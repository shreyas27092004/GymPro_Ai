# app/tools/fitness.py
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .calculators import calc_progression as calc_prog
from .registry import RunContext, tool


class SearchExerciseKbArgs(BaseArgs):
    query: str = Field(min_length=1, max_length=100)
    category: str | None = None


class CalcProgressionArgs(BaseArgs):
    current_weight_kg: float = Field(gt=0)
    reps: int = Field(ge=1, le=50)
    rpe: float = Field(default=8.0, ge=1.0, le=10.0)
    goal: str = "HYPERTROPHY"


@tool("get_my_intake", EmptyArgs, roles={"USER"}, kind="read", needs_health_consent=True)
async def get_my_intake(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT date_of_birth, gender, height_cm, weight_kg, experience_level, goal,
                   goals_extra, known_injuries, injury_notes, allergies, dietary_preference,
                   meals_per_day
            FROM member_profiles
            WHERE user_id = :uid
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "PROFILE_NOT_FOUND"}

    return {
        "ok": True,
        "profile": {
            "date_of_birth": str(row["date_of_birth"]),
            "gender": row["gender"],
            "height_cm": float(row["height_cm"]),
            "weight_kg": float(row["weight_kg"]),
            "experience_level": row["experience_level"],
            "goal": row["goal"],
            "goals_extra": row["goals_extra"] or [],
            "known_injuries": row["known_injuries"] or [],
            "injury_notes": row["injury_notes"],
            "allergies": row["allergies"] or [],
            "dietary_preference": row["dietary_preference"],
            "meals_per_day": row["meals_per_day"],
        },
    }


@tool("search_exercise_kb", SearchExerciseKbArgs, roles={"USER"}, kind="read")
async def search_exercise_kb(args: SearchExerciseKbArgs, ctx: RunContext) -> dict[str, Any]:
    # Standard static knowledge base entries for exercises (untrusted text data)
    kb_entries = [
        {"title": "Barbell Squat", "category": "STRENGTH", "content": "Primary compound movement for quads and glutes. Keep torso upright and descend until hip crease is below knee."},
        {"title": "Deadlift", "category": "STRENGTH", "content": "Hinge movement targeting posterior chain and erectors. Maintain neutral spine and brace core."},
        {"title": "Bench Press", "category": "STRENGTH", "content": "Upper body push targeting pectorals and triceps. Retract scapulae and control bar to sternum."},
        {"title": "Knee-Safe Squat Alternative", "category": "RECOVERY", "content": "Box squats or Romanian deadlifts reduce knee shear while maintaining quad and hamstring engagement."},
        {"title": "HIIT Protocol", "category": "HIIT", "content": "30 seconds sprint / 30 seconds active recovery for 15-20 minutes."},
    ]
    matches = [
        e for e in kb_entries
        if args.query.lower() in e["title"].lower() or args.query.lower() in e["content"].lower()
    ]
    return {"ok": True, "results": matches[:5]}


@tool("get_class_catalog_summary", EmptyArgs, roles={"USER"}, kind="read")
async def get_class_catalog_summary(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT category, count(*) as count, min(start_time) as next_class FROM fitness_classes WHERE status = 'SCHEDULED' AND start_time > NOW() GROUP BY category")
    )
    categories = [
        {
            "category": r["category"],
            "upcoming_count": r["count"],
            "next_class": r["next_class"].isoformat() if hasattr(r["next_class"], "isoformat") else str(r["next_class"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "catalog": categories}


@tool("calc_progression", CalcProgressionArgs, roles={"USER"}, kind="calc")
async def calc_progression(args: CalcProgressionArgs, ctx: RunContext) -> dict[str, Any]:
    res = calc_prog(
        current_weight_kg=args.current_weight_kg,
        reps=args.reps,
        rpe=args.rpe,
        goal=args.goal,
    )
    return {"ok": True, **res}
