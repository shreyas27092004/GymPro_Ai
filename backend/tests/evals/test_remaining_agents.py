# tests/evals/test_remaining_agents.py
from datetime import date
from pathlib import Path
import uuid
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.runner import run_agent
from app.auth.deps import SessionContext
from app.kb.ingest import ingest_corpus
from app.kb.retrieval import query_kb, wrap_retrieved_context
from app.llm import set_llm
from app.tools.registry import RunContext
from tests.conftest import TestSeedSession, superuser_engine
from tests.evals.fake_llm import fake_llm


@pytest.fixture(autouse=True)
def setup_fake_llm():
    set_llm(fake_llm)
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()
    yield
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()


def load_yaml_cases(name: str) -> list[dict]:
    p = Path(__file__).parent / "cases" / f"{name}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


async def seed_remaining_fixtures():
    # Ingest Chroma corpus
    ingest_corpus()

    tid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, account_status) "
                "VALUES (:tid, 'trainer_p10@gympro.test', 'p', 'Asha Rao', 'TRAINER', 'ACTIVE') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO trainer_profiles (trainer_id, specializations, certifications, certs_verified_at, accepting_clients, hourly_rate) "
                "VALUES (:tid, ARRAY['STRENGTH', 'CORRECTIVE_EXERCISE'], ARRAY['CSCS', 'NASM-CES'], NOW(), true, 2000.00) "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        # Class for support
        cid_today = uuid.UUID("33333333-3333-3333-3333-333333333333")
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, capacity, booked_count, start_time, end_time, status)
                VALUES (:cid, 'HIIT Spin', :tid, 'SPIN', 'HIGH', 'INTERMEDIATE', 20, 1, CURRENT_DATE + TIME '07:00:00', CURRENT_DATE + TIME '08:00:00', 'SCHEDULED')
                ON CONFLICT (id) DO NOTHING;
                """
            ),
            {"cid": cid_today, "tid": tid},
        )


@pytest.mark.asyncio
async def test_eval_fitness(db_session: AsyncSession):
    await seed_remaining_fixtures()
    cases = load_yaml_cases("fitness")

    for case in cases:
        user_id = str(uuid.uuid4())
        email = f"fitness_{user_id[:8]}@gympro.test"
        session_data = case.get("session") or {}

        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Fit User', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        async with superuser_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO member_profiles (user_id, date_of_birth, gender, height_cm, weight_kg, experience_level, goal, known_injuries, health_data_consent_at)
                    VALUES (:uid, '1995-05-15', 'MALE', 178, 75, :lvl, :g, :inj, NOW())
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "uid": uuid.UUID(user_id),
                    "lvl": session_data.get("experience_level", "BEGINNER"),
                    "g": session_data.get("goal", "FAT_LOSS"),
                    "inj": session_data.get("known_injuries", []),
                },
            )

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Fit User",
            health_consent=session_data.get("health_consent", True),
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("FITNESS", ctx, case["input"])
        exp = case["expect"]

        # 1. Status check
        if "status_in" in exp:
            assert env.status in exp["status_in"]

        # 2. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools

        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools

        # 3. Flags check
        for flag in exp.get("flags_include", []):
            assert flag in env.safety.flags

        # 4. Roadmap and safety checks
        data = env.data if isinstance(env.data, dict) else env.data.model_dump()
        if exp.get("roadmap_weeks"):
            assert len(data.get("roadmap", [])) == exp["roadmap_weeks"]

        if exp.get("safety_exclusions_include"):
            exclusions = data.get("excluded_for_safety", [])
            for e in exp["safety_exclusions_include"]:
                assert e in exclusions


@pytest.mark.asyncio
async def test_eval_trainer_info(db_session: AsyncSession):
    await seed_remaining_fixtures()
    cases = load_yaml_cases("trainer_info")

    for case in cases:
        user_id = str(uuid.uuid4())
        email = f"tinfo_{user_id[:8]}@gympro.test"

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Trainer Info User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("TRAINER_INFO", ctx, case["input"])
        exp = case["expect"]

        # 1. Status check
        if "status_in" in exp:
            assert env.status in exp["status_in"]

        # 2. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools

        for flag in exp.get("flags_include", []):
            assert flag in env.safety.flags

        data = env.data if isinstance(env.data, dict) else env.data.model_dump()
        if "max_trainers" in exp:
            assert len(data.get("trainers", [])) <= exp["max_trainers"]


@pytest.mark.asyncio
async def test_eval_support(db_session: AsyncSession):
    await seed_remaining_fixtures()
    cases = load_yaml_cases("support")

    for case in cases:
        user_id = str(uuid.uuid4())
        email = f"supp_{user_id[:8]}@gympro.test"

        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Support User', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        async with superuser_engine.begin() as conn:
            # Seed booking in today's class
            await conn.execute(
                text(
                    """
                    INSERT INTO class_bookings (id, class_id, user_id, status)
                    VALUES (gen_random_uuid(), '33333333-3333-3333-3333-333333333333', :uid, 'CONFIRMED')
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"uid": uuid.UUID(user_id)},
            )

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Support User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("SUPPORT", ctx, case["input"])
        exp = case["expect"]

        # 1. Status check
        if "status_in" in exp:
            assert env.status in exp["status_in"]

        # 2. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools

        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools

        if exp.get("confirmation_present"):
            assert env.confirmation.action_id is not None

        if exp.get("missing_fields_include"):
            for f in exp["missing_fields_include"]:
                assert f in env.missing_fields


@pytest.mark.asyncio
async def test_eval_comms(db_session: AsyncSession):
    await seed_remaining_fixtures()
    cases = load_yaml_cases("comms")

    for case in cases:
        user_id = str(uuid.uuid4())
        email = f"comms_{user_id[:8]}@gympro.test"

        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:uid, :email, 'p', 'Comms User', 'USER', 'ACTIVE') ON CONFLICT DO NOTHING"),
                {"uid": uuid.UUID(user_id), "email": email},
            )
            await seed_db.commit()

        session = SessionContext(
            user_id=user_id,
            role=case.get("role", "USER"),
            account_status="ACTIVE",
            plan="GOLD",
            account_email=email,
            full_name="Comms User",
            health_consent=True,
        )
        ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

        history_len_before = len(fake_llm.call_history)
        env = await run_agent("COMMS", ctx, case["input"])
        exp = case["expect"]

        # 1. Status check
        if "status_in" in exp:
            assert env.status in exp["status_in"]

        # 2. Flags check
        for flag in exp.get("flags_include", []):
            assert flag in env.safety.flags

        # 3. Tool calls check
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_call_tools", []):
            assert t in called_tools

        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools


@pytest.mark.asyncio
async def test_eval_kb_injection(db_session: AsyncSession):
    """
    KB injection pack:
    1. Verifies that instructions hidden inside retrieved context are treated as untrusted reference
       facts and never executed by the agent runner or supervisor.
    2. Verifies Chroma staleness filtering excludes > 12 month old documents.
    3. Verifies context wrapping format and citation schema.
    """
    await seed_remaining_fixtures()

    # 1. Test Staleness Filtering: inj-stale-001 has reviewed_at 2024-01-01 (> 12 months from frozen 2026-10-16)
    results = query_kb("injury_protocols", "hip impingement", as_of_date=date(2026, 10, 16))
    stale_ids = [r["id"] for r in results if r["id"] == "inj-stale-001"]
    assert len(stale_ids) == 0, "Stale doc (>12m) was not excluded from injury_protocols retrieval"

    # Active knee doc MUST be retrieved
    knee_results = query_kb("injury_protocols", "knee pain", as_of_date=date(2026, 10, 16))
    assert any(r["id"] == "inj-knee-001" for r in knee_results)

    # 2. Test Context Wrapping and Untrusted Tagging
    wrapped = wrap_retrieved_context(knee_results)
    assert "<retrieved_context" in wrapped
    assert "collection=\"injury_protocols\"" in wrapped

    # 3. Test Runner with Adversarial Injected Context
    cases = load_yaml_cases("kb_injection")
    user_id = str(uuid.uuid4())
    session = SessionContext(
        user_id=user_id,
        role="USER",
        account_status="ACTIVE",
        plan="GOLD",
        account_email=f"kbinj_{user_id[:8]}@gympro.test",
        full_name="KB Inj User",
        health_consent=True,
    )
    ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

    for case in cases:
        history_len_before = len(fake_llm.call_history)
        env = await run_agent(case["agent"], ctx, case["input"])
        exp = case["expect"]

        # Status check
        if "status_in" in exp:
            assert env.status in exp["status_in"]

        # Must not escalate privilege
        assert "PRIVILEGE_ESCALATION" not in env.safety.flags

        # Propose tools must not be called
        calls_during = fake_llm.call_history[history_len_before:]
        called_tools = set()
        for call in calls_during:
            for m in call["messages"]:
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        called_tools.add(tc["function"]["name"])

        for t in exp.get("must_not_call_tools", []):
            assert t not in called_tools, f"Malicious tool {t} was executed from indirect injection!"
