# app/entitlements/trial.py
from datetime import datetime
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system


async def start_trial(
    db: AsyncSession,
    user_id: uuid.UUID,
    phone_hash: str | None = None,
) -> dict[str, Any] | None:
    """
    Grants 3 free classes within 14 days of verification.
    Enforces uniqueness: once per verified user and once per phone hash.
    Skipped / refused if either user or phone has already received a trial grant.
    """
    await set_rls_system(db)
    # 1. Check if user already has a trial grant
    res = await db.execute(
        text("SELECT id, user_id, phone_hash, classes_total, classes_used, starts_at, expires_at FROM trial_grants WHERE user_id = :uid"),
        {"uid": user_id},
    )
    existing = res.mappings().one_or_none()
    if existing:
        return dict(existing)

    # 2. Check if phone hash has already received a trial
    if phone_hash:
        p_res = await db.execute(
            text("SELECT id FROM trial_grants WHERE phone_hash = :ph"),
            {"ph": phone_hash},
        )
        if p_res.first():
            # Phone hash already consumed a trial
            return None

    # 3. Create trial grant
    trial_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO trial_grants (id, user_id, phone_hash, classes_total, classes_used, starts_at, expires_at)
            VALUES (:id, :uid, :ph, 3, 0, NOW(), NOW() + INTERVAL '14 days')
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"id": trial_id, "uid": user_id, "ph": phone_hash},
    )

    t_chk = await db.execute(
        text("SELECT id, user_id, phone_hash, classes_total, classes_used, starts_at, expires_at FROM trial_grants WHERE id = :id"),
        {"id": trial_id},
    )
    row = t_chk.mappings().one_or_none()
    return dict(row) if row else None


async def get_active_trial(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """
    Returns the user's trial grant if active, unexpired, and has remaining classes.
    """
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, phone_hash, classes_total, classes_used, starts_at, expires_at,
                   (classes_total - classes_used) AS classes_remaining,
                   NOW() as current_time
            FROM trial_grants
            WHERE user_id = :uid
              AND expires_at > NOW()
              AND classes_used < classes_total
            """
        ),
        {"uid": user_id},
    )
    row = res.mappings().one_or_none()
    return dict(row) if row else None


async def consume_trial_class(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """
    Atomically increments classes_used by 1 if trial is active and not exhausted.
    """
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            UPDATE trial_grants
            SET classes_used = classes_used + 1
            WHERE user_id = :uid
              AND expires_at > NOW()
              AND classes_used < classes_total
            RETURNING id, user_id, classes_total, classes_used, expires_at
            """
        ),
        {"uid": user_id},
    )
    row = res.mappings().one_or_none()
    return dict(row) if row else None
