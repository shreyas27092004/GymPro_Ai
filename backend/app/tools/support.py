# app/tools/support.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class GetSupportGuidanceArgs(BaseArgs):
    topic: str = Field(min_length=1, max_length=100)


class ProposeIssueReportArgs(BaseArgs):
    category: str  # CLASS_QUALITY | TRAINER_CONDUCT | FACILITY | SAFETY | HARASSMENT | INJURY | BILLING | OTHER
    user_words: str = Field(min_length=5, max_length=1000)
    neutral_summary: str = Field(min_length=5, max_length=300)
    class_id: uuid.UUID | None = None
    severity_hint: str | None = None


@tool("get_todays_classes_for_me", EmptyArgs, roles={"USER"}, kind="read")
async def get_todays_classes_for_me(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT b.id, b.status, c.id as class_id, c.title, c.category, c.start_time, c.end_time
            FROM class_bookings b
            JOIN fitness_classes c ON b.class_id = c.id
            WHERE b.user_id = :uid
              AND c.start_time >= CURRENT_DATE
              AND c.start_time < CURRENT_DATE + INTERVAL '1 day'
            ORDER BY c.start_time ASC
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    classes = [
        {
            "booking_id": str(r["id"]),
            "class_id": str(r["class_id"]),
            "title": r["title"],
            "category": r["category"],
            "status": r["status"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            "end_time": r["end_time"].isoformat() if hasattr(r["end_time"], "isoformat") else str(r["end_time"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(classes), "classes": classes}


@tool("get_support_guidance", GetSupportGuidanceArgs, roles={"USER"}, kind="read")
async def get_support_guidance(args: GetSupportGuidanceArgs, ctx: RunContext) -> dict[str, Any]:
    from ..kb.retrieval import query_kb
    hits = query_kb("gym_policies", args.topic, top_k=1)
    if hits:
        return {"ok": True, "topic": args.topic, "guidance": hits[0]["content"], "citation": hits[0]["citation"]}

    top = args.topic.lower()
    guidance = {
        "cancellation": "Classes may be cancelled up to 2 hours prior to start time without penalty. Late cancellations do not refund credits.",
        "trial": "Trial passes grant 3 free classes within 14 days of verification. Once expired or consumed, choose a Silver, Gold, or Platinum plan.",
        "upgrade": "Upgrades take effect immediately upon confirmation and payment. Unused days from your existing membership are prorated automatically.",
        "downgrade": "Membership downgrades take effect at the end of the current billing cycle and are managed through our front desk staff.",
        "refund": "Refund requests are processed in accordance with gym policy by our administrative staff.",
    }
    for k, v in guidance.items():
        if k in top:
            return {"ok": True, "topic": k, "guidance": v}

    return {
        "ok": True,
        "topic": args.topic,
        "guidance": "For specific assistance, you may submit a member report or speak with a front desk staff member.",
    }


@tool("propose_issue_report", ProposeIssueReportArgs, roles={"USER"}, kind="propose")
async def propose_issue_report(args: ProposeIssueReportArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    cat = args.category.upper()
    summary = f"Submit {cat} report: {args.neutral_summary[:60]}"
    payload = {
        "category": cat,
        "user_words": args.user_words,
        "neutral_summary": args.neutral_summary,
        "class_id": str(args.class_id) if args.class_id else None,
        "severity_hint": args.severity_hint.upper() if args.severity_hint else None,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'SUBMIT_ISSUE_REPORT', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
            """
        ),
        {
            "aid": action_id,
            "uid": uuid.UUID(ctx.session.user_id),
            "payload": json.dumps(payload),
            "summary": summary,
        },
    )
    await ctx.db.commit()

    return {
        "ok": True,
        "action_id": str(action_id),
        "summary": summary,
        "type": "SUBMIT_ISSUE_REPORT",
    }
