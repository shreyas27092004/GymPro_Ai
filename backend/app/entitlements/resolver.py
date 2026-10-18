# app/entitlements/resolver.py
from dataclasses import dataclass
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system
from .trial import get_active_trial


@dataclass
class Entitlement:
    can_book: bool
    reason: str | None
    source: str            # "MEMBERSHIP" | "TRIAL" | "NONE"
    remaining: int | None  # None = unlimited
    trial_grant_id: str | None = None


async def active_plan_code(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    res = await db.execute(
        text("SELECT plan_code FROM memberships WHERE user_id = :uid AND status = 'ACTIVE' LIMIT 1"),
        {"uid": user_id},
    )
    row = res.first()
    return row[0] if row else None


async def get_plan_perks(db: AsyncSession, plan_code: str) -> dict[str, Any]:
    res = await db.execute(
        text("SELECT perks FROM membership_plans WHERE code = :code"),
        {"code": plan_code},
    )
    row = res.mappings().one_or_none()
    return dict(row["perks"]) if row and row["perks"] else {}


async def classes_used_this_cycle(db: AsyncSession, user_id: uuid.UUID, start_date: Any = None) -> int:
    """Counts active (non-cancelled) class bookings created in the current membership cycle."""
    await set_rls_system(db)
    if start_date:
        res = await db.execute(
            text(
                """
                SELECT count(*) FROM class_bookings
                WHERE user_id = :uid
                  AND status != 'CANCELLED'
                  AND created_at >= :st
                """
            ),
            {"uid": user_id, "st": start_date},
        )
    else:
        res = await db.execute(
            text(
                """
                SELECT count(*) FROM class_bookings
                WHERE user_id = :uid
                  AND status != 'CANCELLED'
                """
            ),
            {"uid": user_id},
        )
    return res.scalar_one() or 0


def _get_class_attr(cls: Any, attr: str, default: Any = None) -> Any:
    if cls is None:
        return default
    if hasattr(cls, "get"):
        return cls.get(attr, default)
    if hasattr(cls, "__getitem__"):
        try:
            return cls[attr]
        except Exception:
            pass
    return getattr(cls, attr, default)


async def entitlements(
    db: AsyncSession,
    user_id: uuid.UUID,
    cls: Any = None,
    *,
    projected_plan: str | None = None,
) -> Entitlement:
    """
    Membership first, trial second.
    projected_plan comes ONLY from server-validated bundle handoff.
    """
    # 1. Check Active Membership
    plan = projected_plan
    m_start_date = None
    if not plan:
        m_res = await db.execute(
            text(
                """
                SELECT plan_code, start_date
                FROM memberships
                WHERE user_id = :uid AND status = 'ACTIVE'
                LIMIT 1
                """
            ),
            {"uid": user_id},
        )
        m_row = m_res.mappings().one_or_none()
        if m_row:
            plan = m_row["plan_code"]
            m_start_date = m_row["start_date"]

    if plan:
        perks = await get_plan_perks(db, plan)
        allowed_plans = _get_class_attr(cls, "allowed_plans", None)
        if allowed_plans and plan not in allowed_plans:
            return Entitlement(
                can_book=False,
                reason="PLAN_NOT_ALLOWED",
                source="MEMBERSHIP",
                remaining=None,
            )

        cap = perks.get("group_classes_per_month")  # None = unlimited
        if cap is None or projected_plan:
            return Entitlement(
                can_book=True,
                reason=None,
                source="MEMBERSHIP",
                remaining=cap,
            )

        used = await classes_used_this_cycle(db, user_id, m_start_date)
        can_book = used < cap
        return Entitlement(
            can_book=can_book,
            reason=None if can_book else "NO_CREDITS",
            source="MEMBERSHIP",
            remaining=max(cap - used, 0),
        )

    # 2. Check Trial (only when no active membership)
    trial = await get_active_trial(db, user_id)
    if trial:
        trial_eligible = _get_class_attr(cls, "trial_eligible", True)
        remaining = trial["classes_remaining"]
        if cls is None or trial_eligible:
            return Entitlement(
                can_book=True,
                reason=None,
                source="TRIAL",
                remaining=remaining,
                trial_grant_id=str(trial["id"]),
            )
        else:
            return Entitlement(
                can_book=False,
                reason="CLASS_NOT_TRIAL_ELIGIBLE",
                source="TRIAL",
                remaining=remaining,
                trial_grant_id=str(trial["id"]),
            )

    # 3. Neither Membership nor Trial
    return Entitlement(
        can_book=False,
        reason="NO_PLAN_CHOOSE_ONE",
        source="NONE",
        remaining=0,
    )
