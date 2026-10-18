# app/executor/bundles.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext, get_session
from ..db import get_db, set_rls_system
from .handlers import run_action
from .single import ActionObj


router = APIRouter()


async def step_results(db: AsyncSession, bundle_id: uuid.UUID) -> list[dict[str, Any]]:
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT step_no, type, status, result, summary
            FROM pending_actions
            WHERE bundle_id = :bid
            ORDER BY step_no ASC
            """
        ),
        {"bid": bundle_id},
    )
    return [
        {
            "step_no": row["step_no"],
            "type": row["type"],
            "status": row["status"],
            "result": row["result"],
            "summary": row["summary"],
        }
        for row in res.mappings().all()
    ]


async def stored_results(db: AsyncSession, bundle_row: dict[str, Any]) -> dict[str, Any]:
    steps = await step_results(db, bundle_row["id"])
    return {
        "status": bundle_row["status"],
        "bundle_id": str(bundle_row["id"]),
        "steps": steps,
    }


async def run_bundle_steps(db: AsyncSession, s: SessionContext, bundle_id: uuid.UUID) -> dict[str, Any]:
    """Runs or resumes bundle steps in topological step_no order."""
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, bundle_id, step_no, depends_on, type, payload, status, result, summary, expires_at
            FROM pending_actions
            WHERE bundle_id = :bid
            ORDER BY step_no ASC
            """
        ),
        {"bid": bundle_id},
    )
    steps = res.mappings().all()
    done: dict[int, str] = {
        st["step_no"]: st["status"]
        for st in steps
        if st["status"] in ("EXECUTED", "FAILED", "SKIPPED")
    }

    for st in steps:
        step_no = st["step_no"]
        if step_no in done:
            continue

        deps = st["depends_on"] or []
        # If any dependency did not succeed, skip this dependent step
        if any(done.get(d) != "EXECUTED" for d in deps):
            await set_rls_system(db)
            await db.execute(
                text(
                    """
                    UPDATE pending_actions
                    SET status = 'SKIPPED', result = CAST(:res AS jsonb), executed_at = NOW()
                    WHERE id = :aid
                    """
                ),
                {
                    "aid": st["id"],
                    "res": json.dumps({"ok": False, "error": "DEPENDENCY_FAILED"}),
                },
            )
            await db.commit()
            done[step_no] = "SKIPPED"
            continue

        # Each step executes in its own transaction
        try:
            await set_rls_system(db)
            act_res = await db.execute(
                text(
                    """
                    SELECT id, user_id, bundle_id, type, payload, status, result, expires_at
                    FROM pending_actions
                    WHERE id = :aid
                    FOR UPDATE
                    """
                ),
                {"aid": st["id"]},
            )
            act_row = act_res.mappings().one()
            action = ActionObj(act_row)
            result = await run_action(db, s, action)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        if result.get("awaiting"):
            await set_rls_system(db)
            await db.execute(
                text("UPDATE action_bundles SET status = 'AWAITING_PAYMENT' WHERE id = :bid"),
                {"bid": bundle_id},
            )
            await db.commit()
            return {
                "status": "AWAITING_PAYMENT",
                "bundle_id": str(bundle_id),
                "payment": result["awaiting"],
                "steps": await step_results(db, bundle_id),
            }

        done[step_no] = "EXECUTED" if result.get("ok") else "FAILED"

    statuses = set(done.values())
    if statuses == {"EXECUTED"}:
        final_status = "EXECUTED"
    elif "EXECUTED" not in statuses:
        final_status = "FAILED"
    else:
        final_status = "PARTIAL"

    await set_rls_system(db)
    await db.execute(
        text(
            """
            UPDATE action_bundles
            SET status = :st, executed_at = NOW()
            WHERE id = :bid
            """
        ),
        {"bid": bundle_id, "st": final_status},
    )
    await db.commit()

    return {
        "status": final_status,
        "bundle_id": str(bundle_id),
        "steps": await step_results(db, bundle_id),
    }


@router.post("/bundles/{bundle_id}/confirm")
async def confirm_bundle(
    bundle_id: uuid.UUID,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Confirms and executes an action bundle step-by-step with dependency tracking."""
    try:
        await set_rls_system(db)
        res = await db.execute(
            text(
                """
                SELECT id, user_id, status, summary, expires_at
                FROM action_bundles
                WHERE id = :bid
                FOR UPDATE
                """
            ),
            {"bid": bundle_id},
        )
        bundle = res.mappings().one_or_none()
        if not bundle or str(bundle["user_id"]) != s.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")

        if bundle["status"] != "PENDING":
            return await stored_results(db, bundle)

        now = datetime.now(timezone.utc)
        exp = bundle["expires_at"]
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if exp < now:
            await db.execute(
                text("UPDATE action_bundles SET status = 'EXPIRED' WHERE id = :bid"),
                {"bid": bundle_id},
            )
            await db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACTION_EXPIRED")

        await db.execute(
            text("UPDATE action_bundles SET status = 'CONFIRMING' WHERE id = :bid"),
            {"bid": bundle_id},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await run_bundle_steps(db, s, bundle_id)
