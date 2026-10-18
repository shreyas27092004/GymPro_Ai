# app/payments/service.py
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext
from ..db import set_rls_system
from ..messaging.outbox import enqueue
from ..settings import settings
from .provider import get_provider, to_minor


@dataclass
class PayState:
    state: str  # "PAID" | "AWAITING" | "FAILED"
    id: uuid.UUID | None = None
    checkout: dict[str, Any] | None = None
    error: str | None = None


class QuoteObj:
    def __init__(self, data: dict[str, Any]):
        self.from_plan = data.get("from_plan")
        self.to_plan = data.get("to_plan")
        self.cycle = data.get("cycle", "MONTHLY")
        self.currency = data.get("currency", "INR")
        self.delta_per_cycle = Decimal(str(data.get("delta_per_cycle", 0)))
        self.prorated_today = Decimal(str(data.get("prorated_today", 0)))
        nbd = data.get("next_billing_date")
        if isinstance(nbd, (datetime, date)):
            self.next_billing_date = nbd
        elif isinstance(nbd, str) and nbd:
            self.next_billing_date = date.fromisoformat(nbd.split("T")[0])
        else:
            self.next_billing_date = date.today()


async def begin(
    db: AsyncSession,
    s: SessionContext,
    action: Any,
    quote: Any,
) -> PayState:
    """
    Initiates payment for an action.
    - If disabled or (production and mock), fails with PAYMENT_PROVIDER_REQUIRED.
    - Replay-safe: if payment already exists for action_id, returns existing state.
    - If 0 amount or mock, marks PAID.
    - If razorpay, creates order via provider and returns AWAITING with checkout details.
    """
    mode = settings.payments_mode
    if mode == "disabled" or (settings.env == "production" and mode == "mock"):
        return PayState(state="FAILED", error="PAYMENT_PROVIDER_REQUIRED")

    action_id = getattr(action, "id", None) or action["id"]
    await set_rls_system(db)

    # Replay safety check: one payment per action
    res = await db.execute(
        text(
            """
            SELECT id, user_id, action_id, provider, purpose, amount_minor, currency,
                   status, razorpay_order_id, quote, expires_at, paid_at
            FROM payments
            WHERE action_id = :aid
            """
        ),
        {"aid": action_id},
    )
    existing = res.mappings().one_or_none()
    if existing:
        st = existing["status"]
        if st == "PAID":
            return PayState(state="PAID", id=existing["id"])
        if st in ("FAILED", "EXPIRED"):
            return PayState(state="FAILED", id=existing["id"], error="PAYMENT_FAILED")
        # Existing open payment
        exp = existing["expires_at"]
        exp_iso = exp.isoformat() if hasattr(exp, "isoformat") else str(exp)
        checkout = {
            "payment_id": str(existing["id"]),
            "key_id": settings.razorpay_key_id or "",
            "order_id": existing["razorpay_order_id"],
            "amount_minor": existing["amount_minor"],
            "currency": existing["currency"],
            "description": getattr(action, "summary", "")[:120],
            "expires_at": exp_iso,
        }
        return PayState(state="AWAITING", id=existing["id"], checkout=checkout)

    amount_minor = to_minor(getattr(quote, "prorated_today", 0))
    currency = getattr(quote, "currency", "INR")
    quote_dict = {
        "from_plan": getattr(quote, "from_plan", None),
        "to_plan": getattr(quote, "to_plan", None),
        "cycle": getattr(quote, "cycle", "MONTHLY"),
        "currency": currency,
        "delta_per_cycle": float(getattr(quote, "delta_per_cycle", 0)),
        "prorated_today": float(getattr(quote, "prorated_today", 0)),
        "next_billing_date": (
            quote.next_billing_date.isoformat()
            if hasattr(getattr(quote, "next_billing_date", None), "isoformat")
            else str(getattr(quote, "next_billing_date", ""))
        ),
    }

    payment_id = uuid.uuid4()
    if amount_minor == 0 or mode == "mock":
        prov_name = "NONE" if amount_minor == 0 else "MOCK"
        await db.execute(
            text(
                """
                INSERT INTO payments (
                    id, user_id, action_id, provider, purpose, amount_minor,
                    currency, status, quote, expires_at, paid_at
                ) VALUES (
                    :id, :uid, :aid, :prov, 'PLAN_CHANGE', :amt,
                    :curr, 'PAID', CAST(:quote AS jsonb), NOW() + INTERVAL '15 minutes', NOW()
                )
                """
            ),
            {
                "id": payment_id,
                "uid": uuid.UUID(s.user_id),
                "aid": action_id,
                "prov": prov_name,
                "amt": amount_minor,
                "curr": currency,
                "quote": json.dumps(quote_dict),
            },
        )
        return PayState(state="PAID", id=payment_id)

    # Real mode (razorpay or test FakeProvider)
    prov = get_provider()
    order = await prov.create_order(
        amount_minor=amount_minor,
        currency=currency,
        receipt=payment_id.hex,
        notes={"action_id": str(action_id)},
    )
    order_id = order["id"]

    await db.execute(
        text(
            """
            INSERT INTO payments (
                id, user_id, action_id, provider, purpose, amount_minor,
                currency, status, razorpay_order_id, quote, expires_at
            ) VALUES (
                :id, :uid, :aid, 'RAZORPAY', 'PLAN_CHANGE', :amt,
                :curr, 'CREATED', :order_id, CAST(:quote AS jsonb), NOW() + INTERVAL '15 minutes'
            )
            """
        ),
        {
            "id": payment_id,
            "uid": uuid.UUID(s.user_id),
            "aid": action_id,
            "amt": amount_minor,
            "curr": currency,
            "order_id": order_id,
            "quote": json.dumps(quote_dict),
        },
    )

    p_chk = await db.execute(
        text("SELECT expires_at FROM payments WHERE id = :id"),
        {"id": payment_id},
    )
    exp = p_chk.scalar_one()
    exp_iso = exp.isoformat() if hasattr(exp, "isoformat") else str(exp)

    checkout = {
        "payment_id": str(payment_id),
        "key_id": settings.razorpay_key_id or "",
        "order_id": order_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "description": getattr(action, "summary", "")[:120],
        "expires_at": exp_iso,
    }
    return PayState(state="AWAITING", id=payment_id, checkout=checkout)


async def resume_bundle(
    db: AsyncSession,
    bundle_id: uuid.UUID,
    s: SessionContext,
) -> dict[str, Any]:
    """Resumes execution of a bundle that was paused on AWAITING_PAYMENT."""
    from ..executor.bundles import run_bundle_steps
    return await run_bundle_steps(db, s, bundle_id)


async def finalize_paid(
    db: AsyncSession,
    order_id: str,
    provider_payment_id: str,
    source: str,
) -> dict[str, Any]:
    """
    Idempotent payment finalization.
    Source: VERIFY | WEBHOOK | RECONCILER.
    Activates membership, enqueues receipt, and resumes any paused bundle.
    """
    from ..executor.handlers import activate_plan
    from ..executor.schemas import ChangePlanPayload

    await set_rls_system(db)
    # 1. Lock payment by razorpay_order_id
    pay_res = await db.execute(
        text(
            """
            SELECT id, user_id, action_id, status, amount_minor, currency, quote, expires_at
            FROM payments
            WHERE razorpay_order_id = :oid
            FOR UPDATE
            """
        ),
        {"oid": order_id},
    )
    pay = pay_res.mappings().one_or_none()
    if not pay:
        return {"ok": False, "error": "UNKNOWN_ORDER"}

    if pay["status"] == "PAID":
        return {"ok": True, "replay": True}

    now = datetime.now(timezone.utc)
    exp = pay["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    # 2. Check for late arrival (expired, already failed, or past expires_at)
    if pay["status"] in ("EXPIRED", "FAILED", "NEEDS_REVIEW") or exp < now:
        await db.execute(
            text(
                """
                UPDATE payments
                SET status = 'NEEDS_REVIEW', razorpay_payment_id = :pid
                WHERE id = :id
                """
            ),
            {"pid": provider_payment_id, "id": pay["id"]},
        )
        amt_major = str(Decimal(pay["amount_minor"]) / Decimal(100))
        await enqueue(
            db,
            user_id=None,
            routing_key="payment.needs_review",
            template="PAYMENT_NEEDS_REVIEW",
            params={
                "payment_id": str(pay["id"]),
                "reason": f"Payment captured after {pay['status'] if pay['status'] in ('EXPIRED', 'FAILED', 'NEEDS_REVIEW') else 'expiry'}",
                "amount": amt_major,
                "currency": pay["currency"],
            },
            dedupe_key=f"review:{pay['id']}",
        )
        await db.commit()
        return {"ok": False, "error": "PAYMENT_NEEDS_REVIEW"}

    # 3. Mark payment as PAID
    await db.execute(
        text(
            """
            UPDATE payments
            SET status = 'PAID', razorpay_payment_id = :pid, paid_at = NOW()
            WHERE id = :id
            """
        ),
        {"pid": provider_payment_id, "id": pay["id"]},
    )

    # 4. Lock action
    act_res = await db.execute(
        text(
            """
            SELECT id, user_id, bundle_id, payload, summary, status
            FROM pending_actions
            WHERE id = :aid
            FOR UPDATE
            """
        ),
        {"aid": pay["action_id"]},
    )
    action = act_res.mappings().one()

    # 5. Load user session context
    from ..auth.deps import load_session_context
    s = await load_session_context(db, str(pay["user_id"]))
    if not s:
        return {"ok": False, "error": "USER_NOT_FOUND"}

    # 6. Activate plan
    p = ChangePlanPayload.model_validate(action["payload"])
    quote_data = pay["quote"]
    if isinstance(quote_data, str):
        quote_data = json.loads(quote_data)
    quote = QuoteObj(quote_data)

    result = await activate_plan(db, s, p, quote, pay["id"])
    if not result.get("ok"):
        # Plan change failed (e.g. current plan changed in between) -> NEEDS_REVIEW
        await db.execute(
            text("UPDATE payments SET status = 'NEEDS_REVIEW' WHERE id = :id"),
            {"id": pay["id"]},
        )
        amt_major = str(Decimal(pay["amount_minor"]) / Decimal(100))
        await enqueue(
            db,
            user_id=None,
            routing_key="payment.needs_review",
            template="PAYMENT_NEEDS_REVIEW",
            params={
                "payment_id": str(pay["id"]),
                "reason": f"Plan activation failed: {result.get('error')}",
                "amount": amt_major,
                "currency": pay["currency"],
            },
            dedupe_key=f"review:{pay['id']}",
        )
        await db.execute(
            text(
                """
                UPDATE pending_actions
                SET status = 'FAILED', result = CAST(:res AS jsonb), executed_at = NOW()
                WHERE id = :aid
                """
            ),
            {"aid": action["id"], "res": json.dumps(result)},
        )
        await db.commit()
        return {"ok": False, "error": "PAYMENT_NEEDS_REVIEW"}

    # 7. Action EXECUTED
    await db.execute(
        text(
            """
            UPDATE pending_actions
            SET status = 'EXECUTED', result = CAST(:res AS jsonb), executed_at = NOW()
            WHERE id = :aid
            """
        ),
        {"aid": action["id"], "res": json.dumps(result)},
    )

    # 8. Enqueue PAYMENT_RECEIPT
    amt_major = str(Decimal(pay["amount_minor"]) / Decimal(100))
    await enqueue(
        db,
        user_id=pay["user_id"],
        routing_key="email.payment",
        template="PAYMENT_RECEIPT",
        params={
            "plan": p.to_plan,
            "amount": amt_major,
            "currency": pay["currency"],
            "payment_date": now.strftime("%Y-%m-%d"),
            "payment_ref": provider_payment_id,
        },
        dedupe_key=f"receipt:{pay['id']}",
    )
    await db.commit()

    # 9. Resume bundle if part of bundle
    if action["bundle_id"]:
        await resume_bundle(db, action["bundle_id"], s)

    return {"ok": True}


async def finalize_unpaid(
    db: AsyncSession,
    payment_id: uuid.UUID,
    code: str,
) -> dict[str, Any]:
    """
    Finalizes an open payment as unpaid (e.g. PAYMENT_CANCELLED or PAYMENT_EXPIRED).
    Marks pending action as FAILED and resumes any bundle (skipping dependents).
    """
    await set_rls_system(db)
    pay_res = await db.execute(
        text(
            """
            SELECT id, user_id, action_id, status
            FROM payments
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": payment_id},
    )
    pay = pay_res.mappings().one_or_none()
    if not pay:
        return {"ok": False, "error": "NOT_FOUND"}

    if pay["status"] == "PAID":
        return {"ok": False, "error": "ALREADY_PAID"}

    new_status = "EXPIRED" if code == "PAYMENT_EXPIRED" else "FAILED"
    await db.execute(
        text(
            """
            UPDATE payments
            SET status = :st, failure_code = :code
            WHERE id = :id
            """
        ),
        {"st": new_status, "code": code, "id": payment_id},
    )

    act_res = await db.execute(
        text(
            """
            SELECT id, user_id, bundle_id
            FROM pending_actions
            WHERE id = :aid
            FOR UPDATE
            """
        ),
        {"aid": pay["action_id"]},
    )
    act = act_res.mappings().one()

    fail_result = {"ok": False, "error": code}
    await db.execute(
        text(
            """
            UPDATE pending_actions
            SET status = 'FAILED', result = CAST(:res AS jsonb), executed_at = NOW()
            WHERE id = :aid
            """
        ),
        {"aid": act["id"], "res": json.dumps(fail_result)},
    )
    await db.commit()

    if act["bundle_id"]:
        from ..auth.deps import load_session_context
        s = await load_session_context(db, str(act["user_id"]))
        if s:
            await resume_bundle(db, act["bundle_id"], s)

    return {"ok": True, "status": new_status}
