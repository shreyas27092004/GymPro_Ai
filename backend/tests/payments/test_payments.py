# tests/payments/test_payments.py
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
from app.payments.provider import FakeProvider, set_provider, to_minor
from app.payments.reconciler import reconcile_payments
from app.settings import Settings, settings
from tests.conftest import TestSeedSession, superuser_engine


FAKE_KEY_SECRET = "test_key_secret_xyz123"
FAKE_WEBHOOK_SECRET = "test_webhook_secret_abc789"


@pytest.fixture(autouse=True)
def setup_payments_environment():
    orig_mode = settings.payments_mode
    orig_key_id = settings.razorpay_key_id
    orig_key_secret = settings.razorpay_key_secret
    orig_webhook_secret = settings.razorpay_webhook_secret

    settings.payments_mode = "razorpay"
    settings.razorpay_key_id = "rzp_test_public_key_123"
    settings.razorpay_key_secret = FAKE_KEY_SECRET
    settings.razorpay_webhook_secret = FAKE_WEBHOOK_SECRET

    fake = FakeProvider(key_secret=FAKE_KEY_SECRET, webhook_secret=FAKE_WEBHOOK_SECRET)
    set_provider(fake)

    yield fake

    settings.payments_mode = orig_mode
    settings.razorpay_key_id = orig_key_id
    settings.razorpay_key_secret = orig_key_secret
    settings.razorpay_webhook_secret = orig_webhook_secret


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


async def seed_membership(user_id: uuid.UUID, plan_code: str = "SILVER") -> None:
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
                VALUES (gen_random_uuid(), :uid, :p, 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE - INTERVAL '5 days', CURRENT_DATE + INTERVAL '25 days')
                """
            ),
            {"uid": user_id, "p": plan_code},
        )


async def seed_class(trainer_id: uuid.UUID | None = None, allowed_plans: list[str] | None = None) -> uuid.UUID:
    tid = trainer_id or uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status)
                VALUES (:tid, :email, 'pw', 'Coach', 'TRAINER', 'ACTIVE')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"tid": tid, "email": f"trainer_{uuid.uuid4().hex[:8]}@gympro.test"},
        )
        await seed_db.commit()

    cid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO trainer_profiles (trainer_id, bio) VALUES (:tid, 'Bio') ON CONFLICT DO NOTHING"),
            {"tid": tid},
        )
        await conn.execute(
            text(
                """
                INSERT INTO fitness_classes (
                    id, title, trainer_id, category, impact, min_level, trial_eligible,
                    capacity, booked_count, start_time, end_time, status, allowed_plans
                ) VALUES (
                    :cid, 'VIP Spin', :tid, 'SPIN', 'HIGH', 'BEGINNER', false,
                    20, 0, NOW() + INTERVAL '2 days', NOW() + INTERVAL '2 days 1 hour', 'SCHEDULED', :plans
                )
                """
            ),
            {"cid": cid, "tid": tid, "plans": allowed_plans or []},
        )
    return cid


# -------------------------------------------------------------------------
# 1. Order Amount Equals to_minor(prorated_today); Receipt Equals payment.id;
#    One Order Per Action Even if Confirm is Replayed
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_order_amount_and_single_order_replay(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "pay_order_amount@gympro.test", phone="+919911100000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")
    expected_minor = to_minor(quote.prorated_today)

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:payload AS jsonb), 'Upgrade to Platinum', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "aid": aid,
                "uid": u["id"],
                "payload": json.dumps({
                    "to_plan": "PLATINUM",
                    "cycle": "MONTHLY",
                    "confirmed_total": float(quote.prorated_today),
                }),
            },
        )

    # First confirm
    r1 = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert "awaiting" in d1
    checkout1 = d1["awaiting"]
    assert checkout1["amount_minor"] == expected_minor
    assert checkout1["currency"] == "INR"

    # Assert exactly 1 order was created on provider
    assert len(fake.create_order_calls) == 1
    created_order = fake.create_order_calls[0]
    assert created_order["amount"] == expected_minor
    # Receipt equals payment id hex
    payment_id = uuid.UUID(checkout1["payment_id"])
    assert created_order["receipt"] == payment_id.hex

    # Second confirm (replay)
    r2 = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2 == d1
    # Still only 1 order created on provider (no duplicate order created)
    assert len(fake.create_order_calls) == 1


# -------------------------------------------------------------------------
# 2. Valid Signature: Membership Replaced, Receipt Email Queued,
#    Dependent Booking and Email Steps Run
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_signature_activates_membership_receipt_and_runs_dependents(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "pay_valid_sig@gympro.test", phone="+919922200000")
    await seed_membership(u["id"], "SILVER")
    plat_class_id = await seed_class(allowed_plans=["PLATINUM"])

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    bid = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    a3 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Bundle with upgrade and booking', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bid, "uid": u["id"]},
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
                "bid": bid,
                "p1": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)}),
            },
        )
        # Step 2: BOOK_CLASS for Platinum class (depends on 1)
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Book VIP Class', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a2": a2,
                "uid": u["id"],
                "bid": bid,
                "p2": json.dumps({"class_id": str(plat_class_id)}),
            },
        )
        # Step 3: SEND_BOOKING_EMAIL (depends on 2)
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a3, :uid, :bid, 3, '{2}', 'SEND_BOOKING_EMAIL', CAST(:p3 AS jsonb), 'Send confirmation', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a3": a3,
                "uid": u["id"],
                "bid": bid,
                "p3": json.dumps({"template_id": "CLASS_CONFIRMED", "params": {}, "attach_calendar": True, "requires_step": 2}),
            },
        )

    # 1. Start confirmation: pauses at Step 1 with AWAITING_PAYMENT
    r_bundle = await client.post(f"/api/bundles/{bid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r_bundle.status_code == 200
    b_data = r_bundle.json()
    assert b_data["status"] == "AWAITING_PAYMENT"
    checkout = b_data["payment"]
    order_id = checkout["order_id"]
    payment_ref = f"pay_{uuid.uuid4().hex[:10]}"
    sig = fake.make_checkout_signature(order_id, payment_ref)

    # 2. Client completes payment and calls verify endpoint
    v_res = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_ref,
            "razorpay_signature": sig,
        },
    )
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["ok"] is True
    assert v_data["status"] == "PAID"

    # 3. Verify database state
    await set_rls_system(db_session)
    # Check active membership is now PLATINUM
    m_chk = await db_session.execute(
        text("SELECT plan_code, status FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": u["id"]},
    )
    m_row = m_chk.mappings().one()
    assert m_row["plan_code"] == "PLATINUM"

    # Check PAYMENT_RECEIPT email in outbox
    rcpt_chk = await db_session.execute(
        text("SELECT template, routing_key FROM notification_outbox WHERE user_id = :uid AND template = 'PAYMENT_RECEIPT'"),
        {"uid": u["id"]},
    )
    assert rcpt_chk.first() is not None

    # Check Step 2 (BOOK_CLASS) executed successfully
    b_chk = await db_session.execute(
        text("SELECT status FROM class_bookings WHERE user_id = :uid AND class_id = :cid"),
        {"uid": u["id"], "cid": plat_class_id},
    )
    b_row = b_chk.mappings().one()
    assert b_row["status"] == "CONFIRMED"

    # Check bundle status is now EXECUTED
    bundle_chk = await db_session.execute(
        text("SELECT status FROM action_bundles WHERE id = :bid"),
        {"bid": bid},
    )
    assert bundle_chk.scalar_one() == "EXECUTED"


# -------------------------------------------------------------------------
# 3. Tampered Signature or Another User's Order
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tampered_signature_or_another_users_order(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u1 = await create_user(db_session, "user1_tamper@gympro.test", phone="+919933300000")
    u2 = await create_user(db_session, "user2_tamper@gympro.test", phone="+919944400000")
    await seed_membership(u1["id"], "SILVER")

    quote = await price_diff(db_session, u1["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u1["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u1['token']}"})
    checkout = r_init.json()["awaiting"]
    order_id = checkout["order_id"]
    fake_pid = f"pay_{uuid.uuid4().hex[:10]}"

    # A: User 1 submits tampered signature -> 400 PAYMENT_SIGNATURE_INVALID
    bad_sig = "bad_signature_tampered_12345"
    r_bad = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u1['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": fake_pid, "razorpay_signature": bad_sig},
    )
    assert r_bad.status_code == 400
    assert "PAYMENT_SIGNATURE_INVALID" in r_bad.text

    # Verify audit log wrote PAYMENT_SIGNATURE_INVALID
    await set_rls_system(db_session)
    audit_chk = await db_session.execute(
        text("SELECT count(*) FROM audit_log WHERE actor_id = :uid AND action = 'PAYMENT_SIGNATURE_INVALID'"),
        {"uid": u1["id"]},
    )
    assert audit_chk.scalar_one() >= 1

    # B: User 2 attempts to verify User 1's order -> 404
    valid_sig = fake.make_checkout_signature(order_id, fake_pid)
    r_other = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u2['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": fake_pid, "razorpay_signature": valid_sig},
    )
    assert r_other.status_code == 404


# -------------------------------------------------------------------------
# 4. Verify Twice, then Webhook, then Reconciler: Idempotency
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_twice_then_webhook_then_reconciler_idempotency(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "idempotent_flow@gympro.test", phone="+919955500000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    order_id = r_init.json()["awaiting"]["order_id"]
    fake_pid = f"pay_{uuid.uuid4().hex[:10]}"
    sig = fake.make_checkout_signature(order_id, fake_pid)

    # 1. First verify call -> succeeds
    r_v1 = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": fake_pid, "razorpay_signature": sig},
    )
    assert r_v1.status_code == 200

    # 2. Second verify call -> replay succeeds
    r_v2 = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": fake_pid, "razorpay_signature": sig},
    )
    assert r_v2.status_code == 200

    # 3. Webhook delivery -> returns ok without secondary side-effects
    wh_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {"id": fake_pid, "order_id": order_id}},
        },
    }
    raw_wh = json.dumps(wh_payload).encode()
    wh_sig = fake.make_webhook_signature(raw_wh)
    r_wh = await client.post(
        "/api/payments/razorpay/webhook",
        headers={
            "X-Razorpay-Signature": wh_sig,
            "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex}",
            "Content-Type": "application/json",
        },
        content=raw_wh,
    )
    assert r_wh.status_code == 200

    # 4. Reconciler run -> no secondary effect
    fake.add_payment_to_order(order_id, fake_pid, status="captured")
    rec_res = await reconcile_payments(db_session, fake)
    # Reconciler sees it is already PAID so finalize_paid returns replay
    assert rec_res["paid"] == 1 or rec_res["paid"] == 0

    # Verify exactly 1 active membership and 1 receipt
    await set_rls_system(db_session)
    m_count = await db_session.execute(
        text("SELECT count(*) FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": u["id"]},
    )
    assert m_count.scalar_one() == 1

    rcpt_count = await db_session.execute(
        text("SELECT count(*) FROM notification_outbox WHERE user_id = :uid AND template = 'PAYMENT_RECEIPT'"),
        {"uid": u["id"]},
    )
    assert rcpt_count.scalar_one() == 1


# -------------------------------------------------------------------------
# 5. Webhook: Bad Signature, Forged Body, Replayed Event ID
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_webhook_bad_signature_forged_body_and_replayed_event_id(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    payload = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_test_123"}}}}
    raw = json.dumps(payload).encode()

    # 1. Bad signature -> 400
    r_bad = await client.post(
        "/api/payments/razorpay/webhook",
        headers={"X-Razorpay-Signature": "invalid_sig", "Content-Type": "application/json"},
        content=raw,
    )
    assert r_bad.status_code == 400

    # 2. Forged body (signature generated for different body) -> 400
    other_sig = fake.make_webhook_signature(b'{"different": true}')
    r_forged = await client.post(
        "/api/payments/razorpay/webhook",
        headers={"X-Razorpay-Signature": other_sig, "Content-Type": "application/json"},
        content=raw,
    )
    assert r_forged.status_code == 400

    # 3. Valid delivery -> 200
    valid_sig = fake.make_webhook_signature(raw)
    ev_id = f"evt_unique_{uuid.uuid4().hex}"
    r_valid = await client.post(
        "/api/payments/razorpay/webhook",
        headers={
            "X-Razorpay-Signature": valid_sig,
            "X-Razorpay-Event-Id": ev_id,
            "Content-Type": "application/json",
        },
        content=raw,
    )
    assert r_valid.status_code == 200

    # 4. Replayed event ID -> 200 with duplicate flag
    r_replay = await client.post(
        "/api/payments/razorpay/webhook",
        headers={
            "X-Razorpay-Signature": valid_sig,
            "X-Razorpay-Event-Id": ev_id,
            "Content-Type": "application/json",
        },
        content=raw,
    )
    assert r_replay.status_code == 200
    assert r_replay.json().get("duplicate") is True


# -------------------------------------------------------------------------
# 6. Payment Expires: Action FAILED (PAYMENT_EXPIRED), Dependents SKIPPED,
#    Independent Steps Still Run
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_payment_expires_action_failed_dependents_skipped_independent_step_runs(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "pay_expire@gympro.test", phone="+919966600000")
    await seed_membership(u["id"], "SILVER")
    plat_class_id = await seed_class(allowed_plans=["PLATINUM"])

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    bid = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    a3 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Bundle with expiry test', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bid, "uid": u["id"]},
        )
        # Step 1: CHANGE_PLAN to PLATINUM
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, :bid, 1, '{}', 'CHANGE_PLAN', CAST(:p1 AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a1": a1, "uid": u["id"], "bid": bid, "p1": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )
        # Step 2: BOOK_CLASS (depends on 1)
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'BOOK_CLASS', CAST(:p2 AS jsonb), 'Book VIP Class', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a2": a2, "uid": u["id"], "bid": bid, "p2": json.dumps({"class_id": str(plat_class_id)})},
        )
        # Step 3: SUBMIT_ISSUE_REPORT (independent: depends_on = {})
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a3, :uid, :bid, 3, '{}', 'SUBMIT_ISSUE_REPORT', CAST(:p3 AS jsonb), 'Issue Report', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {
                "a3": a3,
                "uid": u["id"],
                "bid": bid,
                "p3": json.dumps({"category": "FACILITY", "user_words": "Locker broken", "neutral_summary": "Broken locker"}),
            },
        )

    # 1. Start confirmation: Step 1 becomes AWAITING_PAYMENT
    r_bundle = await client.post(f"/api/bundles/{bid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    assert r_bundle.status_code == 200
    b_data = r_bundle.json()
    assert b_data["status"] == "AWAITING_PAYMENT"

    # 2. Simulate payment expiry in database
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("UPDATE payments SET expires_at = NOW() - INTERVAL '1 minute' WHERE action_id = :a1"),
            {"a1": a1},
        )

    # 3. Run reconciler
    await reconcile_payments(db_session, fake)

    # 4. Check step results
    await set_rls_system(db_session)
    steps_res = await db_session.execute(
        text("SELECT step_no, status, result FROM pending_actions WHERE bundle_id = :bid ORDER BY step_no ASC"),
        {"bid": bid},
    )
    steps = steps_res.mappings().all()
    # Step 1: FAILED with PAYMENT_EXPIRED
    assert steps[0]["status"] == "FAILED"
    assert steps[0]["result"]["error"] == "PAYMENT_EXPIRED"
    # Step 2: SKIPPED with DEPENDENCY_FAILED
    assert steps[1]["status"] == "SKIPPED"
    assert steps[1]["result"]["error"] == "DEPENDENCY_FAILED"
    # Step 3: EXECUTED (independent step ran)
    assert steps[2]["status"] == "EXECUTED"

    # Bundle status is PARTIAL
    bundle_res = await db_session.execute(
        text("SELECT status FROM action_bundles WHERE id = :bid"),
        {"bid": bid},
    )
    assert bundle_res.scalar_one() == "PARTIAL"


# -------------------------------------------------------------------------
# 7. User Cancels in Checkout
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_user_cancels_in_checkout(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "pay_cancel@gympro.test", phone="+919977700000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    bid = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO action_bundles (id, user_id, status, summary, expires_at) VALUES (:bid, :uid, 'PENDING', 'Cancel test', NOW() + INTERVAL '15 min')"),
            {"bid": bid, "uid": u["id"]},
        )
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a1, :uid, :bid, 1, '{}', 'CHANGE_PLAN', CAST(:p1 AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a1": a1, "uid": u["id"], "bid": bid, "p1": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, bundle_id, step_no, depends_on, type, payload, summary, status, expires_at)
                VALUES (:a2, :uid, :bid, 2, '{1}', 'SUBMIT_ISSUE_REPORT', CAST(:p2 AS jsonb), 'Issue', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"a2": a2, "uid": u["id"], "bid": bid, "p2": json.dumps({"category": "OTHER", "user_words": "Note", "neutral_summary": "Note"})},
        )

    r_init = await client.post(f"/api/bundles/{bid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    payment_id = r_init.json()["payment"]["payment_id"]

    # User clicks Cancel
    r_cancel = await client.post(f"/api/payments/{payment_id}/cancel", headers={"Authorization": f"Bearer {u['token']}"})
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == "CANCELLED"

    # Verify action 1 FAILED (PAYMENT_CANCELLED) and action 2 SKIPPED
    await set_rls_system(db_session)
    steps_res = await db_session.execute(
        text("SELECT step_no, status, result FROM pending_actions WHERE bundle_id = :bid ORDER BY step_no ASC"),
        {"bid": bid},
    )
    steps = steps_res.mappings().all()
    assert steps[0]["status"] == "FAILED"
    assert steps[0]["result"]["error"] == "PAYMENT_CANCELLED"
    assert steps[1]["status"] == "SKIPPED"


# -------------------------------------------------------------------------
# 8. payment.failed Then a Successful Retry
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_payment_failed_then_successful_retry(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "pay_failed_retry@gympro.test", phone="+919988800000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    order_id = r_init.json()["awaiting"]["order_id"]

    # Webhook payment.failed arrives (attempt 1)
    fail_payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"order_id": order_id}}},
    }
    raw1 = json.dumps(fail_payload).encode()
    await client.post(
        "/api/payments/razorpay/webhook",
        headers={"X-Razorpay-Signature": fake.make_webhook_signature(raw1), "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex}"},
        content=raw1,
    )

    # Check attempts incremented and payment NOT terminated
    await set_rls_system(db_session)
    p_chk1 = await db_session.execute(
        text("SELECT status, attempts FROM payments WHERE razorpay_order_id = :oid"),
        {"oid": order_id},
    )
    row1 = p_chk1.mappings().one()
    assert row1["attempts"] == 1
    assert row1["status"] == "CREATED"

    # User retries successfully in Checkout
    success_pid = f"pay_{uuid.uuid4().hex[:10]}"
    sig = fake.make_checkout_signature(order_id, success_pid)
    r_v = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": success_pid, "razorpay_signature": sig},
    )
    assert r_v.status_code == 200

    # Check membership is now PLATINUM
    m_chk = await db_session.execute(
        text("SELECT plan_code FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": u["id"]},
    )
    assert m_chk.scalar_one() == "PLATINUM"


# -------------------------------------------------------------------------
# 9. Capture Arrives After Expiry -> NEEDS_REVIEW, No Activation, Admin Alert
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_capture_arrives_after_expiry(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "late_capture@gympro.test", phone="+919999900000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    order_id = r_init.json()["awaiting"]["order_id"]

    # Mark payment as EXPIRED
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("UPDATE payments SET status = 'EXPIRED', expires_at = NOW() - INTERVAL '1 hour' WHERE razorpay_order_id = :oid"),
            {"oid": order_id},
        )

    # Capture arrives via webhook
    late_pid = f"pay_late_{uuid.uuid4().hex[:8]}"
    wh_payload = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": late_pid, "order_id": order_id}}},
    }
    raw = json.dumps(wh_payload).encode()
    r_wh = await client.post(
        "/api/payments/razorpay/webhook",
        headers={"X-Razorpay-Signature": fake.make_webhook_signature(raw), "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex}"},
        content=raw,
    )
    assert r_wh.status_code == 200

    # Payment is marked NEEDS_REVIEW
    await set_rls_system(db_session)
    p_chk = await db_session.execute(
        text("SELECT status FROM payments WHERE razorpay_order_id = :oid"),
        {"oid": order_id},
    )
    assert p_chk.scalar_one() == "NEEDS_REVIEW"

    # User remains on SILVER plan (no silent activation)
    m_chk = await db_session.execute(
        text("SELECT plan_code FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": u["id"]},
    )
    assert m_chk.scalar_one() == "SILVER"

    # Admin alert PAYMENT_NEEDS_REVIEW enqueued
    alert_chk = await db_session.execute(
        text("SELECT count(*) FROM notification_outbox WHERE template = 'PAYMENT_NEEDS_REVIEW'"),
    )
    assert alert_chk.scalar_one() >= 1


# -------------------------------------------------------------------------
# 10. Plan Changed Between Order and Payment -> NEEDS_REVIEW, No Double Activation
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_changed_between_order_and_payment_goes_to_needs_review(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    fake = setup_payments_environment
    u = await create_user(db_session, "plan_changed_interim@gympro.test", phone="+919811100000")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    order_id = r_init.json()["awaiting"]["order_id"]

    # Before payment is verified, user's plan is changed to GOLD (e.g. by staff)
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text("UPDATE memberships SET plan_code = 'GOLD' WHERE user_id = :uid AND status = 'ACTIVE'"),
            {"uid": u["id"]},
        )

    # Client verifies payment
    pid = f"pay_{uuid.uuid4().hex[:10]}"
    sig = fake.make_checkout_signature(order_id, pid)
    r_v = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": pid, "razorpay_signature": sig},
    )
    # Returns NEEDS_REVIEW
    assert r_v.status_code == 200
    assert r_v.json().get("status") == "NEEDS_REVIEW"

    # Check payment is NEEDS_REVIEW
    await set_rls_system(db_session)
    p_chk = await db_session.execute(
        text("SELECT status FROM payments WHERE razorpay_order_id = :oid"),
        {"oid": order_id},
    )
    assert p_chk.scalar_one() == "NEEDS_REVIEW"


# -------------------------------------------------------------------------
# 11. ENV=production With PAYMENTS_MODE=mock Refuses to Start
# -------------------------------------------------------------------------
def test_production_mode_refuses_mock_payments():
    with pytest.raises(RuntimeError) as exc_info:
        Settings(env="production", payments_mode="mock")
    assert "PAYMENTS_MODE=mock is not allowed when ENV=production" in str(exc_info.value)


# -------------------------------------------------------------------------
# 12. PAYMENTS_MODE=disabled -> PAYMENT_PROVIDER_REQUIRED, No payments Row
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_payments_mode_disabled(
    client: AsyncClient,
    db_session: AsyncSession,
):
    orig = settings.payments_mode
    try:
        settings.payments_mode = "disabled"
        u = await create_user(db_session, "pay_disabled@gympro.test", phone="+919822200000")
        await seed_membership(u["id"], "SILVER")

        quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

        aid = uuid.uuid4()
        async with superuser_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                    VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                    """
                ),
                {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
            )

        r = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
        assert r.status_code == 200
        res = r.json()
        assert res["ok"] is False
        assert res["error"] == "PAYMENT_PROVIDER_REQUIRED"

        # No row inserted in payments
        await set_rls_system(db_session)
        p_count = await db_session.execute(
            text("SELECT count(*) FROM payments WHERE action_id = :aid"),
            {"aid": aid},
        )
        assert p_count.scalar_one() == 0
    finally:
        settings.payments_mode = orig


# -------------------------------------------------------------------------
# 13. Key Secret and Webhook Secret Never Leaked
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secrets_never_leaked(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_payments_environment: FakeProvider,
):
    u = await create_user(db_session, "secret_leak_check@gympro.test", phone="+919833311111")
    await seed_membership(u["id"], "SILVER")

    quote = await price_diff(db_session, u["id"], "PLATINUM", "MONTHLY")

    aid = uuid.uuid4()
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
                VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:p AS jsonb), 'Upgrade', 'PENDING', NOW() + INTERVAL '15 min')
                """
            ),
            {"aid": aid, "uid": u["id"], "p": json.dumps({"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": float(quote.prorated_today)})},
        )

    r_init = await client.post(f"/api/actions/{aid}/confirm", headers={"Authorization": f"Bearer {u['token']}"})
    pid = r_init.json()["awaiting"]["payment_id"]

    r_get = await client.get(f"/api/payments/{pid}", headers={"Authorization": f"Bearer {u['token']}"})
    assert r_get.status_code == 200
    body_str = r_get.text

    assert FAKE_KEY_SECRET not in body_str
    assert FAKE_WEBHOOK_SECRET not in body_str
    assert "key_secret" not in body_str
    assert "webhook_secret" not in body_str
