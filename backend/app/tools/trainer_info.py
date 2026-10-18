# app/tools/trainer_info.py
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs
from .registry import RunContext, tool


class SearchTrainersArgs(BaseArgs):
    goal_tags: list[str] = Field(default_factory=list)
    certifications_any: list[str] = Field(default_factory=list)
    min_reviews: int | None = None
    accepting_clients: bool = True
    available_from: str | None = None
    available_to: str | None = None


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
            SELECT u.id, u.full_name, t.bio, t.specializations, t.certifications,
                   (t.certs_verified_at IS NOT NULL) AS certs_verified,
                   t.rating, t.review_count, t.hourly_rate, t.accepting_clients
            FROM users u
            JOIN trainer_profiles t ON u.id = t.trainer_id
            WHERE u.role = 'TRAINER' AND u.account_status = 'ACTIVE'
            """
        )
    )
    trainers = []
    for r in res.mappings().all():
        if args.accepting_clients and not r["accepting_clients"]:
            continue

        specs = r["specializations"] or []
        certs = r["certifications"] or []
        verified = bool(r["certs_verified"])

        if args.goal_tags:
            match = any(gt.lower() in [s.lower() for s in specs] for gt in args.goal_tags)
            if not match:
                continue

        if args.certifications_any:
            match_cert = any(c.lower() in [sc.lower() for sc in certs] for c in args.certifications_any)
            if not match_cert:
                continue

        if args.min_reviews is not None and r["review_count"] < args.min_reviews:
            continue

        trainers.append({
            "trainer_id": str(r["id"]),
            "name": r["full_name"],
            "bio": r["bio"],
            "specializations": specs,
            "verified_certifications": certs if verified else [],
            "certs_verified": verified,
            "rating": float(r["rating"]) if r["rating"] is not None else None,
            "review_count": r["review_count"],
            "is_new": r["review_count"] < 5,
            "hourly_rate": float(r["hourly_rate"]),
        })

    return {"ok": True, "match_count": len(trainers), "trainers": trainers[:3]}


@tool("get_trainer_profile", GetTrainerProfileArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_trainer_profile(args: GetTrainerProfileArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT u.id, u.full_name, t.bio, t.specializations, t.certifications,
                   (t.certs_verified_at IS NOT NULL) AS certs_verified,
                   t.rating, t.review_count, t.hourly_rate, t.accepting_clients
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

    verified = bool(row["certs_verified"])
    certs = row["certifications"] or []

    return {
        "ok": True,
        "trainer": {
            "trainer_id": str(row["id"]),
            "name": row["full_name"],
            "bio": row["bio"],
            "specializations": row["specializations"] or [],
            "verified_certifications": certs if verified else [],
            "certs_verified": verified,
            "rating": float(row["rating"]) if row["rating"] is not None else None,
            "review_count": row["review_count"],
            "is_new": row["review_count"] < 5,
            "hourly_rate": float(row["hourly_rate"]),
            "accepting_clients": row["accepting_clients"],
        },
    }


@tool("get_trainer_review_summary", GetTrainerReviewSummaryArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_trainer_review_summary(args: GetTrainerReviewSummaryArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT count(*) as total_feedback, avg(rating) as average_rating
            FROM trainer_reviews
            WHERE trainer_id = :tid
            """
        ),
        {"tid": args.trainer_id},
    )
    row = res.mappings().one_or_none()
    count = row["total_feedback"] if row else 0
    avg_rating = float(row["average_rating"]) if row and row["average_rating"] else None

    return {
        "ok": True,
        "trainer_id": str(args.trainer_id),
        "review_count": count,
        "rating_average": round(avg_rating, 2) if avg_rating is not None else None,
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
