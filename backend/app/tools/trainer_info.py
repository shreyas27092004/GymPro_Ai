# app/tools/trainer_info.py
from typing import Any
import uuid
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs
from .registry import RunContext, tool


class SearchTrainersArgs(BaseArgs):
    specialty: str | None = None


class GetTrainerProfileArgs(BaseArgs):
    trainer_id: uuid.UUID


class GetTrainerReviewSummaryArgs(BaseArgs):
    trainer_id: uuid.UUID


class GetTrainerAvailabilityArgs(BaseArgs):
    trainer_id: uuid.UUID


@tool("search_trainers", SearchTrainersArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def search_trainers(args: SearchTrainersArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT u.id, u.full_name, t.bio, t.specialties, t.credentials_verified
            FROM users u
            JOIN trainer_profiles t ON u.id = t.trainer_id
            WHERE u.role = 'TRAINER' AND u.account_status = 'ACTIVE'
            """
        )
    )
    trainers = []
    for r in res.mappings().all():
        specs = r["specialties"] or []
        if args.specialty and args.specialty.lower() not in [s.lower() for s in specs]:
            continue
        trainers.append({
            "trainer_id": str(r["id"]),
            "full_name": r["full_name"],
            "bio": r["bio"],
            "specialties": specs,
            "credentials_verified": r["credentials_verified"],
        })
    return {"ok": True, "count": len(trainers), "trainers": trainers}


@tool("get_trainer_profile", GetTrainerProfileArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_trainer_profile(args: GetTrainerProfileArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT u.id, u.full_name, t.bio, t.specialties, t.credentials_verified, t.rating_avg, t.rating_count
            FROM users u
            JOIN trainer_profiles t ON u.id = t.trainer_id
            WHERE u.id = :tid AND u.role = 'TRAINER'
            """
        ),
        {"tid": args.trainer_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "TRAINER_NOT_FOUND"}

    return {
        "ok": True,
        "trainer": {
            "trainer_id": str(row["id"]),
            "full_name": row["full_name"],
            "bio": row["bio"],
            "specialties": row["specialties"] or [],
            "credentials_verified": row["credentials_verified"],
            "rating_avg": float(row["rating_avg"]),
            "rating_count": row["rating_count"],
        },
    }


@tool("get_trainer_review_summary", GetTrainerReviewSummaryArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_trainer_review_summary(args: GetTrainerReviewSummaryArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT count(*) as total_feedback, avg(rating) as average_rating
            FROM feedback
            WHERE item_type = 'TRAINER' AND item_id = :tid
            """
        ),
        {"tid": args.trainer_id},
    )
    row = res.mappings().one_or_none()
    count = row["total_feedback"] if row else 0
    avg_rating = float(row["average_rating"]) if row and row["average_rating"] else 5.0

    return {
        "ok": True,
        "trainer_id": str(args.trainer_id),
        "review_count": count,
        "rating_average": round(avg_rating, 2),
    }


@tool("get_trainer_availability", GetTrainerAvailabilityArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_trainer_availability(args: GetTrainerAvailabilityArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT weekday, start_time, end_time
            FROM trainer_availability
            WHERE trainer_id = :tid
            ORDER BY weekday, start_time
            """
        ),
        {"tid": args.trainer_id},
    )
    slots = [
        {
            "weekday": r["weekday"],
            "start_time": str(r["start_time"]),
            "end_time": str(r["end_time"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "trainer_id": str(args.trainer_id), "slots": slots}
