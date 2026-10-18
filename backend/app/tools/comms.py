# app/tools/comms.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from ..messaging.renderer import TEMPLATES
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class GetTemplateArgs(BaseArgs):
    template_id: str


class GetBookingForEmailArgs(BaseArgs):
    booking_id: uuid.UUID


class ProposeSendEmailArgs(BaseArgs):
    # Notice: STRICTLY NO recipient, to, or email argument!
    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    attach_calendar: bool = False
    requires_step: int | None = None


@tool("list_templates", EmptyArgs, roles={"USER", "SYSTEM", "ADMIN"}, kind="read")
async def list_templates(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    return {"ok": True, "templates": list(TEMPLATES.keys())}


@tool("get_template", GetTemplateArgs, roles={"USER", "SYSTEM", "ADMIN"}, kind="read")
async def get_template(args: GetTemplateArgs, ctx: RunContext) -> dict[str, Any]:
    tid = args.template_id.upper()
    if tid not in TEMPLATES:
        return {"ok": False, "error": "TEMPLATE_NOT_FOUND"}
    t = TEMPLATES[tid]
    return {
        "ok": True,
        "template_id": tid,
        "subject": t["subject"],
        "is_marketing": t["is_marketing"],
    }


@tool("get_booking_for_email", GetBookingForEmailArgs, roles={"USER", "SYSTEM", "ADMIN"}, kind="read")
async def get_booking_for_email(args: GetBookingForEmailArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT b.id, b.status, c.title, c.start_time, c.end_time, u.full_name as trainer_name
            FROM class_bookings b
            JOIN fitness_classes c ON b.class_id = c.id
            JOIN users u ON c.trainer_id = u.id
            WHERE b.id = :bid
            """
        ),
        {"bid": args.booking_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "BOOKING_NOT_FOUND"}

    return {
        "ok": True,
        "booking": {
            "booking_id": str(row["id"]),
            "status": row["status"],
            "title": row["title"],
            "trainer_name": row["trainer_name"],
            "start_time": row["start_time"].isoformat() if hasattr(row["start_time"], "isoformat") else str(row["start_time"]),
            "end_time": row["end_time"].isoformat() if hasattr(row["end_time"], "isoformat") else str(row["end_time"]),
        },
    }


@tool("get_weekly_summary_numbers", EmptyArgs, roles={"USER", "SYSTEM"}, kind="read")
async def get_weekly_summary_numbers(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT count(*) as classes_attended
            FROM class_bookings
            WHERE user_id = :uid AND status IN ('CONFIRMED', 'ATTENDED')
              AND created_at >= NOW() - INTERVAL '7 days'
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    attended = res.scalar_one() or 0
    return {
        "ok": True,
        "weekly_numbers": {
            "classes_attended": attended,
            "period": "Last 7 days",
        },
    }


@tool("get_notification_prefs", EmptyArgs, roles={"USER", "SYSTEM"}, kind="read")
async def get_notification_prefs(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT channels, quiet_start, quiet_end, marketing_opt_in FROM notification_prefs WHERE user_id = :uid"),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {
            "ok": True,
            "channels": ["IN_APP", "EMAIL"],
            "marketing_opt_in": False,
        }
    return {
        "ok": True,
        "channels": row["channels"] or ["IN_APP", "EMAIL"],
        "quiet_start": str(row["quiet_start"]) if row["quiet_start"] else None,
        "quiet_end": str(row["quiet_end"]) if row["quiet_end"] else None,
        "marketing_opt_in": row["marketing_opt_in"],
    }


@tool("propose_send_email", ProposeSendEmailArgs, roles={"USER"}, kind="propose")
async def propose_send_email(args: ProposeSendEmailArgs, ctx: RunContext) -> dict[str, Any]:
    # Recipient is NEVER passed in arguments; injected from authenticated session
    action_id = uuid.uuid4()
    tid = args.template_id.upper()
    summary = f"Send confirmation email ({tid}) to account address"
    payload = {
        "template_id": tid,
        "params": args.params,
        "attach_calendar": args.attach_calendar,
        "requires_step": args.requires_step,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'SEND_BOOKING_EMAIL', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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
        "type": "SEND_BOOKING_EMAIL",
    }
