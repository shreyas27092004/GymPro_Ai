# app/tools/schedule.py
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from ..entitlements.resolver import entitlements as resolve_entitlements
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class SearchClassesArgs(BaseArgs):
    category: str | None = None
    impact: str | None = None
    min_level: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    trainer_id: uuid.UUID | None = None
    trial_only: bool = False


class MatchClassNameArgs(BaseArgs):
    query: str = Field(min_length=1, max_length=100)


class GetMyBookingsArgs(BaseArgs):
    status: str | None = None


class CheckConflictsArgs(BaseArgs):
    class_id: uuid.UUID


class CheckClassRulesArgs(BaseArgs):
    class_id: uuid.UUID


class GetEntitlementsArgs(BaseArgs):
    class_id: uuid.UUID | None = None
    use_projected: bool = False


class ProposeBookingArgs(BaseArgs):
    class_id: uuid.UUID


class ProposeCancellationArgs(BaseArgs):
    booking_id: uuid.UUID


class ProposeWaitlistArgs(BaseArgs):
    class_id: uuid.UUID


@tool("search_classes", SearchClassesArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def search_classes(args: SearchClassesArgs, ctx: RunContext) -> dict[str, Any]:
    query_parts = ["SELECT id, title, trainer_id, category, impact, min_level, trial_eligible, capacity, booked_count, start_time, end_time, status, allowed_plans FROM fitness_classes WHERE status = 'SCHEDULED' AND start_time > NOW()"]
    params: dict[str, Any] = {}

    if args.category:
        query_parts.append("AND category = :cat")
        params["cat"] = args.category.upper()
    if args.impact:
        query_parts.append("AND impact = :imp")
        params["imp"] = args.impact.upper()
    if args.min_level:
        query_parts.append("AND min_level = :lvl")
        params["lvl"] = args.min_level.upper()
    if args.trial_only:
        query_parts.append("AND trial_eligible = true")
    if args.trainer_id:
        query_parts.append("AND trainer_id = :tid")
        params["tid"] = args.trainer_id

    query_parts.append("ORDER BY start_time ASC LIMIT 50")
    sql = " ".join(query_parts)

    await set_rls_system(ctx.db)
    res = await ctx.db.execute(text(sql), params)
    classes = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "category": r["category"],
            "impact": r["impact"],
            "min_level": r["min_level"],
            "trial_eligible": r["trial_eligible"],
            "capacity": r["capacity"],
            "booked_count": r["booked_count"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            "end_time": r["end_time"].isoformat() if hasattr(r["end_time"], "isoformat") else str(r["end_time"]),
            "allowed_plans": r["allowed_plans"] or [],
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(classes), "classes": classes}


@tool("match_class_name", MatchClassNameArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def match_class_name(args: MatchClassNameArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT id, title, category, start_time
            FROM fitness_classes
            WHERE status = 'SCHEDULED' AND start_time > NOW()
              AND title ILIKE :q
            ORDER BY start_time ASC
            LIMIT 10
            """
        ),
        {"q": f"%{args.query}%"},
    )
    matches = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "category": r["category"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "matches": matches}


@tool("get_my_bookings", GetMyBookingsArgs, roles={"USER"}, kind="read")
async def get_my_bookings(args: GetMyBookingsArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    sql = """
        SELECT b.id, b.class_id, b.status, b.created_at, c.title, c.category, c.start_time, c.end_time
        FROM class_bookings b
        JOIN fitness_classes c ON b.class_id = c.id
        WHERE b.user_id = :uid
    """
    params: dict[str, Any] = {"uid": uuid.UUID(ctx.session.user_id)}
    if args.status:
        sql += " AND b.status = :st"
        params["st"] = args.status.upper()
    sql += " ORDER BY c.start_time DESC LIMIT 50"

    res = await ctx.db.execute(text(sql), params)
    bookings = [
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
    return {"ok": True, "bookings": bookings}


@tool("check_conflicts", CheckConflictsArgs, roles={"USER"}, kind="read")
async def check_conflicts(args: CheckConflictsArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    cls_res = await ctx.db.execute(
        text("SELECT start_time, end_time FROM fitness_classes WHERE id = :cid"),
        {"cid": args.class_id},
    )
    target = cls_res.mappings().one_or_none()
    if not target:
        return {"ok": False, "error": "CLASS_NOT_FOUND"}

    conf_res = await ctx.db.execute(
        text(
            """
            SELECT c.id, c.title, c.start_time, c.end_time
            FROM class_bookings b
            JOIN fitness_classes c ON b.class_id = c.id
            WHERE b.user_id = :uid
              AND b.status = 'CONFIRMED'
              AND c.status = 'SCHEDULED'
              AND tstzrange(c.start_time - INTERVAL '15 min', c.end_time + INTERVAL '15 min') &&
                  tstzrange(:st, :et)
            """
        ),
        {
            "uid": uuid.UUID(ctx.session.user_id),
            "st": target["start_time"],
            "et": target["end_time"],
        },
    )
    conflicts = [
        {
            "class_id": str(r["id"]),
            "title": r["title"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
        }
        for r in conf_res.mappings().all()
    ]
    return {"ok": True, "has_conflict": len(conflicts) > 0, "conflicts": conflicts}


@tool("check_class_rules", CheckClassRulesArgs, roles={"USER"}, kind="read")
async def check_class_rules(args: CheckClassRulesArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    cls_res = await ctx.db.execute(
        text("SELECT id, title, min_age, min_level, contraindicated_for FROM fitness_classes WHERE id = :cid"),
        {"cid": args.class_id},
    )
    cls = cls_res.mappings().one_or_none()
    if not cls:
        return {"ok": False, "error": "CLASS_NOT_FOUND"}

    failures = []
    # Age check
    if cls["min_age"] and ctx.session.age_years and ctx.session.age_years < cls["min_age"]:
        failures.append(f"MIN_AGE_REQUIRED_{cls['min_age']}")

    # Contraindication check
    contra = cls["contraindicated_for"] or []
    if contra and ctx.session.health_consent:
        p_res = await ctx.db.execute(
            text("SELECT known_injuries FROM member_profiles WHERE user_id = :uid"),
            {"uid": uuid.UUID(ctx.session.user_id)},
        )
        p_row = p_res.mappings().one_or_none()
        injuries = set(p_row["known_injuries"]) if p_row and p_row["known_injuries"] else set()
        overlap = injuries.intersection(set(contra))
        if overlap:
            failures.append(f"CONTRAINDICATED_FOR_{','.join(overlap)}")

    return {"ok": len(failures) == 0, "failures": failures}


@tool("get_membership_entitlements", GetEntitlementsArgs, roles={"USER"}, kind="read")
async def get_membership_entitlements(args: GetEntitlementsArgs, ctx: RunContext) -> dict[str, Any]:
    projected = ctx.handoff_projected_plan() if args.use_projected else None
    cls_dict = None
    if args.class_id:
        await set_rls_system(ctx.db)
        c_res = await ctx.db.execute(
            text("SELECT id, allowed_plans, trial_eligible FROM fitness_classes WHERE id = :cid"),
            {"cid": args.class_id},
        )
        row = c_res.mappings().one_or_none()
        if row:
            cls_dict = dict(row)

    ent = await resolve_entitlements(ctx.db, uuid.UUID(ctx.session.user_id), cls_dict, projected_plan=projected)
    return {
        "ok": True,
        "can_book": ent.can_book,
        "reason": ent.reason,
        "source": ent.source,
        "remaining": ent.remaining,
        "trial_grant_id": ent.trial_grant_id,
    }


@tool("propose_booking", ProposeBookingArgs, roles={"USER"}, kind="propose")
async def propose_booking(args: ProposeBookingArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    cls_res = await ctx.db.execute(
        text("SELECT id, title, start_time, booked_count, capacity, status FROM fitness_classes WHERE id = :cid"),
        {"cid": args.class_id},
    )
    cls = cls_res.mappings().one_or_none()
    if not cls or cls["status"] != "SCHEDULED" or cls["start_time"] <= datetime.now(timezone.utc):
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}

    if cls["booked_count"] >= cls["capacity"]:
        return {"ok": False, "error": "CLASS_FULL", "hint": "offer_waitlist"}

    action_id = uuid.uuid4()
    summary = f"Book {cls['title']} on {cls['start_time'].strftime('%Y-%m-%d %H:%M')}"
    payload = {"class_id": str(args.class_id)}

    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'BOOK_CLASS', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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
        "type": "BOOK_CLASS",
    }


@tool("propose_cancellation", ProposeCancellationArgs, roles={"USER"}, kind="propose")
async def propose_cancellation(args: ProposeCancellationArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    b_res = await ctx.db.execute(
        text(
            """
            SELECT b.id, b.class_id, c.title, c.start_time
            FROM class_bookings b
            JOIN fitness_classes c ON b.class_id = c.id
            WHERE b.id = :bid AND b.user_id = :uid AND b.status = 'CONFIRMED'
            """
        ),
        {"bid": args.booking_id, "uid": uuid.UUID(ctx.session.user_id)},
    )
    booking = b_res.mappings().one_or_none()
    if not booking:
        return {"ok": False, "error": "BOOKING_NOT_FOUND"}

    action_id = uuid.uuid4()
    summary = f"Cancel booking for {booking['title']}"
    payload = {"booking_id": str(args.booking_id)}

    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CANCEL_BOOKING', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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
        "type": "CANCEL_BOOKING",
    }


@tool("propose_waitlist", ProposeWaitlistArgs, roles={"USER"}, kind="propose")
async def propose_waitlist(args: ProposeWaitlistArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    cls_res = await ctx.db.execute(
        text("SELECT id, title FROM fitness_classes WHERE id = :cid AND status = 'SCHEDULED'"),
        {"cid": args.class_id},
    )
    cls = cls_res.mappings().one_or_none()
    if not cls:
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}

    action_id = uuid.uuid4()
    summary = f"Join waitlist for {cls['title']}"
    payload = {"class_id": str(args.class_id)}

    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'JOIN_WAITLIST', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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
        "type": "JOIN_WAITLIST",
    }
