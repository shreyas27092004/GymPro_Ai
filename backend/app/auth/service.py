# app/auth/service.py
import datetime
import uuid
from typing import Annotated, Any
import re
from fastapi import HTTPException, status
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..messaging.outbox import enqueue
from ..ratelimit import check_rate_limit
from ..settings import settings
from .roles import (
    any_active_admin,
    create_admin_request,
    create_trainer_request,
)
from .security import (
    code_matches,
    create_access_token,
    hash_password,
    new_token,
    phone_hash,
    sha256,
    verify_password,
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def clean_email(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("Email must be a string")
    v = v.strip().lower()
    if not EMAIL_REGEX.match(v):
        raise ValueError("Invalid email format")
    return v


EmailType = Annotated[str, BeforeValidator(clean_email)]


class RegisterBody(BaseModel):
    email: EmailType
    password: str = Field(min_length=10, max_length=72)
    full_name: str = Field(min_length=1, max_length=100)
    phone: str | None = None
    account_type: str = "USER"  # USER | TRAINER | ADMIN
    # Client might try to pass 'role', which must be strictly ignored
    role: str | None = None


class LoginBody(BaseModel):
    email: EmailType
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class ForgotPasswordBody(BaseModel):
    email: EmailType


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=72)


class AdminActivateBody(BaseModel):
    email: EmailType
    password: str
    code: str


async def register(db: AsyncSession, body: RegisterBody, ip: str = "127.0.0.1") -> dict[str, Any]:
    # Rate limits
    if not check_rate_limit(f"register:ip:{ip}", 10, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})
    if not check_rate_limit(f"register:email:{body.email}", 3, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})

    acc_type = body.account_type.upper() if body.account_type else "USER"
    if acc_type not in ("USER", "TRAINER", "ADMIN"):
        acc_type = "USER"

    # Admin signup bootstrap check
    if acc_type == "ADMIN" and not await any_active_admin(db):
        raise HTTPException(status_code=403, detail={"error": "ADMIN_SIGNUP_UNAVAILABLE"})

    # Check if user already exists
    e_res = await db.execute(
        text("SELECT id, email_verified_at FROM users WHERE email = :email AND deleted_at IS NULL"),
        {"email": body.email},
    )
    existing = e_res.mappings().one_or_none()

    if existing:
        # Enqueue already-registered notification, identical API response (no account enumeration)
        await enqueue(
            db,
            user_id=existing["id"],
            routing_key="email.already_registered",
            template="ALREADY_REGISTERED",
            params={"email": body.email},
            dedupe_key=f"dup:{body.email}:{datetime.date.today().isoformat()}",
        )
        await db.commit()
        return {"ok": True}

    user_id = uuid.uuid4()
    p_hash = phone_hash(body.phone) if body.phone else None
    pw_hash = hash_password(body.password)
    req_role = None if acc_type == "USER" else acc_type

    # ROLE IS ALWAYS 'USER' AT REGISTRATION. Never trusted from client!
    await db.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, requested_role, account_status, phone, phone_hash)
            VALUES (:id, :email, :pw, :name, 'USER', :req_role, 'PENDING_EMAIL', :phone, :phone_hash)
            """
        ),
        {
            "id": user_id,
            "email": body.email,
            "pw": pw_hash,
            "name": body.full_name,
            "req_role": req_role,
            "phone": body.phone,
            "phone_hash": p_hash,
        },
    )

    raw_token, token_h = new_token()
    await db.execute(
        text(
            """
            INSERT INTO email_verifications (user_id, token_hash, expires_at)
            VALUES (:uid, :th, NOW() + INTERVAL '24 hours')
            """
        ),
        {"uid": user_id, "th": token_h},
    )

    await enqueue(
        db,
        user_id=user_id,
        routing_key="email.verify",
        template="VERIFY_EMAIL",
        params={"link": f"{settings.frontend_url}/verify?token={raw_token}"},
        dedupe_key=f"verify:{user_id}:{token_h[:8]}",
    )

    await db.commit()
    return {"ok": True}


async def verify_email(db: AsyncSession, raw_token: str, ip: str = "127.0.0.1") -> dict[str, Any]:
    th = sha256(raw_token)
    res = await db.execute(
        text(
            """
            SELECT v.id, v.user_id, v.expires_at, v.used_at, u.requested_role, u.phone_hash, u.email, u.full_name
            FROM email_verifications v
            JOIN users u ON v.user_id = u.id
            WHERE v.token_hash = :th
            FOR UPDATE OF v
            """
        ),
        {"th": th},
    )
    row = res.mappings().one_or_none()

    now = datetime.datetime.now(datetime.timezone.utc)
    if not row or row["used_at"] is not None or row["expires_at"] < now:
        raise HTTPException(status_code=400, detail={"error": "INVALID_OR_EXPIRED_TOKEN"})

    await db.execute(
        text("UPDATE email_verifications SET used_at = NOW() WHERE id = :id"),
        {"id": row["id"]},
    )
    await db.execute(
        text("UPDATE users SET email_verified_at = NOW() WHERE id = :uid"),
        {"uid": row["user_id"]},
    )

    req_role = row["requested_role"]
    next_status = "ACTIVE"

    if req_role is None:
        # Standard USER becomes ACTIVE and receives trial grant
        await db.execute(
            text("UPDATE users SET account_status = 'ACTIVE' WHERE id = :uid"),
            {"uid": row["user_id"]},
        )
        from ..entitlements.trial import start_trial
        await start_trial(db, row["user_id"], row["phone_hash"])
    elif req_role == "TRAINER":
        next_status = "PENDING_APPROVAL"
        await db.execute(
            text("UPDATE users SET account_status = 'PENDING_APPROVAL' WHERE id = :uid"),
            {"uid": row["user_id"]},
        )
        await create_trainer_request(db, row["user_id"])
    elif req_role == "ADMIN":
        next_status = "PENDING_ADMIN_CODE"
        await db.execute(
            text("UPDATE users SET account_status = 'PENDING_ADMIN_CODE' WHERE id = :uid"),
            {"uid": row["user_id"]},
        )
        await create_admin_request(db, row["user_id"], row["email"], row["full_name"], ip)

    await db.commit()
    return {"status": next_status}


async def issue_tokens(
    db: AsyncSession,
    user_row: dict[str, Any],
    ip: str = "127.0.0.1",
    family_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    uid = user_row["id"]
    t_ver = user_row["token_version"]
    access_token = create_access_token(str(uid), t_ver)

    raw_rf, rf_hash = new_token()
    fid = family_id or uuid.uuid4()
    ip_h = sha256(ip)

    await db.execute(
        text(
            """
            INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at, ip_hash)
            VALUES (:uid, :fid, :th, NOW() + INTERVAL '7 days', :ip_h)
            """
        ),
        {"uid": uid, "fid": fid, "th": rf_hash, "ip_h": ip_h},
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_rf,
        "token_type": "bearer",
        "expires_in": 900,
    }


async def login(db: AsyncSession, email: str, password: str, ip: str = "127.0.0.1") -> dict[str, Any]:
    # Rate limit check
    if not check_rate_limit(f"login:ip:{ip}", 30, 600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})
    if not check_rate_limit(f"login:email:{email}", 10, 600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})

    res = await db.execute(
        text(
            """
            SELECT id, email, password_hash, role, account_status, email_verified_at,
                   failed_logins, locked_until, token_version, NOW() as current_time
            FROM users
            WHERE email = :email AND deleted_at IS NULL
            """
        ),
        {"email": email},
    )
    user = res.mappings().one_or_none()

    # Equal-time password verification: always run bcrypt even if user is None
    ok = verify_password(password, user["password_hash"] if user else None)

    if user and user["locked_until"] and user["locked_until"] > user["current_time"]:
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})

    if not (user and ok):
        if user:
            failed = user["failed_logins"] + 1
            if failed >= 5:
                # Lock for 15 minutes, with exponential backoff
                mult = 2 ** max(0, failed - 5)
                await db.execute(
                    text(
                        """
                        UPDATE users
                        SET failed_logins = :f,
                            locked_until = NOW() + make_interval(mins => :mins)
                        WHERE id = :id
                        """
                    ),
                    {"f": failed, "mins": 15 * mult, "id": user["id"]},
                )
            else:
                await db.execute(
                    text("UPDATE users SET failed_logins = :f WHERE id = :id"),
                    {"f": failed, "id": user["id"]},
                )
            await db.commit()
        raise HTTPException(status_code=401, detail={"error": "INVALID_CREDENTIALS"})

    # Password was correct -> reset failed logins
    await db.execute(
        text("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = :id"),
        {"id": user["id"]},
    )

    if not user["email_verified_at"]:
        raise HTTPException(status_code=403, detail={"error": "EMAIL_NOT_VERIFIED"})

    if user["account_status"] in ("PENDING_APPROVAL", "PENDING_ADMIN_CODE", "REJECTED", "EXPIRED", "SUSPENDED"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"ACCOUNT_{user['account_status']}",
                "show_code_box": user["account_status"] == "PENDING_ADMIN_CODE",
            },
        )

    tokens = await issue_tokens(db, dict(user), ip)
    await db.commit()
    return tokens


async def refresh(db: AsyncSession, raw_refresh: str, ip: str = "127.0.0.1") -> dict[str, Any]:
    th = sha256(raw_refresh)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, family_id, expires_at, rotated_at, revoked_at, NOW() as current_time
            FROM refresh_tokens
            WHERE token_hash = :th
            FOR UPDATE
            """
        ),
        {"th": th},
    )
    row = res.mappings().one_or_none()

    if not row or row["revoked_at"] is not None or row["expires_at"] < row["current_time"]:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if row["rotated_at"] is not None:
        # REUSE DETECTED: Revoke entire family to protect against theft
        await db.execute(
            text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE family_id = :fid"),
            {"fid": row["family_id"]},
        )
        await db.execute(
            text(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES (NULL, 'REFRESH_REUSE_DETECTED', 'refresh_tokens', :id, CAST(:details AS jsonb))
                """
            ),
            {"id": row["id"], "details": '{"threat": "TOKEN_REUSE"}'},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh token reuse detected; session revoked")

    # Mark rotated
    await db.execute(
        text("UPDATE refresh_tokens SET rotated_at = NOW() WHERE id = :id"),
        {"id": row["id"]},
    )

    u_res = await db.execute(
        text("SELECT id, token_version, account_status FROM users WHERE id = :id AND deleted_at IS NULL"),
        {"id": row["user_id"]},
    )
    user = u_res.mappings().one_or_none()
    if not user or user["account_status"] != "ACTIVE":
        raise HTTPException(status_code=401, detail="User inactive")

    tokens = await issue_tokens(db, dict(user), ip, family_id=row["family_id"])
    await db.commit()
    return tokens


async def logout(db: AsyncSession, user_id: str, raw_refresh: str | None = None) -> dict[str, Any]:
    if raw_refresh:
        th = sha256(raw_refresh)
        res = await db.execute(text("SELECT family_id FROM refresh_tokens WHERE token_hash = :th"), {"th": th})
        fid = res.scalar_one_or_none()
        if fid:
            await db.execute(
                text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE family_id = :fid"),
                {"fid": fid},
            )
            await db.commit()
            return {"ok": True}

    await db.execute(
        text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = :uid AND revoked_at IS NULL"),
        {"uid": uuid.UUID(user_id)},
    )
    await db.commit()
    return {"ok": True}


async def forgot_password(db: AsyncSession, email: str, ip: str = "127.0.0.1") -> dict[str, Any]:
    if not check_rate_limit(f"forgot:ip:{ip}", 10, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})
    if not check_rate_limit(f"forgot:email:{email}", 3, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})

    res = await db.execute(
        text("SELECT id, email_verified_at FROM users WHERE email = :email AND deleted_at IS NULL"),
        {"email": email},
    )
    u = res.mappings().one_or_none()

    if u and u["email_verified_at"]:
        # Only one active reset token per user
        await db.execute(
            text("UPDATE password_resets SET used_at = NOW() WHERE user_id = :uid AND used_at IS NULL"),
            {"uid": u["id"]},
        )
        raw_reset, h = new_token()
        await db.execute(
            text(
                """
                INSERT INTO password_resets (user_id, token_hash, expires_at)
                VALUES (:uid, :h, NOW() + INTERVAL '30 minutes')
                """
            ),
            {"uid": u["id"], "h": h},
        )
        await enqueue(
            db,
            user_id=u["id"],
            routing_key="email.reset",
            template="RESET_PASSWORD",
            params={"link": f"{settings.frontend_url}/reset?token={raw_reset}"},
            dedupe_key=f"reset:{u['id']}:{h[:8]}",
        )

    # Identical response whether email exists or not (no account enumeration)
    await db.commit()
    return {"ok": True}


async def reset_password(db: AsyncSession, raw_token: str, new_password: str) -> dict[str, Any]:
    h = sha256(raw_token)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, expires_at, used_at, NOW() as current_time
            FROM password_resets
            WHERE token_hash = :h
            FOR UPDATE
            """
        ),
        {"h": h},
    )
    row = res.mappings().one_or_none()

    if not row or row["used_at"] is not None or row["expires_at"] < row["current_time"]:
        raise HTTPException(status_code=400, detail={"error": "INVALID_OR_EXPIRED_TOKEN"})

    await db.execute(
        text("UPDATE password_resets SET used_at = NOW() WHERE id = :id"),
        {"id": row["id"]},
    )

    new_hash = hash_password(new_password)
    # Bump token_version to invalidate all active access JWTs
    await db.execute(
        text(
            """
            UPDATE users
            SET password_hash = :h,
                token_version = token_version + 1
            WHERE id = :uid
            """
        ),
        {"h": new_hash, "uid": row["user_id"]},
    )

    # Revoke all refresh tokens for this user
    await db.execute(
        text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = :uid AND revoked_at IS NULL"),
        {"uid": row["user_id"]},
    )

    await enqueue(
        db,
        user_id=row["user_id"],
        routing_key="email.password_changed",
        template="PASSWORD_CHANGED",
        params={},
        dedupe_key=f"pwchg:{row['user_id']}:{row['id']}",
    )

    await db.commit()
    return {"ok": True}


async def activate_admin(
    db: AsyncSession,
    email: str,
    password: str,
    code: str,
    ip: str = "127.0.0.1",
) -> dict[str, Any]:
    if not check_rate_limit(f"activate:ip:{ip}", 10, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})
    if not check_rate_limit(f"activate:email:{email}", 10, 3600):
        raise HTTPException(status_code=429, detail={"error": "TRY_LATER"})

    res = await db.execute(
        text(
            """
            SELECT id, full_name, email, password_hash, account_status, token_version
            FROM users
            WHERE email = :email AND deleted_at IS NULL
            FOR UPDATE
            """
        ),
        {"email": email},
    )
    u = res.mappings().one_or_none()

    if not u or not verify_password(password, u["password_hash"]) or u["account_status"] != "PENDING_ADMIN_CODE":
        raise HTTPException(status_code=401, detail={"error": "INVALID_CREDENTIALS"})

    r_res = await db.execute(
        text(
            """
            SELECT id, code_hmac, code_expires_at, attempts, NOW() as current_time
            FROM role_requests
            WHERE user_id = :uid AND requested_role = 'ADMIN' AND status = 'PENDING'
            FOR UPDATE
            """
        ),
        {"uid": u["id"]},
    )
    req = r_res.mappings().one_or_none()

    if not req or req["code_expires_at"] < req["current_time"]:
        if req:
            await db.execute(text("UPDATE role_requests SET status = 'EXPIRED' WHERE id = :id"), {"id": req["id"]})
        await db.execute(text("UPDATE users SET account_status = 'EXPIRED' WHERE id = :uid"), {"uid": u["id"]})
        await db.commit()
        raise HTTPException(status_code=410, detail={"error": "CODE_EXPIRED"})

    if req["attempts"] >= 5:
        await db.execute(text("UPDATE role_requests SET status = 'CANCELLED' WHERE id = :id"), {"id": req["id"]})
        await db.execute(text("UPDATE users SET account_status = 'EXPIRED' WHERE id = :uid"), {"uid": u["id"]})
        await db.commit()
        raise HTTPException(status_code=423, detail={"error": "REQUEST_LOCKED"})

    if not code_matches(code, req["code_hmac"]):
        await db.execute(
            text("UPDATE role_requests SET attempts = attempts + 1 WHERE id = :id"),
            {"id": req["id"]},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail={"error": "INVALID_CODE"})

    # Successful activation: single use -> HMAC destroyed
    await db.execute(
        text("UPDATE role_requests SET status = 'APPROVED', decided_at = NOW(), code_hmac = '0000000000000000000000000000000000000000000000000000000000000000' WHERE id = :id"),
        {"id": req["id"]},
    )

    # Role change satisfies guard_role_change trigger because APPROVED request exists within 5 mins
    await db.execute(
        text(
            """
            UPDATE users
            SET role = 'ADMIN',
                account_status = 'ACTIVE',
                cooling_off_until = NOW() + INTERVAL '24 hours'
            WHERE id = :uid
            """
        ),
        {"uid": u["id"]},
    )

    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:uid, 'ADMIN_ACTIVATED', 'users', :uid, CAST('{"method": "ONE_TIME_CODE"}' AS jsonb))
            """
        ),
        {"uid": u["id"]},
    )

    tokens = await issue_tokens(db, dict(u), ip)
    await db.commit()
    return tokens
