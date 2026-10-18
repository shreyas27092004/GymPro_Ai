# tests/executor/test_executor.py
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.security import create_access_token, hash_password, phone_hash
from app.db import set_rls_system
from app.entitlements.membership import price_diff
from app.entitlements.trial import start_trial
from tests.conftest import TestSeedSession, superuser_engine


async def create_user(
    db: AsyncSession,
    email: str,
    phone: str = "+919876543210",
    role: str = "USER",
) -> dict:
    uid = uuid.uuid4()
    ph = phone_hash(phone)
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

    token = create_access_token(str(uid), token_version=0)
    return {"id": uid, "email": email, "phone_hash": ph, "token": token}


async def seed_trainer_and_classes(count: int = 1, capacity: int = 20, trial_eligible: bool = True, allowed_plans: list[str] | None = None) -> tuple[uuid.UUID, list[uuid.UUID]]:
    tid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status)
                VALUES (:tid, :email, 'pw', 'Coach', 'TRAINER', 'ACTIVE')
                """
            ),
            {"tid": tid, "email": f"trainer_{uuid.uuid4().hex[:8]}@gympro.test"},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO trainer_profiles (trainer_id, bio) VALUES (:tid, 'Coach Bio')"),
            {"tid": tid},
        )
        class_ids = []
        for i in range(count):
            cid = uuid.uuid4()
            start_t = datetime.now(timezone.utc) + timedelta(days=5 + i, hours=i)
            end_t = start_t + timedelta(hours=1)
            await conn.execute(
                text(
                    """
                    INSERT INTO fitness_classes (
                        id, title, trainer_id, category, impact, min_level, trial_eligible,
                        capacity, booked_count, start_time, end_time, status, allowed_plans
                    ) VALUES (
                        :cid, :title, :tid, 'SPIN', 'HIGH', 'BEGINNER', :trial_el,
                        :cap, 0, :st, :et, 'SCHEDULED', :plans
                    )
                    """
                ),
                {
                    "cid": cid,
                    "title": f"Spin Class {i}",
                    "tid": tid,
                    "trial_el": trial_eligible,
                    "cap": capacity,
                    "st": start_t,
                    "et": end_t,
                    "plans": allowed_plans or [],
                },
            )
            class_ids.append(cid)
    return tid, class_ids


# -------------------------------------------------------------------------
# 1. Concurrency: 8 Concurrent Confirms for Last Spot Give Exactly One Booking
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_confirms_last_spot_exactly_one_booking(client: AsyncClient, db_session: AsyncSession):
    """
    8 concurrent confirms for the last spot give exactly one booking.
    Row lock FOR UPDATE on fitness_classes serializes capacity checks.
    """
    # 1. Seed class with capacity 5 and booked_count 4 (1 spot left)
    tid, class_ids = await seed_trainer_and_classes(count=1, capacity=5)
    class_id = class_ids[0]

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("UPDATE fitness_classes SET booked_count = 4 WHERE id = :cid"),
            {"cid": class_id},
        )

    # 2. Seed 8 distinct active users and grant trials
    users = []
    actions = []
    for i in range(8):
        u = await create_user(db_session, f"last_spot_{i}@gympro.test", phone=f"+91981110000{i}")
        await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])
        aid = uuid.uuid4()
        async with superuser_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                    VALUES (:aid, :uid, 'BOOK_CLASS', CAST(:payload AS jsonb), 'Book last spot', 'PENDING', NOW() + INTERVAL '15 minutes')
                    """
                ),
                {
                    "aid": aid,
                    "uid": u["id"],
                    "payload": json.dumps({"class_id": str(class_id)}),
                },
            )
        users.append(u)
        actions.append(aid)
    await db_session.commit()

    # 3. Trigger 8 concurrent confirms using asyncio.gather
    async def confirm_for_user(u: dict, aid: uuid.UUID):
        return await client.post(
            f"/api/actions/{aid}/confirm",
            headers={"Authorization": f"Bearer {u['token']}"},
        )

    tasks = [confirm_for_user(users[i], actions[i]) for i in range(8)]
    responses = await asyncio.gather(*tasks)

    # 4. Verify exactly 1 succeeded, and 7 failed with CLASS_FULL
    success_count = 0
    full_count = 0
    for r in responses:
        assert r.status_code == 200
        data = r.json()
        if data.get("ok") is True:
            success_count += 1
            assert "booking_id" in data
        else:
            full_count += 1
            assert data.get("error") == "CLASS_FULL"
            assert data.get("hint") == "offer_waitlist"

    assert success_count == 1
    assert full_count == 7

    # 5. Check DB class booked_count is capped at 5
    chk = await db_session.execute(
        text("SELECT booked_count, capacity FROM fitness_classes WHERE id = :cid"),
        {"cid": class_id},
    )
    row = chk.mappings().one()
    assert row["booked_count"] == 5
    assert row["capacity"] == 5

    # 6. Check exactly 1 new booking in class_bookings for these users
    await set_rls_system(db_session)
    b_chk = await db_session.execute(
        text("SELECT count(*) FROM class_bookings WHERE class_id = :cid AND status = 'CONFIRMED'"),
        {"cid": class_id},
    )
    # 4 prior bookings were simulated on booked_count; only 1 real booking inserted
    assert b_chk.scalar_one() == 1


# -------------------------------------------------------------------------
# 2. Concurrency: Same-User Overlap Race Gives One Success
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_same_user_overlap_race_gives_one_success(client: AsyncClient, db_session: AsyncSession):
    """
    Same-user concurrent booking attempts for overlapping class times.
    Advisory lock pg_advisory_xact_lock(hashtextextended(:u, 0)) serializes booking
    transactions for the user, allowing the second to detect CONFLICT.
    """
    u = await create_user(db_session, "overlap_user@gympro.test", phone="+919822200000")
    await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])
    await db_session.commit()

    # Create 2 overlapping classes at the exact same start_time
    tid = uuid.uuid4()
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:tid, 'overlap_coach@gympro.test', 'pw', 'Coach', 'TRAINER', 'ACTIVE')"),
            {"tid": tid},
        )
        await seed_db.commit()

    overlap_start = datetime.now(timezone.utc) + timedelta(days=10)
    overlap_end = overlap_start + timedelta(hours=1)
    async with superuser_engine.begin() as conn:
        await conn.execute(text("INSERT INTO trainer_profiles (trainer_id, bio) VALUES (:tid, 'Coach Bio')"), {"tid": tid})
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, trial_eligible, capacity, booked_count, start_time, end_time, status)
                VALUES (:cid, 'Spin A', :tid, 'SPIN', 'HIGH', 'BEGINNER', TRUE, 20, 0, :st, :et, 'SCHEDULED')
                """
            ),
            {"cid": c1, "tid": tid, "st": overlap_start, "et": overlap_end},
        )

    # For c2, use another trainer so exclusion constraint on trainer overlap doesn't trigger
    tid2 = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text("INSERT INTO users (id, email, password_hash, full_name, role, account_status) VALUES (:tid, 'overlap_coach2@gympro.test', 'pw', 'Coach 2', 'TRAINER', 'ACTIVE')"),
            {"tid": tid2},
        )
        await seed_db.commit()

    async with superuser_engine.begin() as conn:
        await conn.execute(text("INSERT INTO trainer_profiles (trainer_id, bio) VALUES (:tid, 'Coach Bio')"), {"tid": tid2})
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (id, title, trainer_id, category, impact, min_level, trial_eligible, capacity, booked_count, start_time, end_time, status)
                VALUES (:cid, 'Yoga B', :tid, 'YOGA', 'LOW', 'BEGINNER', TRUE, 20, 0, :st, :et, 'SCHEDULED')
                """
            ),
            {"cid": c2, "tid": tid2, "st": overlap_start, "et": overlap_end},
        )

    # Insert 2 pending actions for this user
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, 'BOOK_CLASS', CAST(:p1 AS jsonb), 'Book Spin', 'PENDING', NOW() + INTERVAL '15 min'),
                       (:a2, :uid, 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Book Yoga', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a1": a1,
                "a2": a2,
                "uid": u["id"],
                "p1": json.dumps({"class_id": str(c1)}),
                "p2": json.dumps({"class_id": str(c2)}),
            },
        )

    # Concurrently confirm both actions for the same user
    task1 = client.post(f"/api/actions/{a1}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    task2 = client.post(f"/api/actions/{a2}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    r1, r2 = await asyncio.gather(task1, task2)

    assert r1.status_code == 200
    assert r2.status_code == 200
    results = [r1.json(), r2.json()]

    oks = [res for res in results if res.get("ok") is True]
    conflicts = [res for res in results if res.get("error") == "CONFLICT"]

    assert len(oks) == 1
    assert len(conflicts) == 1


# -------------------------------------------------------------------------
# 3. Double-Confirm Replay is Safe (Idempotency)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_double_confirm_replay_is_safe(client: AsyncClient, db_session: AsyncSession):
    """
    Replaying confirmation on an already EXECUTED action or bundle returns
    the cached result without re-executing or creating duplicate records.
    """
    u = await create_user(db_session, "double_confirm@gympro.test", phone="+919833300000")
    await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])
    await db_session.commit()

    _, class_ids = await seed_trainer_and_classes(count=1, capacity=20)
    cid = class_ids[0]

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'BOOK_CLASS', CAST(:payload AS jsonb), 'Book single', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "payload": json.dumps({"class_id": str(cid)})},
        )

    # First confirm
    r1 = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["ok"] is True
    booking_id = d1["booking_id"]

    # Second confirm (replay)
    r2 = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2 == d1

    # Check database: exactly one booking row created
    await set_rls_system(db_session)
    chk = await db_session.execute(
        text("SELECT count(*) FROM class_bookings WHERE user_id = :uid AND class_id = :cid"),
        {"uid": u["id"], "cid": cid},
    )
    assert chk.scalar_one() == 1


# -------------------------------------------------------------------------
# 4. Bundle Order: Topological Step Execution with Membership Handoff
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bundle_order_and_projected_entitlement(client: AsyncClient, db_session: AsyncSession):
    """
    Bundle executes in step_no order.
    Step 1 upgrades membership from SILVER to PLATINUM.
    Step 2 books a class requiring PLATINUM plan (depends_on=[1]).
    Step 2 succeeds because step 1 executed first in the database.
    """
    u = await create_user(db_session, "bundle_order@gympro.test", phone="+919844400000")

    # Give user active SILVER membership
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
                VALUES (gen_random_uuid(), :uid, 'SILVER', 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE - INTERVAL '5 days', CURRENT_DATE + INTERVAL '25 days')
                """
            ),
            {"uid": u["id"]},
        )

    # Class restricted to PLATINUM plan only
    _, class_ids = await seed_trainer_and_classes(count=1, capacity=20, allowed_plans=["PLATINUM"])
    plat_class_id = class_ids[0]

    # Calculate proration quote for upgrade to PLATINUM
    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    bundle_id = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Upgrade to Platinum and book VIP class', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bundle_id, "uid": u["id"]},
        )
        # Step 1: CHANGE_PLAN to PLATINUM
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, :bid, 1, '{}', 'CHANGE_PLAN', CAST(:p1 AS jsonb), 'Upgrade to Platinum', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a1": a1,
                "uid": u["id"],
                "bid": bundle_id,
                "p1": json.dumps({
                    "to_plan": "PLATINUM",
                    "cycle": "MONTHLY",
                    "confirmed_total": float(quote.prorated_today),
                }),
            },
        )
        # Step 2: BOOK_CLASS for Platinum class (depends_on=[1])
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Book VIP Platinum Class', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a2": a2,
                "uid": u["id"],
                "bid": bundle_id,
                "p2": json.dumps({"class_id": str(plat_class_id)}),
            },
        )

    res = await client.post(
        f"/api/bundles/{bundle_id}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "EXECUTED"
    assert len(data["steps"]) == 2
    assert data["steps"][0]["status"] == "EXECUTED"
    assert data["steps"][1]["status"] == "EXECUTED"
    assert data["steps"][1]["result"]["ok"] is True


# -------------------------------------------------------------------------
# 5. Bundle: Skip on Failed Dependency
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bundle_skip_on_failed_dependency(client: AsyncClient, db_session: AsyncSession):
    """
    When Step 1 fails, Step 2 which depends on 1 is SKIPPED with DEPENDENCY_FAILED.
    """
    u = await create_user(db_session, "skip_dep@gympro.test", phone="+919855500000")
    _, class_ids = await seed_trainer_and_classes(count=1, capacity=20)
    cid = class_ids[0]

    bundle_id = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Failing bundle', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bundle_id, "uid": u["id"]},
        )
        # Step 1: CHANGE_PLAN with deliberate price mismatch -> PRICE_CHANGED failure
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, :bid, 1, '{}', 'CHANGE_PLAN', CAST(:p1 AS jsonb), 'Upgrade with bad price', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a1": a1,
                "uid": u["id"],
                "bid": bundle_id,
                "p1": json.dumps({"to_plan": "GOLD", "cycle": "MONTHLY", "confirmed_total": 99.00}),
            },
        )
        # Step 2: Depends on step 1
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Dependent Book Class', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a2": a2,
                "uid": u["id"],
                "bid": bundle_id,
                "p2": json.dumps({"class_id": str(cid)}),
            },
        )

    res = await client.post(
        f"/api/bundles/{bundle_id}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "FAILED"
    assert data["steps"][0]["status"] == "FAILED"
    assert data["steps"][1]["status"] == "SKIPPED"
    assert data["steps"][1]["result"]["error"] == "DEPENDENCY_FAILED"


# -------------------------------------------------------------------------
# 6. Bundle: Independent Step Still Runs
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bundle_independent_step_still_runs(client: AsyncClient, db_session: AsyncSession):
    """
    Step 1 fails, Step 2 (depends on 1) is SKIPPED, but Step 3 (independent: depends_on=[])
    still runs and executes successfully. Bundle status becomes PARTIAL.
    """
    u = await create_user(db_session, "independent_step@gympro.test", phone="+919866600000")
    await start_trial(db_session, u["id"], phone_hash=u["phone_hash"])
    await db_session.commit()

    _, class_ids = await seed_trainer_and_classes(count=2, capacity=20)
    c1, c2 = class_ids[0], class_ids[1]

    bundle_id = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    a3 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Partial execution bundle', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bundle_id, "uid": u["id"]},
        )
        # Step 1: CHANGE_PLAN with bad price -> FAILS
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, :bid, 1, '{}', 'CHANGE_PLAN', CAST(:p1 AS jsonb), 'Step 1 fail', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a1": a1,
                "uid": u["id"],
                "bid": bundle_id,
                "p1": json.dumps({"to_plan": "GOLD", "cycle": "MONTHLY", "confirmed_total": 5.00}),
            },
        )
        # Step 2: Depends on step 1 -> SKIPPED
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Step 2 skip', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a2": a2, "uid": u["id"], "bid": bundle_id, "p2": json.dumps({"class_id": str(c1)})},
        )
        # Step 3: Independent (depends_on=[]) -> EXECUTED
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a3, :uid, :bid, 3, '{}', 'BOOK_CLASS', CAST(:p3 AS jsonb), 'Step 3 run', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a3": a3, "uid": u["id"], "bid": bundle_id, "p3": json.dumps({"class_id": str(c2)})},
        )

    res = await client.post(
        f"/api/bundles/{bundle_id}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PARTIAL"
    assert data["steps"][0]["status"] == "FAILED"
    assert data["steps"][1]["status"] == "SKIPPED"
    assert data["steps"][2]["status"] == "EXECUTED"
    assert data["steps"][2]["result"]["ok"] is True


# -------------------------------------------------------------------------
# 7. PRICE_CHANGED Detection on Plan Change
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_price_changed_detection(client: AsyncClient, db_session: AsyncSession):
    """
    If the confirmed price does not equal the recomputed price within 0.01,
    the action fails with PRICE_CHANGED and reports the new_total.
    """
    u = await create_user(db_session, "price_change_user@gympro.test", phone="+919877700000")

    # User has Silver membership
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
                VALUES (gen_random_uuid(), :uid, 'SILVER', 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days')
                """
            ),
            {"uid": u["id"]},
        )

    quote = await price_diff(db_session, u["id"], "GOLD", "MONTHLY")
    actual_price = quote.prorated_today

    # Submit action with stale price differing by more than 0.01
    stale_price = float(actual_price) - 50.00
    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:payload AS jsonb), 'Upgrade to Gold', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "aid": aid,
                "uid": u["id"],
                "payload": json.dumps({"to_plan": "GOLD", "cycle": "MONTHLY", "confirmed_total": stale_price}),
            },
        )

    res = await client.post(
        f"/api/actions/{aid}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["error"] == "PRICE_CHANGED"
    assert abs(data["new_total"] - float(actual_price)) < 0.01

    # Verify action in DB is FAILED
    await set_rls_system(db_session)
    chk = await db_session.execute(
        text("SELECT status FROM pending_actions WHERE id = :aid"),
        {"aid": aid},
    )
    assert chk.scalar_one() == "FAILED"


# -------------------------------------------------------------------------
# 8. Expired Action and Bundle Rejection
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_action_and_bundle_rejection(client: AsyncClient, db_session: AsyncSession):
    """
    Expired pending action or bundle returns HTTP 409 ACTION_EXPIRED.
    """
    u = await create_user(db_session, "expired_user@gympro.test", phone="+919888800000")
    _, class_ids = await seed_trainer_and_classes(count=1, capacity=20)
    cid = class_ids[0]

    # 1. Expired action
    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'BOOK_CLASS', CAST(:p AS jsonb), 'Expired action', 'PENDING', NOW() - INTERVAL '5 minutes')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"class_id": str(cid)})},
        )

    r_action = await client.post(
        f"/api/actions/{aid}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert r_action.status_code == 409
    assert r_action.json()["detail"] == "ACTION_EXPIRED"

    # Verify status updated to EXPIRED in DB
    await set_rls_system(db_session)
    chk_act = await db_session.execute(
        text("SELECT status FROM pending_actions WHERE id = :aid"),
        {"aid": aid},
    )
    assert chk_act.scalar_one() == "EXPIRED"

    # 2. Expired bundle
    bid = uuid.uuid4()
    b_aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Expired bundle', NOW() - INTERVAL '5 minutes')
                """
            ),
            {"bid": bid, "uid": u["id"]},
        )
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, :bid, 1, '{}', 'BOOK_CLASS', CAST(:p AS jsonb), 'Expired bundle step', 'PENDING', NOW() - INTERVAL '5 minutes')
                """
            ),
            {"aid": b_aid, "uid": u["id"], "bid": bid, "p": json.dumps({"class_id": str(cid)})},
        )

    r_bundle = await client.post(
        f"/api/bundles/{bid}/confirm",
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert r_bundle.status_code == 409
    assert r_bundle.json()["detail"] == "ACTION_EXPIRED"

    # Verify bundle status updated to EXPIRED in DB
    await set_rls_system(db_session)
    chk_b = await db_session.execute(
        text("SELECT status FROM action_bundles WHERE id = :bid"),
        {"bid": bid},
    )
    assert chk_b.scalar_one() == "EXPIRED"
