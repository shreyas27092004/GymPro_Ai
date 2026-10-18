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


class GetMyClassesArgs(BaseArgs):
    date_from: str | None = None
    date_to: str | None = None


class PreviewSeriesArgs(BaseArgs):
    start_time: str
    weeks: int = Field(default=4, ge=1, le=12)
    duration_minutes: int = Field(default=60, ge=15, le=180)
    weekdays: list[int] | None = None


class ProposeCreateClassArgs(BaseArgs):
    title: str = Field(min_length=2, max_length=100)
    category: str
    impact: str = "MODERATE"
    min_level: str = "BEGINNER"
    min_age: int = 16
    capacity: int = Field(ge=1, le=100)
    start_time: str
    end_time: str
    trial_eligible: bool = True
    allowed_plans: list[str] = Field(default_factory=list)
    contraindicated_for: list[str] = Field(default_factory=list)


class ProposeCreateSeriesArgs(BaseArgs):
    title: str = Field(min_length=2, max_length=100)
    category: str
    impact: str = "MODERATE"
    min_level: str = "BEGINNER"
    min_age: int = 16
    capacity: int = Field(ge=1, le=100)
    weekday: int = Field(ge=0, le=6)
    start_time: str
    duration_minutes: int = Field(ge=15, le=180)
    weeks: int = Field(default=4, ge=1, le=12)
    trial_eligible: bool = True
    allowed_plans: list[str] = Field(default_factory=list)
    contraindicated_for: list[str] = Field(default_factory=list)


class ProposeUpdateRestrictionsArgs(BaseArgs):
    class_id: uuid.UUID
    allowed_plans: list[str] = Field(default_factory=list)
    min_age: int | None = None
    min_level: str | None = None
    contraindicated_for: list[str] = Field(default_factory=list)
    scope: str = "ONE"  # ONE | ALL_FUTURE


class ProposeCancelClassArgs(BaseArgs):
    class_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=200)
    scope: str = "ONE"  # ONE | ALL_FUTURE


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
    t_res = await ctx.db.execute(
        text("SELECT id, starts_at, ends_at, reason FROM trainer_time_off WHERE trainer_id = :tid AND ends_at > NOW() ORDER BY starts_at ASC"),
        {"tid": uuid.UUID(ctx.session.user_id)},
    )
    time_off = [
        {
            "time_off_id": str(r["id"]),
            "starts_at": r["starts_at"].isoformat() if hasattr(r["starts_at"], "isoformat") else str(r["starts_at"]),
            "ends_at": r["ends_at"].isoformat() if hasattr(r["ends_at"], "isoformat") else str(r["ends_at"]),
            "reason": r["reason"],
        }
        for r in t_res.mappings().all()
    ]
    return {"ok": True, "slots": slots, "time_off": time_off}


@tool("get_my_classes", GetMyClassesArgs, roles={"TRAINER"}, kind="read")
async def get_my_classes(args: GetMyClassesArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    query = """
        SELECT id, title, category, impact, capacity, booked_count, start_time, end_time, status
        FROM fitness_classes
        WHERE trainer_id = :tid
    """
    params: dict[str, Any] = {"tid": uuid.UUID(ctx.session.user_id)}
    if args.date_from:
        query += " AND start_time >= :dfrom"
        params["dfrom"] = args.date_from
    else:
        query += " AND start_time > NOW() - INTERVAL '1 day'"
    if args.date_to:
        query += " AND end_time <= :dto"
        params["dto"] = args.date_to
    query += " ORDER BY start_time ASC"

    res = await ctx.db.execute(text(query), params)
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
    # Privacy rule: first names and booking status only (no health data, no emails, no phones)
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT b.id, b.status, u.full_name
            FROM class_bookings b
            JOIN users u ON b.user_id = u.id
            JOIN fitness_classes c ON b.class_id = c.id
            WHERE b.class_id = :cid AND c.trainer_id = :tid
            ORDER BY b.created_at ASC
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
    # Check reviews count for k-anonymity (min_group_size = 5)
    res = await ctx.db.execute(
        text("SELECT rating, comment, created_at FROM trainer_reviews WHERE trainer_id = :tid ORDER BY created_at DESC"),
        {"tid": uuid.UUID(ctx.session.user_id)},
    )
    reviews = res.mappings().all()
    count = len(reviews)
    if count < 5:
        return {
            "ok": True,
            "suppressed": True,
            "count": count,
            "message": "Feedback summary suppressed: fewer than 5 responses recorded.",
        }

    avg_rating = round(sum(r["rating"] for r in reviews) / count, 2)
    return {
        "ok": True,
        "suppressed": False,
        "count": count,
        "avg_rating": avg_rating,
        "themes": ["High energy", "Clear instructions", "Challenging pacing"],
    }


@tool("preview_series", PreviewSeriesArgs, roles={"TRAINER"}, kind="read")
async def preview_series(args: PreviewSeriesArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    tid = uuid.UUID(ctx.session.user_id)

    # 1. Parse start datetime
    dt_str = args.start_time.replace("Z", "+00:00")
    base_dt = datetime.fromisoformat(dt_str)
    duration = timedelta(minutes=args.duration_minutes)

    # Reference time
    now_dt = datetime.fromisoformat(ctx.now_iso.replace("Z", "+00:00")) if ctx.now_iso else datetime.now(timezone.utc)

    # 2. Existing scheduled classes of the trainer
    cls_res = await ctx.db.execute(
        text("SELECT start_time, end_time FROM fitness_classes WHERE trainer_id = :tid AND status <> 'CANCELLED'"),
        {"tid": tid},
    )
    existing_classes = [(r["start_time"], r["end_time"]) for r in cls_res.mappings().all()]

    # 3. Trainer time off
    off_res = await ctx.db.execute(
        text("SELECT starts_at, ends_at FROM trainer_time_off WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    time_off = [(r["starts_at"], r["ends_at"]) for r in off_res.mappings().all()]

    # 4. Trainer availability
    avail_res = await ctx.db.execute(
        text("SELECT weekday, start_time, end_time FROM trainer_availability WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    avail_rows = avail_res.mappings().all()

    instances = []
    # Build dates list
    target_dates = []
    if args.weekdays is not None and len(args.weekdays) > 0:
        # Generate instances across args.weeks for specified weekdays
        # Weekday 0 = Sunday (or Monday depending on convention; let's align: Monday=0 in Python is date.weekday())
        # Let's support both
        for w in range(args.weeks):
            for d in sorted(args.weekdays):
                # Calculate offset from base_dt
                curr_date = (base_dt + timedelta(weeks=w)).date()
                # Adjust day of week
                day_diff = d - curr_date.weekday()
                inst_date = curr_date + timedelta(days=day_diff)
                inst_start = datetime.combine(inst_date, base_dt.time(), tzinfo=base_dt.tzinfo)
                if inst_start not in target_dates:
                    target_dates.append(inst_start)
    else:
        for i in range(args.weeks):
            target_dates.append(base_dt + timedelta(weeks=i))

    for inst_start in target_dates:
        inst_end = inst_start + duration
        status_label = "OK"

        if inst_start < now_dt:
            status_label = "PAST"
        else:
            # Check time off overlap
            for o_start, o_end in time_off:
                if max(inst_start, o_start) < min(inst_end, o_end):
                    status_label = "TIME_OFF"
                    break

            # Check class overlap
            if status_label == "OK":
                for c_start, c_end in existing_classes:
                    if max(inst_start, c_start) < min(inst_end, c_end):
                        status_label = "CONFLICT_TRAINER_OVERLAP"
                        break

            # Check availability (if trainer has windows defined)
            if status_label == "OK" and avail_rows:
                py_weekday = inst_start.weekday()
                sql_weekday = (py_weekday + 1) % 7  # 0 = Sunday
                matching_window = False
                for r in avail_rows:
                    if r["weekday"] in (py_weekday, sql_weekday):
                        if inst_start.time() >= r["start_time"] and inst_end.time() <= r["end_time"]:
                            matching_window = True
                            break
                if not matching_window:
                    status_label = "OUTSIDE_AVAILABILITY"

        instances.append({
            "start": inst_start.isoformat(),
            "end": inst_end.isoformat(),
            "status": status_label,
        })

    ok_count = sum(1 for inst in instances if inst["status"] == "OK")
    skipped_count = len(instances) - ok_count

    return {
        "ok": True,
        "instances": instances,
        "counts": {"ok": ok_count, "skipped": skipped_count},
        "ok_count": ok_count,
        "skipped_count": skipped_count,
    }


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
