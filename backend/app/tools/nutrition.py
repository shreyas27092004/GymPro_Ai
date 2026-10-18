# app/tools/nutrition.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .calculators import compute_macros as calc_macros_fn
from .registry import RunContext, tool


class ComputeMacrosArgs(BaseArgs):
    daily_calories: int = Field(gt=500, le=8000)
    goal: str = "MAINTENANCE"
    weight_kg: float | None = None


class SearchNutritionKbArgs(BaseArgs):
    query: str = Field(min_length=1, max_length=100)


class FindFoodsArgs(BaseArgs):
    query: str = Field(min_length=1, max_length=100)
    category: str | None = None


class ProposeSavePlanArgs(BaseArgs):
    dietary_preference: str
    target_calories: int = Field(ge=800, le=6000)
    protein_g: int = Field(ge=0)
    carbs_g: int = Field(ge=0)
    fat_g: int = Field(ge=0)
    meals: list[dict[str, Any]] = Field(default_factory=list)


# Static curated food catalog with allergen tagging for allergen-safe filtering
FOOD_CATALOG = [
    {"name": "Rolled Oats", "category": "CARBS", "allergens": ["GLUTEN"], "calories": 389, "protein": 16.9, "carbs": 66.3, "fat": 6.9},
    {"name": "Gluten-Free Oats", "category": "CARBS", "allergens": [], "calories": 380, "protein": 15.0, "carbs": 68.0, "fat": 6.0},
    {"name": "Greek Yogurt", "category": "PROTEIN", "allergens": ["DAIRY"], "calories": 59, "protein": 10.0, "carbs": 3.6, "fat": 0.4},
    {"name": "Almond Milk", "category": "BEVERAGE", "allergens": ["NUTS", "TREE_NUTS"], "calories": 15, "protein": 0.5, "carbs": 0.3, "fat": 1.1},
    {"name": "Soy Milk", "category": "BEVERAGE", "allergens": ["SOY"], "calories": 33, "protein": 2.8, "carbs": 1.6, "fat": 1.8},
    {"name": "Peanut Butter", "category": "FATS", "allergens": ["PEANUTS"], "calories": 588, "protein": 25.0, "carbs": 20.0, "fat": 50.0},
    {"name": "Boiled Eggs", "category": "PROTEIN", "allergens": ["EGGS"], "calories": 155, "protein": 13.0, "carbs": 1.1, "fat": 11.0},
    {"name": "Tofu (Firm)", "category": "PROTEIN", "allergens": ["SOY"], "calories": 76, "protein": 8.0, "carbs": 1.9, "fat": 4.8},
    {"name": "Paneer", "category": "PROTEIN", "allergens": ["DAIRY"], "calories": 265, "protein": 18.0, "carbs": 1.2, "fat": 20.8},
    {"name": "Chicken Breast", "category": "PROTEIN", "allergens": [], "calories": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.6},
    {"name": "White Rice", "category": "CARBS", "allergens": [], "calories": 130, "protein": 2.7, "carbs": 28.2, "fat": 0.3},
    {"name": "Banana", "category": "FRUIT", "allergens": [], "calories": 89, "protein": 1.1, "carbs": 22.8, "fat": 0.3},
]


@tool("get_my_nutrition_inputs", EmptyArgs, roles={"USER"}, kind="read", needs_health_consent=True)
async def get_my_nutrition_inputs(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT dietary_preference, cuisine_prefs, meals_per_day, allergies,
                   goal, weight_kg, height_cm
            FROM member_profiles
            WHERE user_id = :uid
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "NUTRITION_INPUTS_NOT_FOUND"}

    return {
        "ok": True,
        "inputs": {
            "dietary_preference": row["dietary_preference"],
            "cuisine_prefs": row["cuisine_prefs"] or [],
            "meals_per_day": row["meals_per_day"],
            "allergies": row["allergies"] or [],
            "goal": row["goal"],
            "weight_kg": float(row["weight_kg"]),
            "height_cm": float(row["height_cm"]),
        },
    }


@tool("compute_macros", ComputeMacrosArgs, roles={"USER"}, kind="calc")
async def compute_macros(args: ComputeMacrosArgs, ctx: RunContext) -> dict[str, Any]:
    try:
        macros = calc_macros_fn(
            daily_calories=args.daily_calories,
            goal=args.goal,
            weight_kg=args.weight_kg,
        )
        return {"ok": True, **macros}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@tool("search_nutrition_kb", SearchNutritionKbArgs, roles={"USER"}, kind="read")
async def search_nutrition_kb(args: SearchNutritionKbArgs, ctx: RunContext) -> dict[str, Any]:
    kb = [
        {"title": "Protein Requirements for Muscle Synthesis", "content": "1.6 to 2.2 grams of protein per kilogram of body weight is optimal for hypertrophy."},
        {"title": "Fat Loss Calorie Deficits", "content": "A moderate deficit of 300-500 kcal/day preserves lean mass while achieving sustainable fat loss."},
        {"title": "Pre-Workout Carb Timing", "content": "Consume 30-50g of easily digestible complex carbs 60-90 minutes prior to intense lifting or spin."},
    ]
    matches = [
        e for e in kb
        if args.query.lower() in e["title"].lower() or args.query.lower() in e["content"].lower()
    ]
    return {"ok": True, "articles": matches}


@tool("find_foods", FindFoodsArgs, roles={"USER"}, kind="read")
async def find_foods(args: FindFoodsArgs, ctx: RunContext) -> dict[str, Any]:
    """
    Searches the food catalog with fail-closed allergen filtering.
    Reads user allergies from member_profiles (if consented) and excludes
    any item matching user allergies.
    """
    user_allergies = set()
    if ctx.session.health_consent:
        await set_rls_system(ctx.db)
        res = await ctx.db.execute(
            text("SELECT allergies FROM member_profiles WHERE user_id = :uid"),
            {"uid": uuid.UUID(ctx.session.user_id)},
        )
        row = res.mappings().one_or_none()
        if row and row["allergies"]:
            user_allergies = {a.upper() for a in row["allergies"]}

    q = args.query.lower()
    results = []
    for food in FOOD_CATALOG:
        food_allergens = {a.upper() for a in food["allergens"]}
        # Allergen fail-closed: exclude if food intersects with any user allergy
        if user_allergies.intersection(food_allergens):
            continue

        if q in food["name"].lower() or q in food["category"].lower():
            if not args.category or args.category.upper() == food["category"]:
                results.append(food)

    return {"ok": True, "count": len(results), "foods": results}


@tool("propose_save_plan", ProposeSavePlanArgs, roles={"USER"}, kind="propose")
async def propose_save_plan(args: ProposeSavePlanArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Save {args.dietary_preference} meal plan ({args.target_calories} kcal/day)"
    payload = {
        "dietary_preference": args.dietary_preference,
        "target_calories": args.target_calories,
        "protein_grams": args.protein_g,
        "carb_grams": args.carbs_g,
        "fat_grams": args.fat_g,
        "meal_plan_details": args.meals,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'SAVE_NUTRITION_PLAN', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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
        "type": "SAVE_NUTRITION_PLAN",
    }
