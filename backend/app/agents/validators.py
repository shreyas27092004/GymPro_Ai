# app/agents/validators.py
import re
from typing import Any
from .schemas import Envelope

RED_FLAG_KEYWORDS = [
    "chest pain",
    "chest tightness",
    "chest pressure",
    "fainting",
    "fainted",
    "near-fainting",
    "shortness of breath",
    "sudden numbness",
    "sudden weakness",
    "loss of vision",
    "loss of speech",
    "heart palpitations with dizziness",
    "palpitations",
    "visible deformity",
    "cannot bear weight",
    "can't bear weight",
    "suicidal",
    "kill myself",
    "end my life",
    "self-harm",
]

CRISIS_KEYWORDS = [
    "suicidal",
    "kill myself",
    "end my life",
    "self-harm",
    "cut myself",
]

EATING_DISORDER_KEYWORDS = [
    "burn off the food",
    "burn off what i ate",
    "vomit after eating",
    "purge",
    "extreme restriction",
    "starve myself",
    "fear of eating",
]


def validate_envelope(agent: str, env: Envelope, ctx: Any) -> None:
    """
    Deterministic safety and consistency checks executed after LLM response generation.
    Raises ValueError on invariant violations, triggering a retry or safe fallback.
    """
    agent_upper = agent.upper()
    user_msg = env.user_message.strip()

    # 1. Word count constraint (<= 80 words per prompt contract, <= 90 in schema)
    word_count = len(user_msg.split())
    if word_count > 90:
        raise ValueError(f"user_message too long ({word_count} words > 90 word ceiling)")

    # 2. General Safety Flags & Status Enforcement
    flags_set = set(env.safety.flags)

    if "PROMPT_INJECTION" in flags_set and env.status not in ("REFUSED", "OK"):
        raise ValueError("Prompt injection must result in REFUSED status")

    if "CROSS_USER_REQUEST" in flags_set and env.status != "REFUSED":
        raise ValueError("Cross-user requests must result in REFUSED status")

    if "PRIVILEGE_ESCALATION" in flags_set and env.status != "REFUSED":
        raise ValueError("Privilege escalation requests must result in REFUSED status")

    if "EMAIL_TARGET_REFUSED" in flags_set and env.status != "REFUSED":
        raise ValueError("Email target requests outside user account must result in REFUSED status")

    # 3. Domain Specific Validations
    if agent_upper == "SCHEDULE":
        _validate_schedule(env, ctx)
    elif agent_upper == "MEMBERSHIP":
        _validate_membership(env, ctx)
    elif agent_upper == "WELLNESS":
        _validate_wellness(env, ctx)
    elif agent_upper == "NUTRITION":
        _validate_nutrition(env, ctx)
    elif agent_upper == "COMMS":
        _validate_comms(env, ctx)
    elif agent_upper == "SUPPORT":
        _validate_support(env, ctx)
    elif agent_upper == "FITNESS":
        _validate_fitness(env, ctx)
    elif agent_upper == "TRAINER_INFO":
        _validate_trainer_info(env, ctx)


def _validate_schedule(env: Envelope, ctx: Any) -> None:
    if env.status == "NEEDS_CONFIRMATION":
        if not env.confirmation.action_id:
            raise ValueError("SCHEDULE: NEEDS_CONFIRMATION requires confirmation.action_id")
        if not env.confirmation.summary:
            raise ValueError("SCHEDULE: NEEDS_CONFIRMATION requires confirmation.summary")

    # If action was proposed for booking, verify that no completed claim was made in user_message
    if env.confirmation.action_id:
        lower_msg = env.user_message.lower()
        if "you are booked" in lower_msg or "i have booked you" in lower_msg or "booking is complete" in lower_msg:
            raise ValueError("SCHEDULE: user_message must not claim booking is already completed prior to confirmation")


def _validate_membership(env: Envelope, ctx: Any) -> None:
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}

    # Downgrades are handled by staff in v1; never proposed by agent
    if data.get("recommendation") == "DOWNGRADE":
        raise ValueError("MEMBERSHIP: Downgrades take effect at renewal and are handled by staff in v1; cannot propose downgrade")

    if env.status == "NEEDS_CONFIRMATION":
        if not env.confirmation.action_id:
            raise ValueError("MEMBERSHIP: Confirmation requires action_id")
        if not env.projected_effects:
            raise ValueError("MEMBERSHIP: Proposing a plan change must include projected_effects")
        # Summary must contain proration or pricing details
        summary = (env.confirmation.summary or "").lower()
        if not any(k in summary for k in ("pay", "inr", "prorated", "month", "ends today")):
            raise ValueError("MEMBERSHIP: Summary must detail cost and proration terms")


def _validate_wellness(env: Envelope, ctx: Any) -> None:
    flags_set = set(env.safety.flags)
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}

    # Check for Red Flag symptoms
    if "RED_FLAG_SYMPTOM" in flags_set:
        if env.status != "ESCALATE":
            raise ValueError("WELLNESS: RED_FLAG_SYMPTOM requires status ESCALATE")
        # No activity recommendations allowed in turn
        preferred = data.get("preferred_activities") or []
        avoid_categories = (data.get("safety_constraints") or {}).get("avoid_categories") or []
        if preferred and "ALL_EXERTION" not in avoid_categories:
            # Must not suggest active exercise
            for act in preferred:
                if act.upper() in ("HIIT", "SPIN", "STRENGTH", "RUNNING", "CROSSFIT"):
                    raise ValueError("WELLNESS: Cannot recommend exercise classes during RED_FLAG_SYMPTOM escalation")

    if "CRISIS" in flags_set:
        if env.status != "ESCALATE":
            raise ValueError("WELLNESS: CRISIS requires status ESCALATE")


def _validate_nutrition(env: Envelope, ctx: Any) -> None:
    flags_set = set(env.safety.flags)
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}
    session = getattr(ctx, "session", None)

    # Minor check (< 18)
    is_minor = getattr(session, "is_minor", False) if session else False
    if session and getattr(session, "age_years", None) is not None:
        if session.age_years < 18:
            is_minor = True

    if is_minor or "MINOR" in flags_set:
        # Minors must never receive calorie deficit / restricted plans
        daily_kcal = data.get("daily_calories")
        tdee = data.get("tdee_basis")
        if daily_kcal is not None and tdee is not None and daily_kcal < tdee:
            raise ValueError("NUTRITION: Calorie restriction is strictly forbidden for minors under 18")
        if env.status not in ("REFUSED", "OK", "NEEDS_INPUT"):
            raise ValueError("NUTRITION: Minor requests for weight loss diet must be REFUSED")

    # Eating disorder signal check
    if "EATING_DISORDER_SIGNAL" in flags_set or "CRISIS" in flags_set:
        if env.status != "ESCALATE":
            raise ValueError("NUTRITION: Eating disorder signals must be ESCALATE")
        if data.get("daily_calories") is not None:
            raise ValueError("NUTRITION: No numeric plan during eating disorder escalation")

    # Hard allergen validation
    allergies = []
    if session and hasattr(session, "allergies"):
        allergies.extend(session.allergies or [])
    allergen_check = data.get("allergen_check") or {}
    allergies.extend(allergen_check.get("allergies") or [])

    if allergies:
        lower_allergies = [a.lower().strip() for a in allergies if a]
        meals = data.get("meals") or []
        for meal in meals:
            items = meal.get("items") or []
            for it in items:
                food_name = (it.get("food") or "").lower()
                for allergen in lower_allergies:
                    if allergen in food_name:
                        raise ValueError(f"NUTRITION: Allergen violation: food '{food_name}' contains '{allergen}'")

    # Caloric floors (if plan generated)
    daily_kcal = data.get("daily_calories")
    if daily_kcal is not None and daily_kcal > 0:
        # Male floor 1500, Female/other floor 1200
        # If sex is known
        if daily_kcal < 1200:
            raise ValueError(f"NUTRITION: Daily calories ({daily_kcal}) violates absolute minimum floor of 1200 kcal")

        # Deficit check: not more than 500 kcal below TDEE
        tdee = data.get("tdee_basis")
        if tdee is not None and tdee > 0:
            deficit = tdee - daily_kcal
            if deficit > 500:
                raise ValueError(f"NUTRITION: Calorie deficit ({deficit} kcal) exceeds maximum safe deficit of 500 kcal")

        # Meal sum tolerance check (meal totals must equal daily totals within 3%)
        meals = data.get("meals") or []
        if meals:
            meal_sum = sum(m.get("kcal", 0) for m in meals)
            if meal_sum > 0:
                diff_pct = abs(meal_sum - daily_kcal) / daily_kcal
                if diff_pct > 0.03:
                    raise ValueError(f"NUTRITION: Meal kcal sum ({meal_sum}) differs from daily calories ({daily_kcal}) by > 3%")


BLAME_WORDS = re.compile(r"\b(fault|blame|incompetent|negligent|guilty|liable|fired)\b", re.I)


def _validate_comms(env: Envelope, ctx: Any) -> None:
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}
    to_masked = data.get("to_masked")
    session = getattr(ctx, "session", None)
    if to_masked and session and hasattr(session, "account_email") and session.account_email:
        user_email = session.account_email
        parts = user_email.split("@")
        expected_domain = parts[1].lower() if len(parts) > 1 else ""
        if not to_masked.lower().endswith(f"@{expected_domain}"):
            raise ValueError(f"COMMS: recipient must be the account email, got {to_masked}")

    # No health/injury in email subject or body preview
    title = (data.get("title") or "").lower()
    preview = (data.get("body_preview") or "").lower()
    for kw in ("injury", "knee", "back", "weight", "pregnant", "cardiac", "chest pain"):
        if kw in title or kw in preview:
            raise ValueError(f"COMMS: subject/preview must not contain personal health details ('{kw}')")

    # BOOKING_DETAILS requires attach_calendar = True
    if data.get("template_id") == "BOOKING_DETAILS" and not data.get("attach_calendar"):
        raise ValueError("COMMS: BOOKING_DETAILS template requires attach_calendar=True")


def _validate_support(env: Envelope, ctx: Any) -> None:
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}
    summary = data.get("neutral_summary")
    if summary:
        if len(summary.split()) > 40:
            raise ValueError(f"SUPPORT: neutral_summary ({len(summary.split())} words) exceeds 40-word limit")
        if BLAME_WORDS.search(summary):
            raise ValueError("SUPPORT: summary must be neutral, contains blame words")


def _validate_fitness(env: Envelope, ctx: Any) -> None:
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}
    if env.status == "OK":
        rec_classes = data.get("recommended_classes") or []

        # Check against handoff safety constraints if present
        handoff = getattr(ctx, "handoff", {}) or {}
        if isinstance(handoff, dict):
            safety_constraints = handoff.get("safety_constraints") or {}
            handoff_avoid = set(c.upper() for c in (safety_constraints.get("avoid_categories") or []))
            max_impact = safety_constraints.get("max_impact")
            for rc in rec_classes:
                cat = rc.get("category", "").upper()
                if cat in handoff_avoid:
                    raise ValueError(f"FITNESS: class category '{cat}' violates avoid_categories safety constraint")
                if max_impact == "LOW" and rc.get("max_impact", "").upper() in ("MODERATE", "HIGH"):
                    raise ValueError(f"FITNESS: class '{cat}' exceeds max_impact 'LOW'")

        # Based_on check
        if rec_classes and not data.get("based_on"):
            raise ValueError("FITNESS: based_on must be populated with inputs used for planning")


def _validate_trainer_info(env: Envelope, ctx: Any) -> None:
    data = env.data if isinstance(env.data, dict) else env.data.model_dump() if hasattr(env.data, "model_dump") else {}
    trainers = data.get("trainers") or []
    if len(trainers) > 3:
        raise ValueError(f"TRAINER_INFO: returned {len(trainers)} trainers; maximum 3 allowed")

    for t in trainers:
        review_count = t.get("review_count", 0)
        if review_count < 5:
            if not t.get("is_new"):
                raise ValueError("TRAINER_INFO: trainers with < 5 reviews must be labeled 'is_new: true'")
            if t.get("rating") is not None:
                raise ValueError("TRAINER_INFO: trainers with < 5 reviews must NOT show a star rating")

    # Outcome promises check in user_message
    lower_msg = env.user_message.lower()
    if any(k in lower_msg for k in ("will lose", "guaranteed", "promise you", "lose 10 kg")):
        raise ValueError("TRAINER_INFO: user_message must not promise health or physical outcomes")

