# app/tools/calculators.py
from decimal import Decimal
from typing import Any
from ..entitlements.membership import PriceDiffQuote, price_diff


def calc_bmr(
    weight_kg: float,
    height_cm: float,
    age_years: int,
    gender: str = "UNSPECIFIED",
) -> float:
    """
    Computes Basal Metabolic Rate using the Mifflin-St Jeor formula.
    - Men: 10 * weight_kg + 6.25 * height_cm - 5 * age_years + 5
    - Women: 10 * weight_kg + 6.25 * height_cm - 5 * age_years - 161
    - Other/Unspecified: average of male and female formulas
    """
    g = gender.upper()
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years
    if g == "MALE":
        bmr = base + 5.0
    elif g == "FEMALE":
        bmr = base - 161.0
    else:
        bmr = base - 78.0

    return round(max(500.0, min(5000.0, bmr)), 1)


def calc_energy(
    bmr: float,
    activity_level: str = "SEDENTARY",
) -> int:
    """
    Computes Total Daily Energy Expenditure (TDEE) based on activity multiplier.
    """
    multipliers = {
        "SEDENTARY": 1.2,
        "LIGHT": 1.375,
        "MODERATE": 1.55,
        "VERY_ACTIVE": 1.725,
        "EXTRA_ACTIVE": 1.9,
    }
    m = multipliers.get(activity_level.upper(), 1.2)
    return round(bmr * m)


def calc_bmi(
    weight_kg: float,
    height_cm: float,
) -> dict[str, Any]:
    """
    Computes Body Mass Index and classification category.
    """
    height_m = height_cm / 100.0
    if height_m <= 0:
        raise ValueError("Height must be greater than zero")
    bmi = round(weight_kg / (height_m ** 2), 1)

    if bmi < 18.5:
        category = "UNDERWEIGHT"
    elif bmi < 25.0:
        category = "NORMAL"
    elif bmi < 30.0:
        category = "OVERWEIGHT"
    else:
        category = "OBESE"

    return {"bmi": bmi, "category": category}


def calc_hydration(
    weight_kg: float,
    minutes_exercise: int = 0,
) -> int:
    """
    Computes daily hydration requirement in milliliters:
    weight_kg * 35 ml + (minutes_exercise / 30) * 350 ml.
    """
    baseline = weight_kg * 35.0
    exercise_bonus = (max(0, minutes_exercise) / 30.0) * 350.0
    return round(baseline + exercise_bonus)


def compute_macros(
    daily_calories: int,
    goal: str = "MAINTENANCE",
    weight_kg: float | None = None,
) -> dict[str, Any]:
    """
    Computes macronutrient gram distribution ensuring 4/4/9 calorie math
    and ensuring the sum is within 1% of target calories.
    """
    if daily_calories <= 0:
        raise ValueError("daily_calories must be positive")

    g = goal.upper()
    if g == "FAT_LOSS":
        p_ratio, f_ratio = 0.35, 0.25
    elif g == "MUSCLE_GAIN":
        p_ratio, f_ratio = 0.30, 0.20
    elif g == "ENDURANCE":
        p_ratio, f_ratio = 0.20, 0.20
    else:  # MAINTENANCE
        p_ratio, f_ratio = 0.25, 0.25

    protein_g = round((daily_calories * p_ratio) / 4.0)
    fats_g = round((daily_calories * f_ratio) / 9.0)
    # Remaining calories allocated to carbohydrates
    carbs_cal = daily_calories - (protein_g * 4 + fats_g * 9)
    carbs_g = max(0, round(carbs_cal / 4.0))

    actual_calories = protein_g * 4 + carbs_g * 4 + fats_g * 9
    pct_diff = abs(actual_calories - daily_calories) / daily_calories
    if pct_diff > 0.01:
        # Fine-tune carbs if off by more than 1%
        diff_cal = daily_calories - actual_calories
        carbs_g += round(diff_cal / 4.0)
        actual_calories = protein_g * 4 + carbs_g * 4 + fats_g * 9

    return {
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fats_g": fats_g,
        "actual_calories": actual_calories,
        "target_calories": daily_calories,
    }


def calc_progression(
    current_weight_kg: float,
    reps: int,
    rpe: float = 8.0,
    goal: str = "HYPERTROPHY",
) -> dict[str, Any]:
    """
    Computes estimated 1-Rep Max using the Epley formula:
    1RM = weight * (1 + reps / 30)
    Recommends progressive overload target weight and reps for next session.
    """
    reps = max(1, reps)
    est_1rm = round(current_weight_kg * (1.0 + reps / 30.0), 1)

    if rpe <= 7.0:
        recommended_weight = current_weight_kg + 2.5
        recommended_reps = reps
        target_rpe = 8.0
        note = "Excellent bar speed and low RPE. Increment load by 2.5 kg."
    elif rpe <= 8.5:
        recommended_weight = current_weight_kg + 1.25
        recommended_reps = reps
        target_rpe = 8.5
        note = "Target intensity met. Increment load by 1.25 kg."
    else:
        recommended_weight = current_weight_kg
        recommended_reps = min(reps + 1, 12)
        target_rpe = 8.0
        note = "High exertion detected (RPE > 8.5). Maintain weight and focus on rep quality."

    return {
        "current_weight_kg": current_weight_kg,
        "reps": reps,
        "rpe": rpe,
        "estimated_1rm_kg": est_1rm,
        "recommended_weight_kg": recommended_weight,
        "recommended_reps": recommended_reps,
        "target_rpe": target_rpe,
        "note": note,
    }


__all__ = [
    "price_diff",
    "PriceDiffQuote",
    "calc_bmr",
    "calc_energy",
    "calc_bmi",
    "calc_hydration",
    "compute_macros",
    "calc_progression",
]
