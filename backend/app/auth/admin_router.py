# app/auth/admin_router.py
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from .deps import SessionContext, require_not_cooling_off, require_role
from .roles import (
    create_staff_invite,
    decide_trainer_request,
    get_admin_requests,
    get_trainer_requests,
    reject_admin_request,
    suspend_user,
)

admin_router = APIRouter(prefix="", tags=["Admin"])


class TrainerDecisionBody(BaseModel):
    decision: str = Field(..., pattern="^(?i)(APPROVE|REJECT|MORE_INFO)$")
    reason: str | None = None


class StaffInviteBody(BaseModel):
    email: str
    role: str = "TRAINER"


class SuspendUserBody(BaseModel):
    reason: str | None = None


class BroadcastBody(BaseModel):
    title: str
    content: str
    target_role: str | None = None


@admin_router.get("/trainer-requests", status_code=status.HTTP_200_OK)
async def api_get_trainer_requests(
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> list[dict[str, Any]]:
    return await get_trainer_requests(db)


@admin_router.post("/trainer-requests/{request_id}/decision", status_code=status.HTTP_200_OK)
async def api_decide_trainer_request(
    request_id: uuid.UUID,
    body: TrainerDecisionBody,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
    _not_cooling: SessionContext = Depends(require_not_cooling_off),
) -> dict[str, Any]:
    res = await decide_trainer_request(
        db,
        request_id=request_id,
        admin_id=uuid.UUID(admin.user_id),
        decision=body.decision,
        reason=body.reason,
    )
    await db.commit()
    return res


@admin_router.get("/admin-requests", status_code=status.HTTP_200_OK)
async def api_get_admin_requests(
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> list[dict[str, Any]]:
    return await get_admin_requests(db)


@admin_router.post("/admin-requests/{request_id}/reject", status_code=status.HTTP_200_OK)
async def api_reject_admin_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> dict[str, Any]:
    res = await reject_admin_request(
        db,
        request_id=request_id,
        admin_id=uuid.UUID(admin.user_id),
    )
    await db.commit()
    return res


# Note: Per Section 4.3 rule 7 and Section 17, NO approve endpoint for admin requests exists!
# Admin requests can ONLY be approved via the one-time-code flow on /auth/activate-admin.


@admin_router.post("/users/{target_user_id}/suspend", status_code=status.HTTP_200_OK)
async def api_suspend_user(
    target_user_id: uuid.UUID,
    body: SuspendUserBody | None = None,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> dict[str, Any]:
    reason = body.reason if body else None
    res = await suspend_user(
        db,
        target_user_id=target_user_id,
        admin_id=uuid.UUID(admin.user_id),
        reason=reason,
    )
    await db.commit()
    return res


@admin_router.post("/staff/invites", status_code=status.HTTP_200_OK)
async def api_create_staff_invite(
    body: StaffInviteBody,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
    _not_cooling: SessionContext = Depends(require_not_cooling_off),
) -> dict[str, Any]:
    res = await create_staff_invite(
        db,
        email=body.email,
        role=body.role,
        admin_id=uuid.UUID(admin.user_id),
    )
    await db.commit()
    return res


@admin_router.post("/broadcasts", status_code=status.HTTP_200_OK)
async def api_send_broadcast(
    body: BroadcastBody,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
    _not_cooling: SessionContext = Depends(require_not_cooling_off),
) -> dict[str, Any]:
    # Placeholder broadcast creation; verified in cooling-off tests
    return {"ok": True, "title": body.title}
