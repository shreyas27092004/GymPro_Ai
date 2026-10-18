# app/tools/trainer_ops.py
from datetime import datetime, timezone, timedelta
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class GetClassRosterArgs(BaseArgs):
    class_id: uuid.UUID


class PreviewSeriesArgs(BaseArgs):
    start_time: str
    weeks: int = Field(default=4, ge=1, le=12)


class ProposeCreateClassArgs(BaseArgs):
    title: str = Field(min_length=2, max_length=100)
    category: str
    impact: str = "MODERATE"
    min_level: str = "BEGINNER"
    capacity: int = Field(ge=1, le=100)
    start_time: str
    end_time: str
    trial_eligible: bool = True
    allowed_plans: list[str] = Field(default_factory=list)


class ProposeCreateSeriesArgs(BaseArgs):
    title: str = Field(min_length=2, max_length=100)
    category: str
    impact: str = "MODERATE"
    min_level: str = "BEGINNER"
    capacity: int = Field(ge=1, le=100)
    weekday: int = Field(ge=0, le=6)
    start_time: str
    duration_minutes: int = Field(ge=15, le=180)
    weeks: int = Field(default=4, ge=1, le=12)


class ProposeUpdateRestrictionsArgs(BaseArgs):
    class_id: uuid.UUID
    allowed_plans: list[str] = Field(default_factory=list)
    min_age: int | None = None
    min_level: str | None = None


class ProposeCancelClassArgs(BaseArgs):
    class_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=200)


class ProposeSetAvailabilityArgs(BaseArgs):
    weekday: int = Field(ge=0, le=6)
    start_time: str
    end_time: str


class ProposeSetTimeOffArgs(BaseArgs):
    starts_at: str
    ends_at: str
    reason: str | None = None


@tool("get_my_availability", EmptyArgs, roles={"TRAINER"}, kind="read")
async def get_my_availability(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT weekday, start_time, end_time FROM trainer_availability WHERE trainer_id = :tid ORDER BY weekday, start_time"),
        {"tid": uuid.UUID(ctx.session.user_id)},
    )
    slots = [
        {"weekday": r["weekday"], "start_time": str(r["start_time"]), "end_time": str(r["end_time"])}
        for r in res.mappings().all()
    ]
    return {"ok": True, "slots": slots}


@tool("get_my_classes", EmptyArgs, roles={"TRAINER"}, kind="read")
async def get_my_classes(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT id, title, category, impact, capacity, booked_count, start_time, end_time, status
            FROM fitness_classes
            WHERE trainer_id = :tid AND start_time > NOW() - INTERVAL '1 day'
            ORDER BY start_time ASC
            """
        ),
        {"tid": uuid.UUID(ctx.session.user_id)},
    )
    classes = [
        {
            "class_id": str(r["id"]),
            "title": r["title"],
            "category": r["category"],
            "capacity": r["capacity"],
            "booked_count": r["booked_count"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            "end_time": r["end_time"].isoformat() if hasattr(r["end_time"], "isoformat") else str(r["end_time"]),
            "status": r["status"],
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "classes": classes}


@tool("get_class_roster", GetClassRosterArgs, roles={"TRAINER"}, kind="read")
async def get_class_roster(args: GetClassRosterArgs, ctx: RunContext) -> dict[str, Any]:
    # Privacy rule: first names only
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT b.id, b.status, u.full_name
            FROM class_bookings b
            JOIN users u ON b.user_id = u.id
            JOIN fitness_classes c ON b.class_id = c.id
            WHERE b.class_id = :cid AND c.trainer_id = :tid
            """
        ),
        {"cid": args.class_id, "tid": uuid.UUID(ctx.session.user_id)},
    )
    roster = [
        {
            "booking_id": str(r["id"]),
            "status": r["status"],
            "first_name": (r["full_name"] or "").split()[0],
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(roster), "roster": roster}


@tool("get_feedback_summary", EmptyArgs, roles={"TRAINER"}, kind="read")
async def get_feedback_summary(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT rating, reason, created_at FROM feedback WHERE item_type = 'TRAINER' AND item_id = :tid ORDER BY created_at DESC LIMIT 20"),
        {"tid": uuid.UUID(ctx.session.user_id)},
    )
    feedback_list = [
        {"rating": r["rating"], "reason": r["reason"], "date": str(r["created_at"].date())}
        for r in res.mappings().all()
    ]
    return {"ok": True, "feedback": feedback_list}


@tool("preview_series", PreviewSeriesArgs, roles={"TRAINER"}, kind="read")
async def preview_series(args: PreviewSeriesArgs, ctx: RunContext) -> dict[str, Any]:
    dt = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
    dates = [(dt + timedelta(weeks=i)).isoformat() for i in range(args.weeks)]
    return {"ok": True, "weeks": args.weeks, "preview_dates": dates}


@tool("propose_create_class", ProposeCreateClassArgs, roles={"TRAINER"}, kind="propose")
async def propose_create_class(args: ProposeCreateClassArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Create class '{args.title}' ({args.category})"
    payload = {
        "title": args.title,
        "category": args.category.upper(),
        "impact": args.impact.upper(),
        "min_level": args.min_level.upper(),
        "capacity": args.capacity,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "trial_eligible": args.trial_eligible,
        "allowed_plans": args.allowed_plans,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CREATE_CLASS', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "CREATE_CLASS"}


@tool("propose_create_series", ProposeCreateSeriesArgs, roles={"TRAINER"}, kind="propose")
async def propose_create_series(args: ProposeCreateSeriesArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Create recurring class series '{args.title}' ({args.weeks} weeks)"
    payload = {
        "title": args.title,
        "category": args.category.upper(),
        "impact": args.impact.upper(),
        "min_level": args.min_level.upper(),
        "capacity": args.capacity,
        "weekday": args.weekday,
        "start_time": args.start_time,
        "duration_minutes": args.duration_minutes,
        "weeks": args.weeks,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CREATE_CLASS_SERIES', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "CREATE_CLASS_SERIES"}


@tool("propose_update_restrictions", ProposeUpdateRestrictionsArgs, roles={"TRAINER"}, kind="propose")
async def propose_update_restrictions(args: ProposeUpdateRestrictionsArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Update class restrictions for class {str(args.class_id)[:8]}"
    payload = {
        "class_id": str(args.class_id),
        "allowed_plans": args.allowed_plans,
        "min_age": args.min_age,
        "min_level": args.min_level,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'UPDATE_CLASS_RESTRICTIONS', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "UPDATE_CLASS_RESTRICTIONS"}


@tool("propose_cancel_class", ProposeCancelClassArgs, roles={"TRAINER"}, kind="propose")
async def propose_cancel_class(args: ProposeCancelClassArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Cancel class {str(args.class_id)[:8]}: {args.reason[:40]}"
    payload = {"class_id": str(args.class_id), "reason": args.reason}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CANCEL_CLASS', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "CANCEL_CLASS"}


@tool("propose_set_availability", ProposeSetAvailabilityArgs, roles={"TRAINER"}, kind="propose")
async def propose_set_availability(args: ProposeSetAvailabilityArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Set weekly availability on weekday {args.weekday} ({args.start_time} - {args.end_time})"
    payload = {"weekday": args.weekday, "start_time": args.start_time, "end_time": args.end_time}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'SET_AVAILABILITY', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "SET_AVAILABILITY"}


@tool("propose_set_time_off", ProposeSetTimeOffArgs, roles={"TRAINER"}, kind="propose")
async def propose_set_time_off(args: ProposeSetTimeOffArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Set trainer time off from {args.starts_at} to {args.ends_at}"
    payload = {"starts_at": args.starts_at, "ends_at": args.ends_at, "reason": args.reason}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'SET_TIME_OFF', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "SET_TIME_OFF"}
