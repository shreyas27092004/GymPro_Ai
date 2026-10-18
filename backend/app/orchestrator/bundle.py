# app/orchestrator/bundle.py
from datetime import datetime, timezone
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system
from ..settings import settings
from ..tools.registry import RunContext


def headline(steps: list[tuple[dict[str, Any], Any]]) -> str:
    parts = []
    for intent, env in steps:
        agent = intent.get("agent", "")
        name = intent.get("name", "")
        if agent == "MEMBERSHIP" or "UPGRADE" in name:
            parts.append("Upgrade plan")
        elif agent == "SCHEDULE" or "BOOK" in name:
            parts.append("Book class")
        elif agent == "COMMS" or "EMAIL" in name:
            parts.append("Email details")
        elif agent == "SUPPORT" or "REPORT" in name:
            parts.append("Submit report")
        else:
            parts.append(name.replace("_", " ").title())
    return ", ".join(parts)


async def build_bundle(
    db: AsyncSession,
    ctx: RunContext,
    plan: dict[str, Any],
    outputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Builds a deterministic bundle card from validated agent envelopes."""
    steps = []
    for intent in plan.get("intents", []):
        env = outputs.get(intent["id"])
        if (
            env
            and getattr(env, "status", None) == "NEEDS_CONFIRMATION"
            and getattr(env, "confirmation", None)
            and env.confirmation.action_id
        ):
            steps.append((intent, env))

    if not steps:
        # Check if there are only questions (NEEDS_INPUT)
        return None

    if len(steps) > settings.bundle_max_steps:
        steps = steps[: settings.bundle_max_steps]

    action_ids = []
    for _, e in steps:
        try:
            action_ids.append(uuid.UUID(str(e.confirmation.action_id)))
        except (ValueError, TypeError):
            continue

    if not action_ids:
        return None

    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, type, summary, status, expires_at
            FROM pending_actions
            WHERE id = ANY(:aids)
            """
        ),
        {"aids": action_ids},
    )
    actions = {r["id"]: r for r in res.mappings().all()}

    # Verify ownership, state and expiry
    verified_steps = []
    for intent, env in steps:
        aid = uuid.UUID(str(env.confirmation.action_id))
        a = actions.get(aid)
        if a and str(a["user_id"]) == ctx.session.user_id and a["status"] == "PENDING":
            verified_steps.append((intent, env))

    if not verified_steps:
        return None

    steps = verified_steps

    # If exactly 1 write step, return plain action card (no bundle row created)
    if len(steps) == 1:
        a = actions[uuid.UUID(str(steps[0][1].confirmation.action_id))]
        exp = a["expires_at"].isoformat() if hasattr(a["expires_at"], "isoformat") else str(a["expires_at"])
        return {
            "action_id": str(a["id"]),
            "summary": a["summary"],
            "expires_at": exp,
        }

    # If >= 2 write steps, create action_bundles row
    step_no = {intent["id"]: i + 1 for i, (intent, _) in enumerate(steps)}
    bundle_id = uuid.uuid4()
    hl = headline(steps)

    earliest_exp = min(
        actions[uuid.UUID(str(e.confirmation.action_id))]["expires_at"] for _, e in steps
    )
    run_id = getattr(ctx, "run_id", None)

    await db.execute(
        text(
            """
            INSERT INTO action_bundles (id, user_id, run_id, status, summary, expires_at, created_at)
            VALUES (:bid, :uid, :rid, 'PENDING', :summary, :exp, NOW())
            """
        ),
        {
            "bid": bundle_id,
            "uid": uuid.UUID(ctx.session.user_id),
            "rid": run_id,
            "summary": hl,
            "exp": earliest_exp,
        },
    )

    cards = []
    for intent, env in steps:
        aid = uuid.UUID(str(env.confirmation.action_id))
        a = actions[aid]
        deps = sorted(step_no[d] for d in intent.get("depends_on", []) if d in step_no)
        await db.execute(
            text(
                """
                UPDATE pending_actions
                SET bundle_id = :bid, step_no = :sno, depends_on = :deps
                WHERE id = :aid
                """
            ),
            {
                "bid": bundle_id,
                "sno": step_no[intent["id"]],
                "deps": deps,
                "aid": aid,
            },
        )
        card = {
            "step_no": step_no[intent["id"]],
            "type": a["type"],
            "summary": a["summary"],
            "depends_on": deps,
        }
        if deps:
            card["conditional_note"] = f"Goes ahead once step {deps[0]} succeeds"
        cards.append(card)

    await db.commit()

    questions = [
        {"agent": i.get("agent"), "text": e.user_message}
        for i in plan.get("intents", [])
        if (e := outputs.get(i["id"])) and getattr(e, "status", None) == "NEEDS_INPUT"
    ]

    exp_str = earliest_exp.isoformat() if hasattr(earliest_exp, "isoformat") else str(earliest_exp)
    return {
        "bundle_id": str(bundle_id),
        "headline": hl,
        "expires_at": exp_str,
        "steps": cards,
        "questions": questions,
    }
