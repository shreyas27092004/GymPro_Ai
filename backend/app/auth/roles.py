# app/auth/roles.py
import json
import uuid
from typing import Any
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..messaging.outbox import enqueue
from ..ratelimit import check_rate_limit
from ..settings import settings
from .security import (
    code_matches,
    new_admin_code,
    phone_hash,
    sha256,
    verify_password,
)


async def any_active_admin(db: AsyncSession) -> bool:
    res = await db.execute(
        text("SELECT 1 FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL LIMIT 1")
    )
    return res.scalar_one_or_none() is not None


async def active_admins(db: AsyncSession) -> list[dict[str, Any]]:
    res = await db.execute(
        text("SELECT id, email, full_name FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL")
    )
    return [dict(r) for r in res.mappings().all()]


async def create_trainer_request(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    req_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO role_requests (id, user_id, requested_role, status, expires_at)
            VALUES (:id, :uid, 'TRAINER', 'PENDING', NOW() + INTERVAL '14 days')
            """
        ),
        {"id": req_id, "uid": user_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO trainer_applications (request_id, specializations, claimed_certifications, bio, risk_hints)
            VALUES (:req_id, '{}', '{}', '', CAST('{}' AS jsonb))
            ON CONFLICT (request_id) DO NOTHING
            """
        ),
        {"req_id": req_id},
    )
    return req_id


async def create_admin_request(db: AsyncSession, user_id: uuid.UUID, user_email: str, user_name: str, ip: str = "127.0.0.1") -> uuid.UUID:
    # 1. At most 3 pending admin requests system-wide
    p_res = await db.execute(
        text("SELECT COUNT(*) FROM role_requests WHERE requested_role = 'ADMIN' AND status = 'PENDING'")
    )
    if (p_res.scalar_one() or 0) >= 3:
        raise HTTPException(status_code=429, detail={"error": "TOO_MANY_PENDING_ADMIN_REQUESTS"})

    # 2. At most 1 request per email per day
    r_res = await db.execute(
        text(
            """
            SELECT COUNT(*) FROM role_requests rr
            JOIN users u ON rr.user_id = u.id
            WHERE u.email = :email AND rr.requested_role = 'ADMIN'
              AND rr.created_at > NOW() - INTERVAL '24 hours'
            """
        ),
        {"email": user_email},
    )
    if (r_res.scalar_one() or 0) >= 1:
        raise HTTPException(status_code=429, detail={"error": "ONE_REQUEST_PER_DAY"})

    # 3. Cancel any older pending admin requests for this user
    await db.execute(
        text("UPDATE role_requests SET status = 'CANCELLED' WHERE user_id = :uid AND requested_role = 'ADMIN' AND status = 'PENDING'"),
        {"uid": user_id},
    )

    code, code_hmac = new_admin_code()
    req_id = uuid.uuid4()
    req_ip_hash = sha256(ip)

    await db.execute(
        text(
            """
            INSERT INTO role_requests (id, user_id, requested_role, status, code_hmac, code_expires_at, expires_at, request_ip_hash)
            VALUES (:id, :uid, 'ADMIN', 'PENDING', :hmac, NOW() + INTERVAL '30 minutes', NOW() + INTERVAL '30 minutes', :ip_hash)
            """
        ),
        {"id": req_id, "uid": user_id, "hmac": code_hmac, "ip_hash": req_ip_hash},
    )

    # Email code to all active admins
    admins = await active_admins(db)
    for adm in admins:
        await enqueue(
            db,
            user_id=adm["id"],
            routing_key="email.admin_code",
            template="ADMIN_CODE",
            params={
                "code": code,
                "name": user_name,
                "email": user_email,
                "reject_link": f"{settings.frontend_url}/admin/requests/{req_id}",
            },
            dedupe_key=f"admin-code:{req_id}:{adm['id']}",
        )

    return req_id
