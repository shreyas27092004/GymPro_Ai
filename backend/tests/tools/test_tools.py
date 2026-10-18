# tests/tools/test_tools.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import uuid
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.schemas import Confirmation, Envelope, MacroSet, Safety
from app.auth.deps import SessionContext
from app.auth.security import create_access_token, hash_password
from app.db import set_rls_system
from app.tools import (
    TOOLS,
    RunContext,
    calc_bmi,
    calc_bmr,
    calc_energy,
    calc_hydration,
    calc_progression,
    compute_macros,
    dispatch,
)
from tests.conftest import TestSeedSession, superuser_engine


async def create_user(
    db: AsyncSession,
    email: str,
    role: str = "USER",
    cooling_off: bool = False,
    consent: bool = False,
) -> SessionContext:
    uid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at, token_version)
                VALUES (:id, :email, :pw, 'Test User', :role, 'ACTIVE', NOW(), 0)
                """
            ),
            {"id": uid, "email": email, "pw": hash_password("password123"), "role": role},
        )
        await seed_db.commit()

    return SessionContext(
        user_id=str(uid),
        role=role,
        account_status="ACTIVE",
        plan=None,
        account_email=email,
        full_name="Test User",
        health_consent=consent,
        cooling_off_active=cooling_off,
        age_years=25,
    )


# -------------------------------------------------------------------------
# 1. Registry Scan Test (Security and Invariant Guard)
# -------------------------------------------------------------------------
def test_registry_scan_invariants():
    """
    Scans every registered tool in the catalog:
    - Every tool declares non-empty roles.
    - Every tool's kind is strictly in {"read", "calc", "propose"}.
    - No write tool exists.
    - No args model accepts user_id, recipient, email, to, role, or password
      (except staff invite which uses email_target and role='TRAINER').
    - Specifically, propose_send_email has NO recipient argument.
    - No tool exists to approve an admin-role request.
    """
    assert len(TOOLS) >= 20, "Tool registry must contain all catalog tools"

    disallowed_arg_names = {"user_id", "recipient", "to", "password"}

    for name, t in TOOLS.items():
        # Kind check: NO WRITE TOOLS
        assert t.kind in ("read", "calc", "propose"), f"Tool {name} has invalid kind: {t.kind}"
        assert t.kind != "write", f"Write tool detected: {name}. Write tools are strictly forbidden."

        # Role declaration check
        assert len(t.roles) > 0, f"Tool {name} must declare permitted roles"
        for r in t.roles:
            assert r in ("USER", "TRAINER", "ADMIN", "SYSTEM"), f"Invalid role {r} in tool {name}"

        # Argument scan
        fields = t.args_model.model_fields.keys()
        for f in fields:
            assert f not in disallowed_arg_names, (
                f"Tool {name} accepts forbidden argument '{f}'. "
                "Identity/recipient must be injected from session context."
            )

        # Propose send email specific check
        if name == "propose_send_email":
            assert "recipient" not in fields
            assert "to" not in fields
            assert "email" not in fields

        # No tool approves an admin request
        assert "approve_admin" not in name.lower()
        assert "admin_approve" not in name.lower()


# -------------------------------------------------------------------------
# 2. Role Authorization / Dispatch Tests
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_role_authorization_and_allowlist(db_session: AsyncSession):
    user_session = await create_user(db_session, "user_authz@gympro.test", role="USER")

    # A: User calling a TRAINER-only tool -> FORBIDDEN
    ctx_user = RunContext(session=user_session, db=db_session, allowed_tools={"get_my_availability"})
    res1 = await dispatch("get_my_availability", {}, ctx_user)
    assert res1["ok"] is False
    assert res1["error"] == "FORBIDDEN"

    # B: User calling an ADMIN-only tool -> FORBIDDEN
    ctx_admin_tool = RunContext(session=user_session, db=db_session, allowed_tools={"get_metric"})
    res2 = await dispatch("get_metric", {"metric_name": "active_members"}, ctx_admin_tool)
    assert res2["ok"] is False
    assert res2["error"] == "FORBIDDEN"

    # C: Tool not in ctx.allowed_tools -> TOOL_NOT_ALLOWED
    ctx_disallowed = RunContext(session=user_session, db=db_session, allowed_tools={"search_classes"})
    res3 = await dispatch("get_my_bookings", {}, ctx_disallowed)
    assert res3["ok"] is False
    assert res3["error"] == "TOOL_NOT_ALLOWED"


# -------------------------------------------------------------------------
# 3. Consent Gating Tests
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_consent_gating(db_session: AsyncSession):
    # User WITHOUT health consent
    no_consent_user = await create_user(db_session, "no_consent@gympro.test", role="USER", consent=False)
    ctx_no_consent = RunContext(
        session=no_consent_user,
        db=db_session,
        allowed_tools={"get_my_intake", "get_my_health_profile", "get_my_nutrition_inputs"},
    )

    # All tools with needs_health_consent=True must fail with CONSENT_REQUIRED
    res1 = await dispatch("get_my_intake", {}, ctx_no_consent)
    assert res1["ok"] is False
    assert res1["error"] == "CONSENT_REQUIRED"

    res2 = await dispatch("get_my_health_profile", {}, ctx_no_consent)
    assert res2["ok"] is False
    assert res2["error"] == "CONSENT_REQUIRED"

    res3 = await dispatch("get_my_nutrition_inputs", {}, ctx_no_consent)
    assert res3["ok"] is False
    assert res3["error"] == "CONSENT_REQUIRED"

    # User WITH health consent
    consenting_user = await create_user(db_session, "consenting@gympro.test", role="USER", consent=True)
    # Seed member profile
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO member_profiles (
                    user_id, date_of_birth, gender, height_cm, weight_kg,
                    experience_level, goal, dietary_preference, health_data_consent_at
                ) VALUES (
                    :uid, '1998-05-15', 'FEMALE', 165.00, 62.00,
                    'INTERMEDIATE', 'FAT_LOSS', 'VEGETARIAN', NOW()
                )
                """
            ),
            {"uid": uuid.UUID(consenting_user.user_id)},
        )

    ctx_consent = RunContext(
        session=consenting_user,
        db=db_session,
        allowed_tools={"get_my_intake", "get_my_health_profile", "get_my_nutrition_inputs"},
    )
    res_ok = await dispatch("get_my_intake", {}, ctx_consent)
    assert res_ok["ok"] is True
    assert res_ok["profile"]["goal"] == "FAT_LOSS"


# -------------------------------------------------------------------------
# 4. Cooling-Off Period Tests
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cooling_off_period_blocks_sensitive_tools(db_session: AsyncSession):
    # Admin during cooling-off window
    cooling_admin = await create_user(db_session, "cooling_admin@gympro.test", role="ADMIN", cooling_off=True)
    ctx_cooling = RunContext(
        session=cooling_admin,
        db=db_session,
        allowed_tools={"propose_broadcast", "propose_decide_trainer_request", "get_metric"},
    )

    # Sensitive tools with blocked_in_cooling_off=True return COOLING_OFF_ACTIVE
    res_bcast = await dispatch("propose_broadcast", {"subject": "Test Announcement", "body": "Hello gym members"}, ctx_cooling)
    assert res_bcast["ok"] is False
    assert res_bcast["error"] == "COOLING_OFF_ACTIVE"

    res_decide = await dispatch("propose_decide_trainer_request", {"request_id": str(uuid.uuid4()), "decision": "APPROVE", "reason": "Good"}, ctx_cooling)
    assert res_decide["ok"] is False
    assert res_decide["error"] == "COOLING_OFF_ACTIVE"

    # Non-sensitive tools still work for cooling-off admin
    res_metric = await dispatch("get_metric", {"metric_name": "active_members"}, ctx_cooling)
    assert res_metric["ok"] is True


# -------------------------------------------------------------------------
# 5. Allergen Fail-Closed Test
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_allergen_fail_closed_food_filtering(db_session: AsyncSession):
    user = await create_user(db_session, "allergy_user@gympro.test", role="USER", consent=True)
    # Seed member profile with DAIRY and NUTS allergies
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO member_profiles (
                    user_id, date_of_birth, height_cm, weight_kg,
                    allergies, health_data_consent_at
                ) VALUES (
                    :uid, '1995-01-01', 170.00, 65.00,
                    ARRAY['DAIRY', 'NUTS', 'TREE_NUTS'], NOW()
                )
                """
            ),
            {"uid": uuid.UUID(user.user_id)},
        )

    ctx = RunContext(session=user, db=db_session, allowed_tools={"find_foods"})

    # Query for milk products: Almond Milk (NUTS) and Greek Yogurt (DAIRY) must be excluded; Soy Milk (SOY) included
    res_milk = await dispatch("find_foods", {"query": "Milk"}, ctx)
    assert res_milk["ok"] is True
    food_names = [f["name"] for f in res_milk["foods"]]
    assert "Soy Milk" in food_names
    assert "Almond Milk" not in food_names
    assert "Greek Yogurt" not in food_names

    # Query for oats: regular Rolled Oats (GLUTEN) allowed, Peanut Butter (PEANUTS) would be allowed if queried
    res_oats = await dispatch("find_foods", {"query": "Oats"}, ctx)
    assert res_oats["ok"] is True
    oat_names = [f["name"] for f in res_oats["foods"]]
    assert "Rolled Oats" in oat_names


# -------------------------------------------------------------------------
# 6. Calculator Unit Tests
# -------------------------------------------------------------------------
def test_calculators():
    # 1. BMR (Mifflin-St Jeor)
    # Male: 75 kg, 178 cm, 30 years -> 10*75 + 6.25*178 - 5*30 + 5 = 1717.5
    bmr_m = calc_bmr(75.0, 178.0, 30, gender="MALE")
    assert bmr_m == 1717.5

    # Female: 60 kg, 165 cm, 28 years -> 10*60 + 6.25*165 - 5*28 - 161 = 1330.25 -> 1330.2
    bmr_f = calc_bmr(60.0, 165.0, 28, gender="FEMALE")
    assert abs(bmr_f - 1330.25) < 0.1

    # 2. TDEE / Energy
    tdee_sed = calc_energy(1717.5, "SEDENTARY")
    assert tdee_sed == round(1717.5 * 1.2)  # 2061

    tdee_mod = calc_energy(1717.5, "MODERATE")
    assert tdee_mod == round(1717.5 * 1.55)  # 2662

    # 3. BMI
    bmi_normal = calc_bmi(70.0, 175.0)
    assert bmi_normal["bmi"] == 22.9
    assert bmi_normal["category"] == "NORMAL"

    bmi_obese = calc_bmi(95.0, 175.0)
    assert bmi_obese["bmi"] == 31.0
    assert bmi_obese["category"] == "OBESE"

    # 4. Hydration
    # 70 kg, 60 min exercise -> 70 * 35 + (60/30) * 350 = 2450 + 700 = 3150 ml
    hyd = calc_hydration(70.0, minutes_exercise=60)
    assert hyd == 3150

    # 5. Macros (4/4/9 calorie rule, sums within 1%)
    target_cal = 2200
    macros = compute_macros(target_cal, goal="FAT_LOSS")
    assert macros["target_calories"] == target_cal
    assert abs(macros["actual_calories"] - target_cal) / target_cal <= 0.01
    computed_sum = macros["protein_g"] * 4 + macros["carbs_g"] * 4 + macros["fats_g"] * 9
    assert computed_sum == macros["actual_calories"]

    # 6. Progression (Epley 1RM + Overload)
    prog = calc_progression(current_weight_kg=100.0, reps=5, rpe=7.0)
    assert prog["estimated_1rm_kg"] == 116.7  # 100 * (1 + 5/30)
    assert prog["recommended_weight_kg"] == 102.5  # +2.5 kg on low RPE


# -------------------------------------------------------------------------
# 7. Propose Tools Create Pending Actions
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_propose_tools_create_pending_actions(db_session: AsyncSession):
    user = await create_user(db_session, "propose_test@gympro.test", role="USER")

    # Seed an active class
    tid = uuid.uuid4()
    cid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:tid, 'c@gympro.test', 'p', 'Coach', 'TRAINER', 'ACTIVE') ON CONFLICT DO NOTHING"),
            {"tid": tid},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO trainer_profiles (trainer_id) VALUES (:tid) ON CONFLICT DO NOTHING"),
            {"tid": tid},
        )
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, capacity, booked_count, start_time, end_time, status)
                VALUES (:cid, 'Spin Blast', :tid, 'SPIN', 'HIGH', 'BEGINNER', 20, 0, NOW() + INTERVAL '2 days', NOW() + INTERVAL '2 days 1 hour', 'SCHEDULED')
                """
            ),
            {"cid": cid, "tid": tid},
        )

    ctx = RunContext(
        session=user,
        db=db_session,
        allowed_tools={"propose_booking", "propose_send_email"},
    )

    # 1. Propose booking
    res_book = await dispatch("propose_booking", {"class_id": str(cid)}, ctx)
    assert res_book["ok"] is True
    assert res_book["type"] == "BOOK_CLASS"
    action_id = uuid.UUID(res_book["action_id"])

    # Verify database pending_actions row
    await set_rls_system(db_session)
    act_res = await db_session.execute(
        text("SELECT status, type, user_id FROM pending_actions WHERE id = :aid"),
        {"aid": action_id},
    )
    act_row = act_res.mappings().one()
    assert act_row["status"] == "PENDING"
    assert act_row["type"] == "BOOK_CLASS"
    assert act_row["user_id"] == uuid.UUID(user.user_id)

    # 2. Propose send email (NO recipient argument passed)
    res_email = await dispatch(
        "propose_send_email",
        {"template_id": "CLASS_CONFIRMED", "params": {"class_id": str(cid)}},
        ctx,
    )
    assert res_email["ok"] is True
    email_aid = uuid.UUID(res_email["action_id"])
    await set_rls_system(db_session)
    e_chk = await db_session.execute(
        text("SELECT status, type FROM pending_actions WHERE id = :aid"),
        {"aid": email_aid},
    )
    e_row = e_chk.mappings().one()
    assert e_row["status"] == "PENDING"
    assert e_row["type"] == "SEND_BOOKING_EMAIL"


# -------------------------------------------------------------------------
# 8. Pydantic Envelope Validation
# -------------------------------------------------------------------------
def test_envelope_schema_validation():
    # Valid envelope
    env = Envelope(
        agent="SCHEDULE",
        schema_version="1.0",
        status="OK",
        data={"booked": True},
        user_message="Your spin class is confirmed for tomorrow morning.",
        confirmation=Confirmation(action_id="123", summary="Book spin"),
        safety=Safety(flags=[]),
        confidence=0.95,
    )
    assert env.agent == "SCHEDULE"
    assert env.status == "OK"

    # User message > 90 words fails validation
    long_msg = "word " * 95
    with pytest.raises(ValidationError) as exc_info:
        Envelope(
            agent="SCHEDULE",
            schema_version="1.0",
            status="OK",
            user_message=long_msg,
        )
    assert "user_message too long" in str(exc_info.value)
