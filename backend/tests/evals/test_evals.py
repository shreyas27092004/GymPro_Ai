# tests/evals/test_evals.py
from datetime import datetime, timezone
from pathlib import Path
import uuid
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.runner import run_agent, safe_fallback
from app.auth.deps import SessionContext
from app.db import set_rls_system
from app.llm import set_llm
from app.prompts import load_prompt, sync_prompt_versions
from app.tools.registry import RunContext
from tests.conftest import TestSeedSession, superuser_engine
from tests.evals.fake_llm import fake_llm


@pytest.fixture(autouse=True)
def setup_fake_llm():
    """Ensure FakeLLM is injected into the runner for all eval tests."""
    set_llm(fake_llm)
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()
    yield
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()


async def seed_eval_db_fixtures(db: AsyncSession):
    """Seed test trainer and sample class for schedule evals."""
    tid = uuid.UUID("99999999-9999-9999-9999-999999999999")
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:tid, 'trainer99@gympro.test', 'p', 'Asha Rao', 'TRAINER', 'ACTIVE') ON CONFLICT DO NOTHING"),
            {"tid": tid},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO trainer_profiles (trainer_id) VALUES (:tid) ON CONFLICT DO NOTHING"),
            {"tid": tid},
        )
        cid = uuid.UUID("11111111-1111-1111-1111-111111111111")
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, capacity, booked_count, start_time, end_time, status)
                VALUES (:cid, 'Evening Yoga', :tid, 'YOGA', 'LOW', 'BEGINNER', 20, 0, '2026-10-17 18:00:00+05:30', '2026-10-17 19:00:00+05:30', 'SCHEDULED')
                ON CONFLICT (id) DO NOTHING;
                """
            ),
            {"cid": cid, "tid": tid},
        )


def load_yaml_cases(name: str) -> list[dict]:
    p = Path(__file__).parent / "cases" / f"{name}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# -------------------------------------------------------------------------
# 1. Schedule Agent Evals
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eval_schedule(db_session: AsyncSession):
    await seed_eval_db_fixtures(db_session)
    cases = load_yaml_cases("schedule")

    for case in cases:
        user_id = str(uuid.uuid4())
        # Seed user in DB so propose_booking pending_actions can reference users(id)
        email = f"sched_eval_{user_id[:8]}@gympro.test"
        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Sched', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Schedule Eval User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("SCHEDULE", ctx, case["input"])
        exp = case["expect"]

        # 1. Status Check
        if "status_in" in exp:
            assert env.status in exp["status_in"], f"Case {case['id']}: unexpected status {env.status}"

        # 2. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools, f"Case {case['id']}: expected tool {t} was not called"
        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools, f"Case {case['id']}: forbidden tool {t} was called"

        # 3. Flags check
        for f in exp.get("flags_include", []):
            assert f in env.safety.flags, f"Case {case['id']}: expected safety flag {f}"

        # 4. Confirmation check
        if exp.get("confirmation_present"):
            assert env.confirmation.action_id is not None, f"Case {case['id']}: confirmation action_id missing"

        # 5. No completed claim
        if exp.get("no_completed_claim"):
            low = env.user_message.lower()
            assert "you are booked" not in low and "i have booked you" not in low, f"Case {case['id']}: claims completed booking"


# -------------------------------------------------------------------------
# 2. Membership Agent Evals
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eval_membership(db_session: AsyncSession):
    await seed_eval_db_fixtures(db_session)
    cases = load_yaml_cases("membership")

    for case in cases:
        user_id = str(uuid.uuid4())
        session_data = case.get("session") or {}

        # Seed user and membership in DB so price_diff and propose_plan_change work
        email = f"member_eval_{user_id[:8]}@gympro.test"
        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Member', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        if session_data.get("plan") or case["id"] == "member-001-upgrade":
            async with superuser_engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
                        VALUES (gen_random_uuid(), :uid, 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, CURRENT_DATE - INTERVAL '10 days', CURRENT_DATE + INTERVAL '20 days')
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"uid": uuid.UUID(user_id)},
                )
        if session_data.get("trial"):
            tr = session_data["trial"]
            async with superuser_engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO trial_grants (id, user_id, classes_total, classes_used, starts_at, expires_at)
                        VALUES (gen_random_uuid(), :uid, :ct, :cu, NOW() - INTERVAL '5 days', NOW() + INTERVAL '9 days')
                        ON CONFLICT (user_id) DO NOTHING
                        """
                    ),
                    {"uid": uuid.UUID(user_id), "ct": tr["classes_total"], "cu": tr["classes_used"]},
                )

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan=session_data.get("plan", "GOLD"),
            account_email=email,
            full_name="Member Eval User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("MEMBERSHIP", ctx, case["input"])
        exp = case["expect"]

        # 1. Status Check
        if "status_in" in exp:
            assert env.status in exp["status_in"], f"Case {case['id']}: unexpected status {env.status}"

        # 2. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools, f"Case {case['id']}: expected tool {t} was not called"
        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools, f"Case {case['id']}: forbidden tool {t} was called"

        # 3. Flags check
        for f in exp.get("flags_include", []):
            assert f in env.safety.flags, f"Case {case['id']}: expected safety flag {f}"

        # 4. Projected plan after
        if "projected_plan_after" in exp:
            assert env.projected_effects is not None
            assert env.projected_effects.get("plan_after") == exp["projected_plan_after"]


# -------------------------------------------------------------------------
# 3. Wellness Agent Evals
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eval_wellness(db_session: AsyncSession):
    await seed_eval_db_fixtures(db_session)
    cases = load_yaml_cases("wellness")

    for case in cases:
        user_id = str(uuid.uuid4())
        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email="wellness_eval@gympro.test",
            full_name="Wellness Eval User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("WELLNESS", ctx, case["input"])
        exp = case["expect"]

        # 1. Status Check
        if "status_in" in exp:
            assert env.status in exp["status_in"], f"Case {case['id']}: unexpected status {env.status}"

        # 2. Flags Check (RED_FLAG_SYMPTOM, CRISIS, PROMPT_INJECTION at 100%)
        for f in exp.get("flags_include", []):
            assert f in env.safety.flags, f"Case {case['id']}: safety flag {f} missing"

        # 3. No activity recommendations on red-flag
        if exp.get("no_activity_recommendations"):
            assert env.status == "ESCALATE"
            data = env.data if isinstance(env.data, dict) else env.data.model_dump()
            preferred = data.get("preferred_activities") or []
            assert len(preferred) == 0, f"Case {case['id']}: recommended exercise during red flag"


# -------------------------------------------------------------------------
# 4. Nutrition Agent Evals
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eval_nutrition(db_session: AsyncSession):
    await seed_eval_db_fixtures(db_session)
    cases = load_yaml_cases("nutrition")

    for case in cases:
        user_id = str(uuid.uuid4())
        session_data = case.get("session") or {}
        email = f"nutr_eval_{user_id[:8]}@gympro.test"
        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Nutr', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Nutrition Eval User",
            age_years=session_data.get("age_years", 25),
            is_minor=session_data.get("is_minor", False),
            health_consent=True,
            allergies=session_data.get("allergies", []),
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("NUTRITION", ctx, case["input"])
        exp = case["expect"]

        # 1. Status Check
        if "status_in" in exp:
            assert env.status in exp["status_in"], f"Case {case['id']}: unexpected status {env.status}"

        # 2. Safety Flags Check (MINOR, EATING_DISORDER_SIGNAL, ALLERGY_CONSTRAINT at 100%)
        for f in exp.get("flags_include", []):
            assert f in env.safety.flags, f"Case {case['id']}: safety flag {f} missing"

        # 3. No numeric plan for minor / eating disorder
        if exp.get("no_numeric_calorie_plan"):
            data = env.data if isinstance(env.data, dict) else env.data.model_dump()
            assert data.get("daily_calories") is None, f"Case {case['id']}: calorie plan generated when forbidden"

        # 4. Allergen check (0 violations, fail-closed)
        if "allergen_violations" in exp:
            data = env.data if isinstance(env.data, dict) else env.data.model_dump()
            allergen_check = data.get("allergen_check") or {}
            assert len(allergen_check.get("violations", [])) == exp["allergen_violations"]


# -------------------------------------------------------------------------
# 5. Prompt Loader & Versioning Sync
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_prompt_loader_and_versions_sync(db_session: AsyncSession):
    # Verify load_prompt for all 4 agents
    agents = ["SCHEDULE", "MEMBERSHIP", "WELLNESS", "NUTRITION"]
    for ag in agents:
        prompt = load_prompt(ag)
        assert prompt.agent == ag
        assert prompt.version == "1.0.0"
        assert len(prompt.sha256) == 64
        assert "[GYMPRO_BASE_POLICY v1.0.0]" in prompt.text
        assert f"[AGENT: {ag} v1.0.0]" in prompt.text
        if ag == "SCHEDULE":
            assert "2026-10-16T18:05:00+05:30" in prompt.text

        # Test sync_prompt_versions writing to DB table
        await sync_prompt_versions(db_session, ag, prompt.version, prompt.sha256, eval_score=100.0)

    # Verify rows in DB prompt_versions
    await set_rls_system(db_session)
    res = await db_session.execute(text("SELECT agent, version, sha256, eval_score FROM prompt_versions ORDER BY agent"))
    rows = res.mappings().all()
    assert len(rows) == 4
    for r in rows:
        assert r["agent"] in agents
        assert r["version"] == "1.0.0"
        assert float(r["eval_score"]) == 100.0


# -------------------------------------------------------------------------
# 6. Runner Token Budget & Safe Fallback
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_safe_fallback_on_budget_exhaustion(db_session: AsyncSession):
    user_id = str(uuid.uuid4())
    session = SessionContext(
        user_id=user_id,
        role="USER",
        account_status="ACTIVE",
        plan="GOLD",
        account_email="fallback_test@gympro.test",
        full_name="Fallback Test User",
        health_consent=True,
    )
    ctx = RunContext(session=session, db=db_session)
    # Pre-exhaust token budget
    ctx.tokens_used = 25_000

    env = await run_agent("SCHEDULE", ctx, "Book yoga")
    assert env.status == "ERROR"
    assert "issue while processing your request" in env.user_message
