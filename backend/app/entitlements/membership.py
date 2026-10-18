# app/entitlements/membership.py
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import uuid
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..messaging.outbox import enqueue


@dataclass
class PriceDiffQuote:
    from_plan: str | None
    to_plan: str
    cycle: str
    delta_per_cycle: Decimal
    prorated_today: Decimal
    next_billing_date: date
    currency: str = "INR"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["delta_per_cycle"] = float(self.delta_per_cycle)
        d["prorated_today"] = float(self.prorated_today)
        d["next_billing_date"] = self.next_billing_date.isoformat()
        return d


async def list_membership_plans(db: AsyncSession) -> list[dict[str, Any]]:
    res = await db.execute(
        text(
            """
            SELECT code, display_name, price_monthly, price_annual, currency, perks, sort_order, is_active
            FROM membership_plans
            WHERE is_active = TRUE
            ORDER BY sort_order ASC
            """
        )
    )
    return [dict(r) for r in res.mappings().all()]


async def get_highest_plan(db: AsyncSession) -> dict[str, Any]:
    res = await db.execute(
        text(
            """
            SELECT code, display_name, price_monthly, price_annual, currency, perks, sort_order
            FROM membership_plans
            WHERE is_active = TRUE
            ORDER BY sort_order DESC
            LIMIT 1
            """
        )
    )
    row = res.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=500, detail="No active membership plans found.")
    return dict(row)


async def get_active_membership(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any] | None:
    res = await db.execute(
        text(
            """
            SELECT m.id, m.user_id, m.plan_code, m.status, m.billing_cycle, m.price_paid,
                   m.start_date, m.end_date, m.auto_renew, m.replaced_by,
                   mp.display_name, mp.perks
            FROM memberships m
            JOIN membership_plans mp ON m.plan_code = mp.code
            WHERE m.user_id = :uid AND m.status = 'ACTIVE'
            LIMIT 1
            """
        ),
        {"uid": user_id},
    )
    row = res.mappings().one_or_none()
    return dict(row) if row else None


async def price_diff(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_plan_code: str,
    cycle: str = "MONTHLY",
    as_of_date: date | None = None,
) -> PriceDiffQuote:
    """
    Computes proration math for moving to to_plan_code.
    If upgrading an active membership:
      prorated_today = (delta_per_cycle * remaining_days) / total_days
      Applies minimum charge of 1.00 INR when positive.
      Next billing date stays the end date of the current cycle.
    If new subscription:
      prorated_today = full cycle price.
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Target plan
    t_res = await db.execute(
        text("SELECT code, display_name, price_monthly, price_annual, currency, sort_order FROM membership_plans WHERE code = :code AND is_active = TRUE"),
        {"code": to_plan_code.upper()},
    )
    to_plan = t_res.mappings().one_or_none()
    if not to_plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "PLAN_UNAVAILABLE"})

    to_price = Decimal(str(to_plan["price_monthly"])) if cycle.upper() == "MONTHLY" else Decimal(str(to_plan["price_annual"]))
    currency = to_plan["currency"]

    # Active membership
    old_m = await get_active_membership(db, user_id)

    if not old_m:
        # Brand new membership
        next_billing = as_of_date + timedelta(days=365 if cycle.upper() == "ANNUAL" else 30)
        return PriceDiffQuote(
            from_plan=None,
            to_plan=to_plan["code"],
            cycle=cycle.upper(),
            delta_per_cycle=to_price,
            prorated_today=to_price,
            next_billing_date=next_billing,
            currency=currency,
        )

    from_plan_code = old_m["plan_code"]
    f_res = await db.execute(
        text("SELECT code, display_name, price_monthly, price_annual, sort_order FROM membership_plans WHERE code = :code"),
        {"code": from_plan_code},
    )
    from_plan = f_res.mappings().one_or_none()
    from_price = Decimal(str(from_plan["price_monthly"])) if cycle.upper() == "MONTHLY" else Decimal(str(from_plan["price_annual"]))

    if to_plan["code"] == from_plan["code"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ALREADY_ON_PLAN", "message": f"You are already on the {to_plan['code']} plan."},
        )

    if to_plan["sort_order"] < from_plan["sort_order"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "DOWNGRADE_NOT_ALLOWED", "message": "Downgrades take effect at renewal and are handled by staff in v1."},
        )

    delta = to_price - from_price
    cycle_start = old_m["start_date"]
    cycle_end = old_m["end_date"]

    total_days = (cycle_end - cycle_start).days
    if total_days <= 0:
        total_days = 30

    remaining_days = (cycle_end - as_of_date).days

    if remaining_days <= 0:
        prorated_today = delta
        next_billing = as_of_date + timedelta(days=365 if cycle.upper() == "ANNUAL" else 30)
    else:
        prorated_raw = (delta * Decimal(remaining_days)) / Decimal(total_days)
        prorated_today = prorated_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Minimum charge: 1.00 INR when positive
        if Decimal("0.00") < prorated_today < Decimal("1.00"):
            prorated_today = Decimal("1.00")
        next_billing = cycle_end

    return PriceDiffQuote(
        from_plan=from_plan_code,
        to_plan=to_plan["code"],
        cycle=cycle.upper(),
        delta_per_cycle=delta,
        prorated_today=prorated_today,
        next_billing_date=next_billing,
        currency=currency,
    )


async def execute_upgrade(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_plan_code: str,
    cycle: str = "MONTHLY",
    as_of_date: date | None = None,
    payment_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """
    Executes an atomic membership upgrade:
    1. Replaces old membership (status='REPLACED', end_date=today).
    2. Inserts new active membership with prorated price.
    3. Links old.replaced_by = new.id.
    4. Enqueues PLAN_CHANGED email.
    """
    if as_of_date is None:
        as_of_date = date.today()

    quote = await price_diff(db, user_id, to_plan_code, cycle, as_of_date)

    # Lock old active membership
    res = await db.execute(
        text("SELECT id, plan_code FROM memberships WHERE user_id = :uid AND status = 'ACTIVE' FOR UPDATE"),
        {"uid": user_id},
    )
    old = res.mappings().one_or_none()

    if old and old["plan_code"] != quote.from_plan:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "CONFLICT", "message": "Current plan changed since quote."})

    # End old membership as REPLACED and set end_date = today to free uq_one_active_membership
    if old:
        await db.execute(
            text("UPDATE memberships SET status = 'REPLACED', end_date = :td WHERE id = :id"),
            {"td": as_of_date, "id": old["id"]},
        )
        await db.flush()

    new_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date, auto_renew)
            VALUES (:id, :uid, :code, 'ACTIVE', :cycle, :price, :st, :et, TRUE)
            """
        ),
        {
            "id": new_id,
            "uid": user_id,
            "code": quote.to_plan,
            "cycle": quote.cycle,
            "price": quote.prorated_today,
            "st": as_of_date,
            "et": quote.next_billing_date,
        },
    )

    if old:
        await db.execute(
            text("UPDATE memberships SET replaced_by = :nid WHERE id = :id"),
            {"nid": new_id, "id": old["id"]},
        )

    # Notification & audit
    await enqueue(
        db,
        user_id=user_id,
        routing_key="email.plan",
        template="PLAN_CHANGED",
        params={"plan": quote.to_plan},
        dedupe_key=f"plan:{new_id}",
    )

    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:uid, 'MEMBERSHIP_UPGRADED', 'memberships', :nid, CAST(:det AS jsonb))
            """
        ),
        {
            "uid": user_id,
            "nid": new_id,
            "det": str({
                "from_plan": quote.from_plan,
                "to_plan": quote.to_plan,
                "price_paid": str(quote.prorated_today),
                "next_billing_date": quote.next_billing_date.isoformat(),
            }).replace("'", '"'),
        },
    )

    return {
        "ok": True,
        "membership_id": str(new_id),
        "plan": quote.to_plan,
        "quote": quote.to_dict(),
    }
