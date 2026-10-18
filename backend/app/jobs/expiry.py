# app/jobs/expiry.py
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system


async def run_expiry_jobs(db: AsyncSession) -> dict[str, int]:
    """
    Performs data hygiene expiry jobs (Section 14):
    - Expire pending trainer requests older than 14 days
    - Expire pending admin requests and codes older than 30 minutes
    - Expire unverified accounts older than 7 days
    - Expire pending actions / bundles older than 15 minutes
    """
    await set_rls_system(db)
    counts: dict[str, int] = {}

    # 1. Expire pending trainer requests > 14 days
    res = await db.execute(
        text(
            """
            UPDATE role_requests
            SET status = 'EXPIRED'
            WHERE requested_role = 'TRAINER' AND status = 'PENDING'
              AND created_at < NOW() - INTERVAL '14 days'
            """
        )
    )
    counts["expired_trainer_requests"] = res.rowcount

    # 2. Expire pending admin requests > 30 minutes
    res = await db.execute(
        text(
            """
            UPDATE role_requests
            SET status = 'EXPIRED',
                code_hmac = NULL
            WHERE requested_role = 'ADMIN' AND status = 'PENDING'
              AND (created_at < NOW() - INTERVAL '30 minutes' OR code_expires_at < NOW())
            """
        )
    )
    counts["expired_admin_requests"] = res.rowcount

    # 3. Expire unverified users > 7 days
    res = await db.execute(
        text(
            """
            UPDATE users
            SET account_status = 'EXPIRED'
            WHERE account_status = 'PENDING_EMAIL'
              AND created_at < NOW() - INTERVAL '7 days'
            """
        )
    )
    counts["expired_unverified_users"] = res.rowcount

    # 4. Expire pending actions & bundles > 15 minutes
    res = await db.execute(
        text(
            """
            UPDATE pending_actions
            SET status = 'EXPIRED'
            WHERE status = 'PENDING'
              AND (expires_at < NOW() OR created_at < NOW() - INTERVAL '15 minutes')
            """
        )
    )
    counts["expired_pending_actions"] = res.rowcount

    res = await db.execute(
        text(
            """
            UPDATE action_bundles
            SET status = 'EXPIRED'
            WHERE status = 'PENDING'
              AND (expires_at < NOW() OR created_at < NOW() - INTERVAL '15 minutes')
            """
        )
    )
    counts["expired_action_bundles"] = res.rowcount

    await db.commit()
    return counts
