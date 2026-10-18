# app/tools/wellness.py
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .calculators import (
    calc_bmi as calc_bmi_fn,
    calc_energy as calc_energy_fn,
    calc_hydration as calc_hydration_fn,
)
from .registry import RunContext, tool


class CalcEnergyArgs(BaseArgs):
    bmr: float = Field(gt=0)
    activity_level: str = "SEDENTARY"


class CalcBmiArgs(BaseArgs):
    weight_kg: float = Field(gt=0)
    height_cm: float = Field(gt=0)


class CalcHydrationArgs(BaseArgs):
    weight_kg: float = Field(gt=0)
    minutes_exercise: int = Field(default=0, ge=0)


class GetInjuryProtocolArgs(BaseArgs):
    injury_code: str = Field(min_length=1, max_length=50)


@tool("get_my_health_profile", EmptyArgs, roles={"USER"}, kind="read", needs_health_consent=True)
async def get_my_health_profile(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT date_of_birth, gender, height_cm, weight_kg, known_injuries, injury_notes, allergies
            FROM member_profiles
            WHERE user_id = :uid
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "HEALTH_PROFILE_NOT_FOUND"}

    return {
        "ok": True,
        "health_profile": {
            "date_of_birth": str(row["date_of_birth"]),
            "gender": row["gender"],
            "height_cm": float(row["height_cm"]),
            "weight_kg": float(row["weight_kg"]),
            "known_injuries": row["known_injuries"] or [],
            "injury_notes": row["injury_notes"],
            "allergies": row["allergies"] or [],
        },
    }


@tool("calc_energy", CalcEnergyArgs, roles={"USER"}, kind="calc")
async def calc_energy(args: CalcEnergyArgs, ctx: RunContext) -> dict[str, Any]:
    tdee = calc_energy_fn(args.bmr, args.activity_level)
    return {"ok": True, "tdee_calories": tdee}


@tool("calc_bmi", CalcBmiArgs, roles={"USER"}, kind="calc")
async def calc_bmi(args: CalcBmiArgs, ctx: RunContext) -> dict[str, Any]:
    try:
        res = calc_bmi_fn(args.weight_kg, args.height_cm)
        return {"ok": True, **res}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@tool("calc_hydration", CalcHydrationArgs, roles={"USER"}, kind="calc")
async def calc_hydration(args: CalcHydrationArgs, ctx: RunContext) -> dict[str, Any]:
    ml = calc_hydration_fn(args.weight_kg, args.minutes_exercise)
    return {"ok": True, "hydration_ml": ml, "liters": round(ml / 1000.0, 2)}


@tool("get_injury_protocol", GetInjuryProtocolArgs, roles={"USER"}, kind="read")
async def get_injury_protocol(args: GetInjuryProtocolArgs, ctx: RunContext) -> dict[str, Any]:
    code = args.injury_code.upper()
    protocols = {
        "KNEE": {
            "contraindicated": ["SPIN", "HIGH_IMPACT", "BOX_JUMPS"],
            "safe_alternatives": ["SWIMMING", "PILATES", "ISOMETRIC_QUAD_SETS"],
            "guidance": "Avoid deep knee flexion past 90 degrees under load. Emphasize hip abductor and glute strengthening.",
        },
        "LOWER_BACK": {
            "contraindicated": ["HEAVY_CONVENTIONAL_DEADLIFT", "SPINAL_FLEXION_UNDER_LOAD"],
            "safe_alternatives": ["BIRD_DOG", "CHAIR_SQUATS", "WALKING"],
            "guidance": "Maintain neutral pelvic tilt. Avoid rapid torsion movements.",
        },
        "SHOULDER": {
            "contraindicated": ["BEHIND_NECK_PRESS", "UPRIGHT_ROWS"],
            "safe_alternatives": ["NEUTRAL_GRIP_PRESS", "FACE_PULLS", "EXTERNAL_ROTATIONS"],
            "guidance": "Limit overhead press range if impingement occurs.",
        },
    }
    res = protocols.get(
        code,
        {
            "contraindicated": ["HIGH_IMPACT"],
            "safe_alternatives": ["LIGHT_MOBILITY", "WALKING"],
            "guidance": "Listen to your body, warm up thoroughly, and stop immediately if sharp pain occurs.",
        },
    )
    return {"ok": True, "injury_code": code, "protocol": res}


@tool("get_crisis_resources", EmptyArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_crisis_resources(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    return {
        "ok": True,
        "resources": [
            {"service": "KIRAN Mental Health Helpline", "phone": "1800-599-0019", "country": "IN", "available": "24/7"},
            {"service": "Tele-MANAS", "phone": "14416", "country": "IN", "available": "24/7"},
            {"service": "National Emergency Helpline", "phone": "112", "country": "IN", "available": "24/7"},
        ],
        "disclaimer": "GymPro AI coaches provide fitness and wellness coaching only, not medical treatment or emergency psychiatric support.",
    }
