# app/entitlements/intake.py
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
import uuid
from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls, set_rls_system


class IntakeUpdate(BaseModel):
    date_of_birth: date
    gender: Literal["FEMALE", "MALE", "NON_BINARY", "PREFER_NOT_TO_SAY", "UNSPECIFIED"] = "UNSPECIFIED"
    height_cm: Decimal = Field(..., ge=100, le=250)
    weight_kg: Decimal = Field(..., ge=25, le=350)
    experience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED", "ATHLETE"] = "BEGINNER"
    goal: Literal["FAT_LOSS", "MUSCLE_GAIN", "ENDURANCE", "FLEXIBILITY", "STRENGTH", "REHABILITATION", "MAINTENANCE"] = "MAINTENANCE"
    goals_extra: list[str] = Field(default_factory=list)
    known_injuries: list[str] = Field(default_factory=list)
    injury_notes: str | None = None
    allergies: list[str] = Field(default_factory=list)
    dietary_preference: str | None = None
    cuisine_prefs: list[str] = Field(default_factory=list)
    meals_per_day: int | None = Field(None, ge=1, le=8)
    typical_sleep_hours: Decimal | None = Field(None, ge=0, le=24)
    preferred_days: list[int] = Field(default_factory=list)
    preferred_windows: list[str] = Field(default_factory=list)
    is_pregnant: bool | None = None
    medical_clearance: bool = False
    activity_level: Literal["SEDENTARY", "LIGHT", "MODERATE", "VERY_ACTIVE"] = "LIGHT"
    daily_step_goal: int = 10000
    daily_calorie_burn_goal: int = 500
    sections_completed: list[str] = Field(default_factory=list)

    @field_validator("known_injuries")
    @classmethod
    def validate_injuries(cls, v: list[str]) -> list[str]:
        valid = {"KNEE", "LOWER_BACK", "SHOULDER", "ANKLE", "WRIST", "NECK", "OTHER"}
        cleaned = [i.strip().upper() for i in v]
        for item in cleaned:
            if item not in valid:
                raise ValueError(f"Invalid injury code: {item}. Allowed: {valid}")
        return cleaned

    @field_validator("allergies")
    @classmethod
    def validate_allergies(cls, v: list[str]) -> list[str]:
        valid = {"PEANUT", "TREE_NUT", "DAIRY", "EGG", "SOY", "GLUTEN", "FISH", "SHELLFISH", "OTHER"}
        cleaned = [a.strip().upper() for a in v]
        for item in cleaned:
            if item not in valid:
                raise ValueError(f"Invalid allergen code: {item}. Unknown allergens fail closed.")
        return cleaned


def calculate_age(dob: date, as_of: date | None = None) -> int:
    today = as_of or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def get_member_profile(db: AsyncSession, user_id: uuid.UUID | str) -> dict[str, Any] | None:
    uid = uuid.UUID(str(user_id))
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT user_id, date_of_birth, gender, height_cm, weight_kg, experience_level,
                   goal, goals_extra, known_injuries, injury_notes, allergies,
                   dietary_preference, cuisine_prefs, meals_per_day, typical_sleep_hours,
                   preferred_days, preferred_windows, is_pregnant, medical_clearance,
                   activity_level, daily_step_goal, daily_calorie_burn_goal,
                   sections_completed, health_data_consent_at, updated_at
            FROM member_profiles
            WHERE user_id = :uid
            """
        ),
        {"uid": uid},
    )
    row = res.mappings().one_or_none()
    return dict(row) if row else None


async def save_member_profile(
    db: AsyncSession,
    user_id: uuid.UUID | str,
    data: IntakeUpdate,
    as_of: date | None = None,
) -> dict[str, Any]:
    """
    Validates and upserts member intake profile.
    Enforces age checks: under-18 users are refused calorie-restricted (FAT_LOSS) goals.
    Enforces pregnancy checks: pregnant users are refused aggressive calorie-deficit targets.
    Database trigger automatically snapshots each change into member_intake_versions.
    """
    uid = uuid.UUID(str(user_id))
    age = calculate_age(data.date_of_birth, as_of)
    if age < 18 and data.goal == "FAT_LOSS":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "UNDERAGE_CALORIE_RESTRICTION",
                "message": "Calorie-restricted fat loss goals are not permitted for members under 18.",
            },
        )

    if data.is_pregnant and data.goal == "FAT_LOSS":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "PREGNANCY_GOAL_CONFLICT",
                "message": "Aggressive fat loss goals are contraindicated during pregnancy. Please choose MAINTENANCE or gentle mobility.",
            },
        )

    # Automatically derive sections completed if not explicitly populated
    sections = list(data.sections_completed)
    if "GOALS" not in sections:
        sections.append("GOALS")
    if "BODY" not in sections:
        sections.append("BODY")
    if data.allergies or data.dietary_preference:
        if "DIET" not in sections:
            sections.append("DIET")
    if data.known_injuries:
        if "INJURIES" not in sections:
            sections.append("INJURIES")
    if data.preferred_days or data.preferred_windows:
        if "SCHEDULE" not in sections:
            sections.append("SCHEDULE")

    # Set RLS context so snapshot_member_profile trigger populates changed_by
    await set_rls(db, user_id=str(uid), role="USER")

    await db.execute(
        text(
            """
            INSERT INTO member_profiles (
                user_id, date_of_birth, gender, height_cm, weight_kg, experience_level,
                goal, goals_extra, known_injuries, injury_notes, allergies,
                dietary_preference, cuisine_prefs, meals_per_day, typical_sleep_hours,
                preferred_days, preferred_windows, is_pregnant, medical_clearance,
                activity_level, daily_step_goal, daily_calorie_burn_goal,
                sections_completed, updated_at
            ) VALUES (
                :uid, :dob, :gender, :height, :weight, :exp,
                :goal, :g_extra, :injuries, :notes, :allergies,
                :diet, :cuisine, :meals, :sleep,
                :p_days, :p_windows, :preg, :med,
                :act, :steps, :burn,
                :sections, NOW()
            )
            ON CONFLICT (user_id) DO UPDATE SET
                date_of_birth = EXCLUDED.date_of_birth,
                gender = EXCLUDED.gender,
                height_cm = EXCLUDED.height_cm,
                weight_kg = EXCLUDED.weight_kg,
                experience_level = EXCLUDED.experience_level,
                goal = EXCLUDED.goal,
                goals_extra = EXCLUDED.goals_extra,
                known_injuries = EXCLUDED.known_injuries,
                injury_notes = EXCLUDED.injury_notes,
                allergies = EXCLUDED.allergies,
                dietary_preference = EXCLUDED.dietary_preference,
                cuisine_prefs = EXCLUDED.cuisine_prefs,
                meals_per_day = EXCLUDED.meals_per_day,
                typical_sleep_hours = EXCLUDED.typical_sleep_hours,
                preferred_days = EXCLUDED.preferred_days,
                preferred_windows = EXCLUDED.preferred_windows,
                is_pregnant = EXCLUDED.is_pregnant,
                medical_clearance = EXCLUDED.medical_clearance,
                activity_level = EXCLUDED.activity_level,
                daily_step_goal = EXCLUDED.daily_step_goal,
                daily_calorie_burn_goal = EXCLUDED.daily_calorie_burn_goal,
                sections_completed = EXCLUDED.sections_completed,
                updated_at = NOW()
            """
        ),
        {
            "uid": uid,
            "dob": data.date_of_birth,
            "gender": data.gender,
            "height": data.height_cm,
            "weight": data.weight_kg,
            "exp": data.experience_level,
            "goal": data.goal,
            "g_extra": data.goals_extra,
            "injuries": data.known_injuries,
            "notes": data.injury_notes,
            "allergies": data.allergies,
            "diet": data.dietary_preference,
            "cuisine": data.cuisine_prefs,
            "meals": data.meals_per_day,
            "sleep": data.typical_sleep_hours,
            "p_days": data.preferred_days,
            "p_windows": data.preferred_windows,
            "preg": data.is_pregnant,
            "med": data.medical_clearance,
            "act": data.activity_level,
            "steps": data.daily_step_goal,
            "burn": data.daily_calorie_burn_goal,
            "sections": sections,
        },
    )

    updated = await get_member_profile(db, user_id)
    return updated or {}


async def set_health_consent(
    db: AsyncSession,
    user_id: uuid.UUID | str,
    granted: bool,
) -> dict[str, Any]:
    """
    Grants (NOW()) or revokes (NULL) separate health-data consent.
    If no member_profile row exists yet, creates a placeholder with default biometrics.
    """
    uid = uuid.UUID(str(user_id))
    await set_rls_system(db)

    # Ensure profile row exists
    res = await db.execute(
        text("SELECT user_id, health_data_consent_at FROM member_profiles WHERE user_id = :uid"),
        {"uid": uid},
    )
    existing = res.mappings().one_or_none()
    if not existing:
        await db.execute(
            text(
                """
                INSERT INTO member_profiles (
                    user_id, date_of_birth, height_cm, weight_kg, updated_at
                ) VALUES (
                    :uid, '1995-01-01', 170.0, 70.0, NOW()
                )
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"uid": uid},
        )

    if granted:
        await db.execute(
            text("UPDATE member_profiles SET health_data_consent_at = NOW(), updated_at = NOW() WHERE user_id = :uid"),
            {"uid": uid},
        )
    else:
        await db.execute(
            text("UPDATE member_profiles SET health_data_consent_at = NULL, updated_at = NOW() WHERE user_id = :uid"),
            {"uid": uid},
        )

    res = await db.execute(
        text("SELECT health_data_consent_at FROM member_profiles WHERE user_id = :uid"),
        {"uid": uid},
    )
    row = res.mappings().one_or_none()
    c_at = row["health_data_consent_at"] if row else None
    return {
        "consented": c_at is not None,
        "health_data_consent_at": c_at.isoformat() if c_at else None,
    }


async def get_intake_history(
    db: AsyncSession,
    user_id: uuid.UUID | str,
) -> list[dict[str, Any]]:
    """
    Returns audit trail of member profile versions from member_intake_versions
    (powers 'What the AI remembers' screen).
    """
    uid = uuid.UUID(str(user_id))
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, snapshot, changed_by, created_at
            FROM member_intake_versions
            WHERE user_id = :uid
            ORDER BY created_at DESC
            """
        ),
        {"uid": uid},
    )
    return [dict(r) for r in res.mappings().all()]
