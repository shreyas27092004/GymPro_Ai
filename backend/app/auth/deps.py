# app/auth/deps.py
import datetime
import uuid
from typing import Any
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
from ..db import get_db, set_rls
from ..settings import settings
from .security import decode_access_token


class SessionContext(BaseModel):
    user_id: str
    role: str                         # USER | TRAINER | ADMIN (read from DB)
    account_status: str               # must be ACTIVE for standard endpoints
    plan: str | None
    account_email: str                # server-only, masked when shown to client
    full_name: str
    locale: str = "en"
    timezone: str = "Asia/Kolkata"
    age_years: int | None = None
    health_consent: bool = False
    is_minor: bool = False
    cooling_off_active: bool = False  # new admins
    token_version: int = 0

    def public(self) -> dict[str, Any]:
        """Returns public session data safe to expose to client."""
        # Mask account email for privacy
        parts = self.account_email.split("@")
        masked_email = f"{parts[0][:2]}***@{parts[1]}" if len(parts) == 2 and len(parts[0]) > 2 else self.account_email
        return {
            "user_id": self.user_id,
            "role": self.role,
            "account_status": self.account_status,
            "plan": self.plan,
            "full_name": self.full_name,
            "email_masked": masked_email,
            "locale": self.locale,
            "timezone": self.timezone,
            "age_years": self.age_years,
            "health_consent": self.health_consent,
            "is_minor": self.is_minor,
            "cooling_off_active": self.cooling_off_active,
        }


async def load_session_context(db: AsyncSession, user_id_str: str) -> SessionContext | None:
    """Fetch user state from database, computing current role, status, plan, consent, and age."""
    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        return None

    # Fetch user core data
    res = await db.execute(
        text(
            """
            SELECT id, email, full_name, role, account_status, token_version, locale, timezone,
                   cooling_off_until, NOW() as current_time
            FROM users
            WHERE id = :id AND deleted_at IS NULL
            """
        ),
        {"id": user_uuid},
    )
    user_row = res.mappings().one_or_none()
    if not user_row:
        return None

    # Check cooling off
    cooling_off_active = False
    if user_row["cooling_off_until"] and user_row["cooling_off_until"] > user_row["current_time"]:
        cooling_off_active = True

    # Fetch active plan
    m_res = await db.execute(
        text("SELECT plan_code FROM memberships WHERE user_id = :id AND status = 'ACTIVE' LIMIT 1"),
        {"id": user_uuid},
    )
    plan = m_res.scalar_one_or_none()

    # Fetch profile (DOB, health consent)
    p_res = await db.execute(
        text("SELECT date_of_birth, health_data_consent_at FROM member_profiles WHERE user_id = :id"),
        {"id": user_uuid},
    )
    prof_row = p_res.mappings().one_or_none()

    age_years = None
    is_minor = False
    health_consent = False

    if prof_row:
        if prof_row["health_data_consent_at"]:
            health_consent = True
        dob = prof_row["date_of_birth"]
        if dob:
            today = datetime.date.today()
            age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            is_minor = age_years < 18

    tz = user_row["timezone"] or "Asia/Kolkata"

    return SessionContext(
        user_id=str(user_row["id"]),
        role=user_row["role"],
        account_status=user_row["account_status"],
        plan=plan,
        account_email=user_row["email"],
        full_name=user_row["full_name"],
        locale=user_row["locale"] or "en",
        timezone=tz,
        age_years=age_years,
        health_consent=health_consent,
        is_minor=is_minor,
        cooling_off_active=cooling_off_active,
        token_version=user_row["token_version"],
    )


async def get_session(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> SessionContext:
    """Validate Bearer RS256 token and load live state from database."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    raw_token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = decode_access_token(raw_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
        )
    except (jwt.InvalidSignatureError, jwt.InvalidAlgorithmError, jwt.DecodeError, jwt.PyJWTError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    ctx = await load_session_context(db, sub)
    if ctx is None or claims.get("ver") != ctx.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")

    if ctx.account_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ACCOUNT_NOT_ACTIVE", "status": ctx.account_status},
        )

    # Automatically set RLS context for the request session
    await set_rls(db, ctx.user_id, ctx.role)
    return ctx


def require_role(*roles: str):
    async def dep(s: SessionContext = Depends(get_session)) -> SessionContext:
        if s.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return s
    return dep


def require_not_cooling_off(s: SessionContext = Depends(get_session)) -> SessionContext:
    if s.cooling_off_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "COOLING_OFF_ACTIVE"},
        )
    return s
