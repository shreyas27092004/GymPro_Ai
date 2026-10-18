# app/auth/roles.py
import datetime
import json
import uuid
from typing import Any
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system
from ..messaging.outbox import enqueue
from ..settings import settings
from .security import (
    code_matches,
    hash_password,
    new_admin_code,
    new_token,
    phone_hash,
    sha256,
    verify_password,
)

DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "10minutemail.com",
    "guerrillamail.com",
    "sharklasers.com",
    "throwawaymail.com",
    "yopmail.com",
}


def is_disposable_email(email: str) -> bool:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return domain in DISPOSABLE_DOMAINS


async def any_active_admin(db: AsyncSession) -> bool:
    """Checks if any active admin currently exists in the system."""
    res = await db.execute(
        text("SELECT 1 FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL LIMIT 1")
    )
    return res.scalar_one_or_none() is not None


async def active_admins(db: AsyncSession) -> list[dict[str, Any]]:
    """Returns all active administrators."""
    res = await db.execute(
        text("SELECT id, email, full_name FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL")
    )
    return [dict(r) for r in res.mappings().all()]


async def create_trainer_request(
    db: AsyncSession,
    user_id: uuid.UUID,
    specializations: list[str] | None = None,
    claimed_certifications: list[str] | None = None,
    bio: str | None = None,
) -> uuid.UUID:
    """Creates a trainer role request and application record."""
    # Check if applicant was rejected within the last 7 days (Section 4.2 rule 6)
    r_check = await db.execute(
        text(
            """
            SELECT 1 FROM role_requests
            WHERE user_id = :uid AND requested_role = 'TRAINER' AND status = 'REJECTED'
              AND decided_at > NOW() - INTERVAL '7 days'
            """
        ),
        {"uid": user_id},
    )
    if r_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "REJECTED_WAIT_7_DAYS", "message": "Rejected applicants must wait 7 days before reapplying"},
        )

    # Fetch user for risk hints
    u_res = await db.execute(
        text("SELECT email, phone_hash FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    user_row = u_res.mappings().one_or_none()
    duplicate_phone = False
    disposable_email = False
    if user_row:
        disposable_email = is_disposable_email(user_row["email"])
        if user_row["phone_hash"]:
            ph_res = await db.execute(
                text("SELECT 1 FROM users WHERE phone_hash = :ph AND id != :uid LIMIT 1"),
                {"ph": user_row["phone_hash"], "uid": user_id},
            )
            duplicate_phone = ph_res.scalar_one_or_none() is not None

    risk_hints = {
        "duplicate_phone": duplicate_phone,
        "disposable_email": disposable_email,
    }

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

    specs = specializations or []
    certs = claimed_certifications or []
    bio_text = bio or ""

    await db.execute(
        text(
            """
            INSERT INTO trainer_applications (request_id, specializations, claimed_certifications, bio, risk_hints)
            VALUES (:req_id, :specs, :certs, :bio, CAST(:hints AS jsonb))
            ON CONFLICT (request_id) DO NOTHING
            """
        ),
        {
            "req_id": req_id,
            "specs": specs,
            "certs": certs,
            "bio": bio_text,
            "hints": json.dumps(risk_hints),
        },
    )

    # In-app badge / notice for admins (batched digest, Section 4.2 rule 5)
    await enqueue(
        db,
        user_id=None,
        routing_key="notify.admin.badge",
        template="TRAINER_REQUESTS_DIGEST",
        params={"title": "New Trainer Application", "message": "A new trainer application is pending review."},
        dedupe_key=f"badge:trainer:{datetime.date.today().isoformat()}",
        channel="IN_APP",
    )

    return req_id


async def create_admin_request(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_email: str,
    user_name: str,
    ip: str = "127.0.0.1",
) -> uuid.UUID:
    """Creates an admin one-time code request, subject to system-wide flood limits."""
    # 1. At most 3 pending admin requests in the whole system (Section 4.3 rule 4)
    p_res = await db.execute(
        text("SELECT COUNT(*) FROM role_requests WHERE requested_role = 'ADMIN' AND status = 'PENDING'")
    )
    if (p_res.scalar_one() or 0) >= 3:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": "TOO_MANY_PENDING_ADMIN_REQUESTS"})

    # 2. At most 1 request per email per 24 hours (Section 4.3 rule 4)
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
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"error": "ONE_REQUEST_PER_DAY"})

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

    # Email code to EVERY active admin (never logged, Section 4.3 rule 2)
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
                "applicant_email": user_email,
                "reject_link": f"{settings.frontend_url}/admin/requests/{req_id}",
            },
            dedupe_key=f"admin-code:{req_id}:{adm['id']}",
        )

    return req_id


async def get_trainer_requests(db: AsyncSession) -> list[dict[str, Any]]:
    """Returns the list of pending trainer applications for admin review."""
    res = await db.execute(
        text(
            """
            SELECT rr.id as request_id, rr.user_id, rr.status, rr.created_at,
                   u.full_name, u.email, u.phone,
                   ta.specializations, ta.claimed_certifications, ta.bio, ta.risk_hints
            FROM role_requests rr
            JOIN users u ON rr.user_id = u.id
            LEFT JOIN trainer_applications ta ON ta.request_id = rr.id
            WHERE rr.requested_role = 'TRAINER' AND rr.status = 'PENDING'
            ORDER BY rr.created_at ASC
            """
        )
    )
    return [dict(r) for r in res.mappings().all()]


async def decide_trainer_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    admin_id: uuid.UUID,
    decision: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """
    Processes an admin decision on a trainer request:
    APPROVE, REJECT, or MORE_INFO.
    """
    decision = decision.upper()
    if decision not in ("APPROVE", "REJECT", "MORE_INFO"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "INVALID_DECISION"})

    res = await db.execute(
        text(
            """
            SELECT rr.id, rr.user_id, rr.status, u.email, u.full_name
            FROM role_requests rr
            JOIN users u ON rr.user_id = u.id
            WHERE rr.id = :id AND rr.requested_role = 'TRAINER' AND rr.status = 'PENDING'
            FOR UPDATE
            """
        ),
        {"id": request_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "REQUEST_NOT_FOUND"})

    target_user_id = row["user_id"]

    if decision == "APPROVE":
        # 1. Update request status to APPROVED (satisfies guard_role_change trigger)
        await db.execute(
            text(
                """
                UPDATE role_requests
                SET status = 'APPROVED',
                    decided_by = :aid,
                    decided_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": request_id, "aid": admin_id},
        )

        # 2. Update user role and status in the same transaction
        await db.execute(
            text(
                """
                UPDATE users
                SET role = 'TRAINER',
                    account_status = 'ACTIVE'
                WHERE id = :uid
                """
            ),
            {"uid": target_user_id},
        )

        # 3. Create trainer profile row if missing
        await db.execute(
            text(
                """
                INSERT INTO trainer_profiles (trainer_id, specializations, certifications, bio)
                SELECT rr.user_id, ta.specializations, ta.claimed_certifications, ta.bio
                FROM role_requests rr
                LEFT JOIN trainer_applications ta ON ta.request_id = rr.id
                WHERE rr.id = :id
                ON CONFLICT (trainer_id) DO NOTHING
                """
            ),
            {"id": request_id},
        )

        # 4. Notify applicant
        await enqueue(
            db,
            user_id=target_user_id,
            routing_key="email.trainer_decision",
            template="TRAINER_DECISION",
            params={
                "status": "APPROVED",
                "message": reason or "Your trainer application has been approved! Welcome to GymPro.",
            },
            dedupe_key=f"trainer-decision:{request_id}:approved",
        )

        # 5. Audit log
        await db.execute(
            text(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES (:aid, 'TRAINER_APPROVED', 'users', :uid, CAST('{"request_id": "' || :rid || '"}' AS jsonb))
                """
            ),
            {"aid": admin_id, "uid": target_user_id, "rid": str(request_id)},
        )

    elif decision == "REJECT":
        await db.execute(
            text(
                """
                UPDATE role_requests
                SET status = 'REJECTED',
                    decided_by = :aid,
                    decided_at = NOW(),
                    reason = :reason
                WHERE id = :id
                """
            ),
            {"id": request_id, "aid": admin_id, "reason": reason or "Application does not meet current criteria"},
        )
        await db.execute(
            text("UPDATE users SET account_status = 'REJECTED' WHERE id = :uid"),
            {"uid": target_user_id},
        )
        await enqueue(
            db,
            user_id=target_user_id,
            routing_key="email.trainer_decision",
            template="TRAINER_DECISION",
            params={
                "status": "REJECTED",
                "message": reason or "Your trainer application was not approved at this time.",
            },
            dedupe_key=f"trainer-decision:{request_id}:rejected",
        )
        await db.execute(
            text(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES (:aid, 'TRAINER_REJECTED', 'users', :uid, CAST('{"request_id": "' || :rid || '"}' AS jsonb))
                """
            ),
            {"aid": admin_id, "uid": target_user_id, "rid": str(request_id)},
        )

    elif decision == "MORE_INFO":
        await db.execute(
            text("UPDATE trainer_applications SET review_notes = :reason WHERE request_id = :id"),
            {"id": request_id, "reason": reason},
        )
        await enqueue(
            db,
            user_id=target_user_id,
            routing_key="email.trainer_decision",
            template="TRAINER_DECISION",
            params={
                "status": "MORE_INFO_REQUESTED",
                "message": reason or "Please provide additional documentation regarding your certifications.",
            },
            dedupe_key=f"trainer-decision:{request_id}:more_info",
        )
        await db.execute(
            text(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES (:aid, 'TRAINER_MORE_INFO', 'users', :uid, CAST('{"request_id": "' || :rid || '"}' AS jsonb))
                """
            ),
            {"aid": admin_id, "uid": target_user_id, "rid": str(request_id)},
        )

    return {"ok": True, "decision": decision}


async def get_admin_requests(db: AsyncSession) -> list[dict[str, Any]]:
    """Returns the list of pending admin requests."""
    res = await db.execute(
        text(
            """
            SELECT rr.id as request_id, rr.user_id, rr.created_at, rr.code_expires_at, rr.attempts,
                   u.full_name, u.email
            FROM role_requests rr
            JOIN users u ON rr.user_id = u.id
            WHERE rr.requested_role = 'ADMIN' AND rr.status = 'PENDING'
            ORDER BY rr.created_at ASC
            """
        )
    )
    return [dict(r) for r in res.mappings().all()]


async def reject_admin_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    admin_id: uuid.UUID,
    reason: str | None = None,
) -> dict[str, Any]:
    """Rejects or revokes an admin request."""
    res = await db.execute(
        text("SELECT id, user_id FROM role_requests WHERE id = :id AND requested_role = 'ADMIN' AND status = 'PENDING' FOR UPDATE"),
        {"id": request_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "REQUEST_NOT_FOUND"})

    await db.execute(
        text(
            """
            UPDATE role_requests
            SET status = 'REJECTED',
                decided_by = :aid,
                decided_at = NOW(),
                code_hmac = NULL,
                reason = :reason
            WHERE id = :id
            """
        ),
        {"id": request_id, "aid": admin_id, "reason": reason or "Rejected by administrator"},
    )
    await db.execute(
        text("UPDATE users SET account_status = 'REJECTED' WHERE id = :uid"),
        {"uid": row["user_id"]},
    )
    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:aid, 'ADMIN_REQUEST_REJECTED', 'users', :uid, CAST('{"request_id": "' || :rid || '"}' AS jsonb))
            """
        ),
        {"aid": admin_id, "uid": row["user_id"], "rid": str(request_id)},
    )
    return {"ok": True}


async def suspend_user(
    db: AsyncSession,
    target_user_id: uuid.UUID,
    admin_id: uuid.UUID,
    reason: str | None = None,
) -> dict[str, Any]:
    """Suspends a user or new admin during cooling-off, revoking all active sessions."""
    res = await db.execute(
        text("SELECT id, role, account_status FROM users WHERE id = :uid AND deleted_at IS NULL FOR UPDATE"),
        {"uid": target_user_id},
    )
    u = res.mappings().one_or_none()
    if not u:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "USER_NOT_FOUND"})

    # Set status SUSPENDED, bump token_version to invalidate JWTs
    await db.execute(
        text(
            """
            UPDATE users
            SET account_status = 'SUSPENDED',
                token_version = token_version + 1
            WHERE id = :uid
            """
        ),
        {"uid": target_user_id},
    )

    # Revoke all refresh tokens
    await db.execute(
        text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = :uid AND revoked_at IS NULL"),
        {"uid": target_user_id},
    )

    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:aid, 'USER_SUSPENDED', 'users', :uid, CAST(:det AS jsonb))
            """
        ),
        {
            "aid": admin_id,
            "uid": target_user_id,
            "det": json.dumps({"reason": reason or "Administrative suspension"}),
        },
    )

    return {"ok": True, "status": "SUSPENDED"}


async def create_staff_invite(
    db: AsyncSession,
    email: str,
    role: str,
    admin_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Creates a staff invite (Decision 16: TRAINER invites only; ADMIN invites do not exist).
    """
    role = role.upper()
    if role != "TRAINER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ADMIN_INVITES_DISABLED", "message": "There are no admin invites in v1. Only trainer invites are allowed."},
        )

    raw_token, token_h = new_token()
    invite_id = uuid.uuid4()

    await db.execute(
        text(
            """
            INSERT INTO staff_invites (id, email, role, token_hash, invited_by, expires_at)
            VALUES (:id, :email, 'TRAINER', :th, :aid, NOW() + INTERVAL '7 days')
            """
        ),
        {
            "id": invite_id,
            "email": email.strip().lower(),
            "th": token_h,
            "aid": admin_id,
        },
    )

    invite_link = f"{settings.frontend_url}/register/trainer?invite={raw_token}"
    return {
        "invite_id": str(invite_id),
        "email": email,
        "role": "TRAINER",
        "invite_link": invite_link,
        "token": raw_token,
    }


async def accept_staff_invite(
    db: AsyncSession,
    raw_token: str,
    password: str,
    full_name: str,
    phone: str | None = None,
) -> dict[str, Any]:
    """
    Consumes a staff invite:
    Inserts an APPROVED role_requests row (decided_by = inviter) in the same transaction,
    satisfying the guard_role_change trigger.
    """
    th = sha256(raw_token)
    res = await db.execute(
        text(
            """
            SELECT id, email, role, invited_by, expires_at, used_at, NOW() as current_time
            FROM staff_invites
            WHERE token_hash = :th
            FOR UPDATE
            """
        ),
        {"th": th},
    )
    inv = res.mappings().one_or_none()
    if not inv or inv["used_at"] is not None or inv["expires_at"] < inv["current_time"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "INVALID_OR_EXPIRED_INVITE"})

    # Mark invite used
    await db.execute(
        text("UPDATE staff_invites SET used_at = NOW() WHERE id = :id"),
        {"id": inv["id"]},
    )

    new_user_id = uuid.uuid4()
    pw_hash = hash_password(password)
    p_hash = phone_hash(phone) if phone else None

    # Step A: Insert user initially as USER to satisfy foreign key constraints
    await db.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at, phone, phone_hash)
            VALUES (:uid, :email, :pw, :name, 'USER', 'PENDING_APPROVAL', NOW(), :phone, :phone_hash)
            """
        ),
        {
            "uid": new_user_id,
            "email": inv["email"],
            "pw": pw_hash,
            "name": full_name,
            "phone": phone,
            "phone_hash": p_hash,
        },
    )

    # Step B: Insert pre-approved role request row (Decision 16 & trigger requirement)
    req_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO role_requests (id, user_id, requested_role, status, decided_by, decided_at, expires_at)
            VALUES (:rid, :uid, 'TRAINER', 'APPROVED', :aid, NOW(), NOW() + INTERVAL '14 days')
            """
        ),
        {"rid": req_id, "uid": new_user_id, "aid": inv["invited_by"]},
    )

    # Step C: Update user role to TRAINER (satisfies guard_role_change trigger via the APPROVED role_request)
    await db.execute(
        text(
            """
            UPDATE users SET role = 'TRAINER', account_status = 'ACTIVE' WHERE id = :uid
            """
        ),
        {"uid": new_user_id},
    )

    # Step C: Create trainer profile
    await db.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, specializations, certifications, bio)
            VALUES (:uid, '{}', '{}', '')
            ON CONFLICT (trainer_id) DO NOTHING
            """
        ),
        {"uid": new_user_id},
    )

    # Step D: Audit log
    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:aid, 'TRAINER_INVITE_ACCEPTED', 'users', :uid, CAST(:det AS jsonb))
            """
        ),
        {
            "aid": inv["invited_by"],
            "uid": new_user_id,
            "det": json.dumps({"invite_id": str(inv["id"])}),
        },
    )

    return {"ok": True, "user_id": str(new_user_id), "role": "TRAINER", "status": "ACTIVE"}
