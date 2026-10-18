# app/executor/single.py
from datetime import datetime, timezone
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext, get_session
from ..db import get_db, set_rls, set_rls_system
from .handlers import run_action


router = APIRouter()


class ActionObj:
    def __init__(self, row: dict[str, Any]):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.bundle_id = row["bundle_id"]
        self.type = row["type"]
        self.payload = row["payload"]
        self.status = row["status"]
        self.result = row["result"]
        self.expires_at = row["expires_at"]


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: uuid.UUID,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Confirms and executes a single pending action deterministically (no LLM in this path)."""
    try:
        await set_rls_system(db)
        res = await db.execute(
            text(
                """
                SELECT id, user_id, bundle_id, type, payload, status, result, expires_at
                FROM pending_actions
                WHERE id = :aid
                FOR UPDATE
                """
            ),
            {"aid": action_id},
        )
        row = res.mappings().one_or_none()
        if not row or str(row["user_id"]) != s.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")

        action = ActionObj(row)
        if action.bundle_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This action belongs to a bundle; confirm the bundle",
            )

        if action.status in ("EXECUTED", "AWAITING_PAYMENT"):
            return action.result  # Idempotent replay

        now = datetime.now(timezone.utc)
        exp = action.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if action.status != "PENDING" or exp < now:
            if action.status == "PENDING":
                await db.execute(
                    text("UPDATE pending_actions SET status = 'EXPIRED' WHERE id = :aid"),
                    {"aid": action_id},
                )
                await db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACTION_EXPIRED")

        result = await run_action(db, s, action)
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
