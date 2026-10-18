# app/auth/admin_router.py
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db, set_rls_system
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


class IssueTriageBody(BaseModel):
    status: str = Field(..., pattern="^(?i)(NEW|IN_REVIEW|ACTIONED|CLOSED)$")
    admin_action: str | None = Field(default=None, pattern="^(?i)(CONTACT_USER|WARN_TRAINER|ESCALATE|NONE)$")
    note: str | None = None


@admin_router.get("/issues", status_code=status.HTTP_200_OK)
async def api_get_issues(
    status_filter: str | None = None,
    severity_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> list[dict[str, Any]]:
    await set_rls_system(db)
    query = """
        SELECT id, category, severity, status, ai_summary, admin_action, handled_at, created_at
        FROM issue_reports
        WHERE 1=1
    """
    params: dict[str, Any] = {}
    if status_filter:
        query += " AND status = :st"
        params["st"] = status_filter.upper()
    if severity_filter:
        query += " AND severity = :sev"
        params["sev"] = severity_filter.upper()
    query += " ORDER BY created_at DESC LIMIT 100"

    res = await db.execute(text(query), params)
    return [
        {
            "issue_id": str(r["id"]),
            "reporter": "a member",
            "category": r["category"],
            "severity": r["severity"],
            "status": r["status"],
            "summary": r["ai_summary"],
            "admin_action": r["admin_action"],
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            "handled_at": r["handled_at"].isoformat() if r["handled_at"] and hasattr(r["handled_at"], "isoformat") else str(r["handled_at"]) if r["handled_at"] else None,
        }
        for r in res.mappings().all()
    ]


@admin_router.get("/issues/{issue_id}", status_code=status.HTTP_200_OK)
async def api_get_issue_detail(
    issue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    res = await db.execute(
        text("SELECT id, category, severity, status, user_words, ai_summary, admin_action, handled_by, handled_at, created_at FROM issue_reports WHERE id = :id"),
        {"id": issue_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    return {
        "issue_id": str(row["id"]),
        "reporter": "a member",
        "category": row["category"],
        "severity": row["severity"],
        "status": row["status"],
        "user_words": row["user_words"],
        "ai_summary": row["ai_summary"],
        "admin_action": row["admin_action"],
        "handled_by": str(row["handled_by"]) if row["handled_by"] else None,
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "handled_at": row["handled_at"].isoformat() if row["handled_at"] and hasattr(row["handled_at"], "isoformat") else str(row["handled_at"]) if row["handled_at"] else None,
    }


@admin_router.post("/issues/{issue_id}/triage", status_code=status.HTTP_200_OK)
async def api_triage_issue(
    issue_id: uuid.UUID,
    body: IssueTriageBody,
    db: AsyncSession = Depends(get_db),
    admin: SessionContext = Depends(require_role("ADMIN")),
) -> dict[str, Any]:
    await set_rls_system(db)
    st = body.status.upper()
    act = body.admin_action.upper() if body.admin_action else None

    res = await db.execute(
        text(
            """
            UPDATE issue_reports
            SET status = :st, admin_action = :act, handled_by = :aid, handled_at = NOW()
            WHERE id = :id
            RETURNING id
            """
        ),
        {"id": issue_id, "st": st, "act": act, "aid": uuid.UUID(admin.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    await db.commit()

    return {"ok": True, "issue_id": str(issue_id), "status": st, "admin_action": act}

