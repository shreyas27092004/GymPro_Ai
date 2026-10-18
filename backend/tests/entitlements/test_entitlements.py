# tests/entitlements/test_entitlements.py
from datetime import date, datetime, timedelta
from decimal import Decimal
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.security import create_access_token, hash_password, phone_hash
from app.db import set_rls_system
from app.entitlements.intake import (
    IntakeUpdate,
    get_intake_history,
    get_member_profile,
    save_member_profile,
    set_health_consent,
)
from app.entitlements.membership import (
    PriceDiffQuote,
    execute_upgrade,
    get_active_membership,
    price_diff,
)
from app.entitlements.resolver import Entitlement, entitlements
from app.entitlements.trial import consume_trial_class, get_active_trial, start_trial
from tests.conftest import TestSeedSession, superuser_engine


async def create_active_user(
    db: AsyncSession,
    email: str,
    phone: str | None = None,
    role: str = "USER",
) -> dict:
    """Helper to create an active user and return user info with bearer token."""
    uid = uuid.uuid4()
    p_hash = phone_hash(phone) if phone else None
    await db.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status, phone, phone_hash, email_verified_at)
            VALUES (:uid, :email, :pw, 'Test User', :role, 'ACTIVE', :phone, :ph, NOW())
            """
        ),
        {
            "uid": uid,
            "email": email,
            "pw": hash_password("validpassword123"),
            "role": role,
            "phone": phone,
            "ph": p_hash,
        },
    )
    await db.commit()
    token = create_access_token(str(uid), token_version=0)
    return {"id": uid, "email": email, "phone": phone, "phone_hash": p_hash, "token": token}


# -------------------------------------------------------------------------
# 1. Trial Once Per Email and Per Phone Hash
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trial_once_per_email_and_phone_hash(client: AsyncClient, db_session: AsyncSession):
    """Verify free trial is granted once per user and strictly once per phone hash."""
    phone = "+919876500001"
    ph = phone_hash(phone)

    # 1. User 1 registers and verifies -> receives trial grant
    u1 = await create_active_user(db_session, "user1@gympro.test", phone=phone)
    grant1 = await start_trial(db_session, u1["id"], phone_hash=ph)
    await db_session.commit()

    assert grant1 is not None
    assert grant1["classes_total"] == 3
    assert grant1["classes_used"] == 0

    # User 1 calling start_trial again returns existing grant without duplication
    grant1_again = await start_trial(db_session, u1["id"], phone_hash=ph)
    assert grant1_again["id"] == grant1["id"]

    # 2. Attempting to create user with the exact same phone violates uq_users_phone_hash
    with pytest.raises(Exception):
        await create_active_user(db_session, "dup_phone@gympro.test", phone=phone)
    await db_session.rollback()

    # 3. User 2 registers without a phone, then tries to claim trial with User 1's phone_hash
    u2 = await create_active_user(db_session, "user2@gympro.test", phone=None)
    grant2 = await start_trial(db_session, u2["id"], phone_hash=ph)
    await db_session.commit()

    # User 2 cannot receive a trial because phone_hash already claimed one
    assert grant2 is None

    # API /api/me/trial reflects this
    res1 = await client.get("/api/me/trial", headers={"Authorization": f"Bearer {u1['token']}"})
    assert res1.status_code == 200
    assert res1.json()["active"] is True
    assert res1.json()["trial"]["classes_total"] == 3

    res2 = await client.get("/api/me/trial", headers={"Authorization": f"Bearer {u2['token']}"})
    assert res2.status_code == 200
    assert res2.json()["active"] is False
    assert res2.json()["trial"] is None


# -------------------------------------------------------------------------
# 2. Trial Classes Only & Trial Expiry/Exhaustion
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trial_classes_only(db_session: AsyncSession):
    """Verify trial only permits classes marked trial_eligible, and locks out when exhausted/expired."""
    u = await create_active_user(db_session, "trial_rider@gympro.test", phone="+919876500002")
    await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])
    await db_session.commit()

    class_eligible = {"id": uuid.uuid4(), "title": "Beginner Yoga", "trial_eligible": True, "allowed_plans": None}
    class_ineligible = {"id": uuid.uuid4(), "title": "Elite PT Clinic", "trial_eligible": False, "allowed_plans": None}

    # 1. Trial eligible class -> can_book = True
    ent1 = await entitlements(db_session, u["id"], cls=class_eligible)
    assert ent1.can_book is True
    assert ent1.source == "TRIAL"
    assert ent1.remaining == 3
    assert ent1.reason is None

    # 2. Non-trial eligible class -> can_book = False, reason = CLASS_NOT_TRIAL_ELIGIBLE
    ent2 = await entitlements(db_session, u["id"], cls=class_ineligible)
    assert ent2.can_book is False
    assert ent2.source == "TRIAL"
    assert ent2.reason == "CLASS_NOT_TRIAL_ELIGIBLE"
    assert ent2.remaining == 3

    # 3. Consume all 3 trial classes
    c1 = await consume_trial_class(db_session, u["id"])
    assert c1["classes_used"] == 1
    c2 = await consume_trial_class(db_session, u["id"])
    assert c2["classes_used"] == 2
    c3 = await consume_trial_class(db_session, u["id"])
    assert c3["classes_used"] == 3
    await db_session.commit()

    # 4th consume fails
    c4 = await consume_trial_class(db_session, u["id"])
    assert c4 is None

    # Exhausted trial -> can_book = False, NO_PLAN_CHOOSE_ONE
    ent3 = await entitlements(db_session, u["id"], cls=class_eligible)
    assert ent3.can_book is False
    assert ent3.source == "NONE"
    assert ent3.reason == "NO_PLAN_CHOOSE_ONE"
    assert ent3.remaining == 0

    # 4. Stale expired trial (>14 days)
    u_exp = await create_active_user(db_session, "trial_exp@gympro.test", phone="+919876500003")
    await set_rls_system(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO trial_grants (user_id, phone_hash, classes_total, classes_used, starts_at, expires_at)
            VALUES (:uid, :ph, 3, 0, NOW() - INTERVAL '15 days', NOW() - INTERVAL '1 day')
            """
        ),
        {"uid": u_exp["id"], "ph": u_exp["phone_hash"]},
    )
    await db_session.commit()

    active_t = await get_active_trial(db_session, u_exp["id"])
    assert active_t is None
    ent_exp = await entitlements(db_session, u_exp["id"], cls=class_eligible)
    assert ent_exp.can_book is False
    assert ent_exp.reason == "NO_PLAN_CHOOSE_ONE"


# -------------------------------------------------------------------------
# 3. Entitlement Order: Active Membership Overrides Trial
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_entitlement_order_membership_first(db_session: AsyncSession):
    """Verify active membership credits are evaluated first, even when user also has trial grant."""
    u = await create_active_user(db_session, "dual_holder@gympro.test", phone="+919876500004")
    # Grant trial
    await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])

    # Grant active SILVER membership (4 classes/month)
    m_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
            VALUES (:id, :uid, 'SILVER', 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days')
            """
        ),
        {"id": m_id, "uid": u["id"]},
    )
    await db_session.commit()

    cid = uuid.uuid4()
    tid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status)
                VALUES (:tid, 'coach_ent@gympro.test', 'pw', 'Coach', 'TRAINER', 'ACTIVE')
                """
            ),
            {"tid": tid},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO trainer_profiles (trainer_id, bio)
                VALUES (:tid, 'Lead Coach')
                """
            ),
            {"tid": tid},
        )
        start_c = datetime.now() + timedelta(days=10)
        end_c = start_c + timedelta(hours=1)
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, trial_eligible, capacity, start_time, end_time, status)
                VALUES (:cid, 'Spin', :tid, 'SPIN', 'HIGH', 'BEGINNER', TRUE, 20, :start, :end, 'SCHEDULED')
                """
            ),
            {"cid": cid, "tid": tid, "start": start_c, "end": end_c},
        )

    cls_obj = {"id": cid, "title": "Spin", "trial_eligible": True, "allowed_plans": None}

    # Membership first -> source is MEMBERSHIP, remaining = 4
    ent = await entitlements(db_session, u["id"], cls=cls_obj)
    assert ent.can_book is True
    assert ent.source == "MEMBERSHIP"
    assert ent.remaining == 4

    # Class restricted to GOLD & PLATINUM -> PLAN_NOT_ALLOWED
    gold_cls = {"id": uuid.uuid4(), "title": "VIP Masterclass", "trial_eligible": True, "allowed_plans": ["GOLD", "PLATINUM"]}
    ent_gold = await entitlements(db_session, u["id"], cls=gold_cls)
    assert ent_gold.can_book is False
    assert ent_gold.reason == "PLAN_NOT_ALLOWED"
    assert ent_gold.source == "MEMBERSHIP"

    # Use up all 4 credits
    await set_rls_system(db_session)
    for i in range(4):
        c_i = uuid.uuid4()
        c_start = datetime.now() + timedelta(days=20 + i)
        c_end = c_start + timedelta(hours=1)
        async with superuser_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, trial_eligible, capacity, start_time, end_time, status)
                    VALUES (:cid, :title, :tid, 'SPIN', 'HIGH', 'BEGINNER', TRUE, 20, :start, :end, 'SCHEDULED')
                    """
                ),
                {"cid": c_i, "title": f"Spin {i}", "tid": tid, "start": c_start, "end": c_end},
            )
        await db_session.execute(
            text(
                """
                INSERT INTO class_bookings (user_id, class_id, status)
                VALUES (:uid, :cid, 'CONFIRMED')
                """
            ),
            {"uid": u["id"], "cid": c_i},
        )
    await db_session.commit()

    # Out of credits -> NO_CREDITS
    ent_spent = await entitlements(db_session, u["id"], cls=cls_obj)
    assert ent_spent.can_book is False
    assert ent_spent.reason == "NO_CREDITS"
    assert ent_spent.remaining == 0


# -------------------------------------------------------------------------
# 4. Membership Upgrade Replaces Old Membership
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upgrade_replaces_old_membership(client: AsyncClient, db_session: AsyncSession):
    """Verify upgrade replaces old membership, links replaced_by, and enforces unique active index."""
    u = await create_active_user(db_session, "upgrader@gympro.test")

    # 1. User starts on GOLD
    gold_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
            VALUES (:id, :uid, 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, CURRENT_DATE - INTERVAL '10 days', CURRENT_DATE + INTERVAL '20 days')
            """
        ),
        {"id": gold_id, "uid": u["id"]},
    )
    await db_session.commit()

    # 2. Upgrade to PLATINUM
    res = await client.post(
        "/api/me/membership/upgrade",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"to_plan": "PLATINUM", "cycle": "MONTHLY"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["plan"] == "PLATINUM"
    plat_id = uuid.UUID(data["membership_id"])

    # 3. Check database state
    # Old membership: status = REPLACED, replaced_by = plat_id
    old_res = await db_session.execute(
        text("SELECT status, replaced_by, end_date FROM memberships WHERE id = :id"),
        {"id": gold_id},
    )
    old_row = old_res.mappings().one()
    assert old_row["status"] == "REPLACED"
    assert old_row["replaced_by"] == plat_id

    # New membership: status = ACTIVE, plan_code = PLATINUM
    new_res = await db_session.execute(
        text("SELECT status, plan_code, price_paid, end_date FROM memberships WHERE id = :id"),
        {"id": plat_id},
    )
    new_row = new_res.mappings().one()
    assert new_row["status"] == "ACTIVE"
    assert new_row["plan_code"] == "PLATINUM"

    # Exactly ONE active membership exists
    count_res = await db_session.execute(
        text("SELECT count(*) FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": u["id"]},
    )
    assert count_res.scalar_one() == 1

    # 4. Attempting to downgrade (PLATINUM to SILVER) is rejected
    down_res = await client.post(
        "/api/me/membership/upgrade",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"to_plan": "SILVER", "cycle": "MONTHLY"},
    )
    assert down_res.status_code == 400
    assert down_res.json()["detail"]["error"] == "DOWNGRADE_NOT_ALLOWED"

    # 5. Attempting to select same plan (PLATINUM to PLATINUM) is rejected
    same_res = await client.post(
        "/api/me/membership/upgrade",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"to_plan": "PLATINUM", "cycle": "MONTHLY"},
    )
    assert same_res.status_code == 400
    assert same_res.json()["detail"]["error"] == "ALREADY_ON_PLAN"


# -------------------------------------------------------------------------
# 5. Proration Math Calculations
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_proration_math(db_session: AsyncSession):
    """Verify price_diff proration formula: delta * remaining_days / total_days with 1.00 min charge."""
    u = await create_active_user(db_session, "proration_user@gympro.test")

    # Start date: 2026-10-01, End date: 2026-11-01 (31 days)
    # As of: 2026-10-16 (16 days remaining)
    start_d = date(2026, 10, 1)
    end_d = date(2026, 11, 1)
    as_of = date(2026, 10, 16)

    m_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
            VALUES (:id, :uid, 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, :st, :et)
            """
        ),
        {"id": m_id, "uid": u["id"], "st": start_d, "et": end_d},
    )
    await db_session.commit()

    # GOLD (1999) -> PLATINUM (3499)
    # Delta = 1500.00
    # Prorated = 1500 * (16 / 31) = 774.19
    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY", as_of_date=as_of)
    assert quote.from_plan == "GOLD"
    assert quote.to_plan == "PLATINUM"
    assert quote.delta_per_cycle == Decimal("1500.00")
    assert quote.prorated_today == Decimal("774.19")
    assert quote.next_billing_date == end_d

    # Minimum charge: If remaining days is tiny and delta is small, clamp to 1.00
    # Create artificial 1 day remaining with small delta
    end_tomorrow = as_of + timedelta(days=1)
    start_long_ago = as_of - timedelta(days=999)
    await db_session.execute(
        text("UPDATE memberships SET start_date = :st, end_date = :et WHERE id = :id"),
        {"st": start_long_ago, "et": end_tomorrow, "id": m_id},
    )
    await db_session.commit()

    # 1500 * (1 / 1000) = 1.50 -> still above 1
    # Now set start to 10,000 days ago so 1500 * (1 / 10001) = 0.15 -> clamps to 1.00
    start_huge = as_of - timedelta(days=10000)
    await db_session.execute(
        text("UPDATE memberships SET start_date = :st, end_date = :et WHERE id = :id"),
        {"st": start_huge, "et": end_tomorrow, "id": m_id},
    )
    await db_session.commit()

    quote_min = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY", as_of_date=as_of)
    assert quote_min.prorated_today == Decimal("1.00")


# -------------------------------------------------------------------------
# 6. Consent Gating, Intake History & Under-18 Restrictions
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_consent_gating_and_intake_versions(client: AsyncClient, db_session: AsyncSession):
    """Verify health data consent grant/revoke, intake snapshotting in member_intake_versions, and age checks."""
    u = await create_active_user(db_session, "intake_user@gympro.test")
    headers = {"Authorization": f"Bearer {u['token']}"}

    # 1. Grant health-data consent
    c_res = await client.post("/api/me/consent", headers=headers)
    assert c_res.status_code == 200
    assert c_res.json()["consented"] is True
    assert c_res.json()["health_data_consent_at"] is not None

    # Verify profile row has consent timestamp
    prof = await get_member_profile(db_session, u["id"])
    assert prof["health_data_consent_at"] is not None

    # 2. Revoke health-data consent
    d_res = await client.delete("/api/me/consent", headers=headers)
    assert d_res.status_code == 200
    assert d_res.json()["consented"] is False
    assert d_res.json()["health_data_consent_at"] is None

    prof_rev = await get_member_profile(db_session, u["id"])
    assert prof_rev["health_data_consent_at"] is None

    # 3. Under-18 calorie restriction refusal
    # Born 16 years ago
    underage_dob = (date.today() - timedelta(days=16 * 365 + 4)).isoformat()
    bad_intake = {
        "date_of_birth": underage_dob,
        "height_cm": 175.0,
        "weight_kg": 72.0,
        "goal": "FAT_LOSS",
        "allergies": ["PEANUT"],
        "known_injuries": ["KNEE"],
    }
    bad_res = await client.put("/api/me/intake", headers=headers, json=bad_intake)
    assert bad_res.status_code == 400
    assert bad_res.json()["detail"]["error"] == "UNDERAGE_CALORIE_RESTRICTION"

    # Under-18 with MAINTENANCE goal succeeds
    bad_intake["goal"] = "MAINTENANCE"
    ok_res = await client.put("/api/me/intake", headers=headers, json=bad_intake)
    assert ok_res.status_code == 200
    assert ok_res.json()["goal"] == "MAINTENANCE"

    # 4. Adult (age 25) with FAT_LOSS goal succeeds
    adult_dob = (date.today() - timedelta(days=25 * 365 + 6)).isoformat()
    adult_intake = {
        "date_of_birth": adult_dob,
        "height_cm": 180.0,
        "weight_kg": 85.0,
        "goal": "FAT_LOSS",
        "allergies": ["DAIRY"],
        "known_injuries": ["LOWER_BACK"],
    }
    adult_res = await client.put("/api/me/intake", headers=headers, json=adult_intake)
    assert adult_res.status_code == 200
    assert adult_res.json()["goal"] == "FAT_LOSS"

    # 5. Verify append-only version history in member_intake_versions (via trigger)
    history = await get_intake_history(db_session, u["id"])
    assert len(history) >= 2

    # Check /api/me/memory endpoint
    mem_res = await client.get("/api/me/memory", headers=headers)
    assert mem_res.status_code == 200
    mem_list = mem_res.json()
    assert len(mem_list) >= 2
    latest_snapshot = mem_list[0]["snapshot"]
    assert latest_snapshot["goal"] == "FAT_LOSS"
    assert latest_snapshot["allergies"] == ["DAIRY"]
