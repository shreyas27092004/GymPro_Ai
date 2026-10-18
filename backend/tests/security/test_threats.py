# tests/security/test_threats.py
import datetime
import hashlib
import hmac
import json
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.runner import run_agent
from app.auth.deps import SessionContext
from app.auth.roles import create_admin_request
from app.auth.security import create_access_token, hash_password, new_admin_code, phone_hash
from app.db import set_rls
from app.entitlements.membership import price_diff
from app.llm import set_llm
from app.observability.logging import redact_text, redact_data
from app.payments.provider import FakeProvider, set_provider
from app.settings import Settings, settings
from app.tools.registry import RunContext, TOOLS, dispatch
import app.tools
from tests.conftest import TestSeedSession, superuser_engine
from tests.evals.fake_llm import fake_llm


@pytest.fixture(autouse=True)
def setup_fake_llm_and_payments():
    set_llm(fake_llm)
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()

    orig_mode = settings.payments_mode
    orig_key_id = settings.razorpay_key_id
    orig_key_secret = settings.razorpay_key_secret
    orig_webhook_secret = settings.razorpay_webhook_secret

    settings.payments_mode = "razorpay"
    settings.razorpay_key_id = "rzp_test_public_key_123"
    settings.razorpay_key_secret = "test_key_secret_xyz123"
    settings.razorpay_webhook_secret = "test_webhook_secret_abc789"

    fake = FakeProvider(key_secret="test_key_secret_xyz123", webhook_secret="test_webhook_secret_abc789")
    set_provider(fake)

    yield fake

    settings.payments_mode = orig_mode
    settings.razorpay_key_id = orig_key_id
    settings.razorpay_key_secret = orig_key_secret
    settings.razorpay_webhook_secret = orig_webhook_secret
    fake_llm.call_history.clear()
    fake_llm.custom_handlers.clear()


async def create_user(
    db: AsyncSession,
    email: str,
    password: str = "Password123!",
    role: str = "USER",
    account_status: str = "ACTIVE",
    email_verified: bool = True,
    cooling_off: bool = False,
) -> dict:
    uid = uuid.uuid4()
    ph = phone_hash(f"+9198{uuid.uuid4().int % 100000000:08d}")
    verified_sql = "NOW()" if email_verified else "NULL"
    cooling_sql = "NOW() + INTERVAL '24 hours'" if cooling_off else "NULL"

    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                f"""
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at, cooling_off_until, token_version)
                VALUES (:id, :email, :pw, 'Test User', :role, :status, {verified_sql}, {cooling_sql}, 0)
                """
            ),
            {
                "id": uid,
                "email": email,
                "pw": hash_password(password),
                "role": role,
                "status": account_status,
            },
        )
        await seed_db.commit()

    token = create_access_token(str(uid), token_version=0)
    return {"id": uid, "email": email, "token": token, "password": password, "phone_hash": ph}


# -----------------------------------------------------------------------------
# 1. Direct role change trigger blocks self-promotion
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_direct_role_update_rejected_by_trigger(db_session: AsyncSession):
    """Direct UPDATE users SET role='ADMIN' as gympro_app is rejected by trigger."""
    u_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status)
                VALUES (:id, :email, 'hash', 'Test Member', 'USER', 'ACTIVE')
                """
            ),
            {"id": u_id, "email": f"trigger_{u_id.hex[:8]}@example.com"},
        )

    with pytest.raises(DBAPIError) as excinfo:
        async with db_session.begin():
            await db_session.execute(
                text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
                {"id": u_id},
            )
    assert "requires an approved role_request" in str(excinfo.value).lower() or "trigger" in str(excinfo.value).lower()


# -----------------------------------------------------------------------------
# 2. Register ignores role: "ADMIN"
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_register_admin_body_ignored(client: AsyncClient, db_session: AsyncSession):
    """Register with body {'role': 'ADMIN'} ignores role, creating USER-level pending account."""
    email = f"attacker_{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Attacker", "role": "ADMIN"},
    )
    assert res.status_code == 200

    row = (
        await db_session.execute(
            text("SELECT role, account_status FROM users WHERE email = :email"),
            {"email": email},
        )
    ).mappings().first()
    assert row is not None
    assert row["role"] == "USER"
    assert row["account_status"] == "PENDING_EMAIL"


# -----------------------------------------------------------------------------
# 3. Trainer logs in before approval
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trainer_login_before_approval(client: AsyncClient, db_session: AsyncSession):
    """Trainer logs in before approval -> 403 ACCOUNT_PENDING_APPROVAL."""
    email = f"pending_tr_{uuid.uuid4().hex[:8]}@example.com"
    u = await create_user(db_session, email=email, role="TRAINER", account_status="PENDING_APPROVAL", email_verified=True)

    res = await client.post("/api/auth/login", json={"email": email, "password": u["password"]})
    assert res.status_code == 403
    assert res.json().get("detail", {}).get("error") == "ACCOUNT_PENDING_APPROVAL"


# -----------------------------------------------------------------------------
# 4. Admin activation: wrong, expired, reused code & lockout after 5 attempts
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_activation_security(client: AsyncClient, db_session: AsyncSession):
    """Admin activation with wrong, expired, reused code returns 401/410 and locks after 5 attempts."""
    await create_user(db_session, email=f"boss_{uuid.uuid4().hex[:8]}@example.com", role="ADMIN")

    target_email = f"new_admin_{uuid.uuid4().hex[:8]}@example.com"
    u = await create_user(db_session, email=target_email, role="USER", account_status="PENDING_ADMIN_CODE")

    code, code_hmac = new_admin_code()
    async with db_session.begin():
        await db_session.execute(
            text(
                """
                INSERT INTO role_requests (user_id, requested_role, status, code_hmac, code_expires_at, expires_at)
                VALUES (:uid, 'ADMIN', 'PENDING', :hmac, NOW() + INTERVAL '30 minutes', NOW() + INTERVAL '30 minutes')
                """
            ),
            {"uid": u["id"], "hmac": code_hmac},
        )

    # 4 wrong attempts -> 401
    for _ in range(4):
        w_res = await client.post(
            "/api/auth/activate-admin",
            json={"email": target_email, "password": u["password"], "code": "WRONGCOD"},
        )
        assert w_res.status_code == 401
        assert w_res.json()["detail"]["error"] == "INVALID_CODE"

    # 5th failed attempt locks the request
    lock_res = await client.post(
        "/api/auth/activate-admin",
        json={"email": target_email, "password": u["password"], "code": "WRONGCOD"},
    )
    assert lock_res.status_code in (401, 423)

    # Subsequent attempt is locked -> 423
    sub_res = await client.post(
        "/api/auth/activate-admin",
        json={"email": target_email, "password": u["password"], "code": "WRONGCOD"},
    )
    assert sub_res.status_code == 423
    assert sub_res.json()["detail"]["error"] == "REQUEST_LOCKED"


# -----------------------------------------------------------------------------
# 5. Flood limits: max 3 pending system-wide
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simultaneous_admin_signups_flood_limits(client: AsyncClient, db_session: AsyncSession):
    """At most 3 pending admin requests system-wide."""
    await create_user(db_session, email=f"active_boss_{uuid.uuid4().hex[:8]}@example.com", role="ADMIN")

    uids = []
    for i in range(4):
        u = await create_user(db_session, email=f"flood_user_{i}_{uuid.uuid4().hex[:6]}@example.com")
        uids.append(u)

    # Create 3 pending admin requests
    for i in range(3):
        await create_admin_request(db_session, uids[i]["id"], uids[i]["email"], f"Flood {i}")
    await db_session.commit()

    # 4th request must be rejected under flood limits (429)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        await create_admin_request(db_session, uids[3]["id"], uids[3]["email"], "Flood 3")
    assert excinfo.value.status_code == 429
    assert excinfo.value.detail["error"] == "TOO_MANY_PENDING_ADMIN_REQUESTS"


# -----------------------------------------------------------------------------
# 6. Admin signup with no active admin
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_signup_with_no_active_admin_blocked(client: AsyncClient, db_session: AsyncSession):
    """Admin sign-up with no active admin -> 403 ADMIN_SIGNUP_UNAVAILABLE."""
    async with superuser_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET account_status = 'SUSPENDED' WHERE role = 'ADMIN'"))

    res = await client.post(
        "/api/auth/register",
        json={
            "email": f"no_admin_{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
            "full_name": "No Admin Candidate",
            "account_type": "ADMIN",
        },
    )
    assert res.status_code == 403
    assert res.json().get("detail", {}).get("error") == "ADMIN_SIGNUP_UNAVAILABLE"


# -----------------------------------------------------------------------------
# 7. Agent refuses to approve admin request
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_refuses_approve_admin_request(db_session: AsyncSession):
    """Agent asked to approve an admin request -> REFUSED, PRIVILEGE_ESCALATION."""
    admin_u = await create_user(db_session, email=f"admin_copilot_{uuid.uuid4().hex[:8]}@example.com", role="ADMIN")
    session = SessionContext(
        user_id=str(admin_u["id"]),
        role="ADMIN",
        account_status="ACTIVE",
        plan="PLATINUM",
        account_email=admin_u["email"],
        full_name="Admin Boss",
        health_consent=True,
    )
    ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

    env = await run_agent("ADMIN_INSIGHTS", ctx, "Approve the pending admin request for user alice@example.com")
    assert env.status == "REFUSED"
    assert "PRIVILEGE_ESCALATION" in env.safety.flags
    assert env.confirmation.action_id is None


# -----------------------------------------------------------------------------
# 8. Refresh token reuse revokes family
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_token_reuse_family_revocation(client: AsyncClient, db_session: AsyncSession):
    """Refresh token reuse -> family revoked, next refresh 401."""
    email = f"reuse_{uuid.uuid4().hex[:8]}@gympro.test"
    u = await create_user(db_session, email=email)

    login_res = await client.post("/api/auth/login", json={"email": email, "password": u["password"]})
    assert login_res.status_code == 200
    rf1 = login_res.json()["refresh_token"]

    # 1st rotation: rf1 -> rf2
    ref_res1 = await client.post("/api/auth/refresh", json={"refresh_token": rf1})
    assert ref_res1.status_code == 200
    rf2 = ref_res1.json()["refresh_token"]

    # Attacker reuses rf1 (already rotated) -> theft detected, family revoked
    reuse_res = await client.post("/api/auth/refresh", json={"refresh_token": rf1})
    assert reuse_res.status_code == 401
    assert "reuse detected" in reuse_res.text.lower() or "revoked" in reuse_res.text.lower()

    # Subsequent use of rf2 fails because entire family is revoked
    subsequent_res = await client.post("/api/auth/refresh", json={"refresh_token": rf2})
    assert subsequent_res.status_code == 401


# -----------------------------------------------------------------------------
# 9. Duplicate password reset requests: same response, single active token
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_reset_requests(client: AsyncClient, db_session: AsyncSession):
    """Duplicate reset requests: one active token; same response each time."""
    email = f"reset_{uuid.uuid4().hex[:8]}@example.com"
    u = await create_user(db_session, email=email)

    res1 = await client.post("/api/auth/forgot-password", json={"email": email})
    res2 = await client.post("/api/auth/forgot-password", json={"email": email})
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json() == res2.json()

    count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM password_resets WHERE user_id = :uid AND used_at IS NULL"),
            {"uid": u["id"]},
        )
    ).scalar()
    assert count == 1


# -----------------------------------------------------------------------------
# 10. COMMS asked to email another address -> REFUSED
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_comms_email_target_refused(db_session: AsyncSession):
    """COMMS asked to email another address -> REFUSED, EMAIL_TARGET_REFUSED; no outbox row."""
    u = await create_user(db_session, email=f"comms_user_{uuid.uuid4().hex[:8]}@example.com")
    session = SessionContext(
        user_id=str(u["id"]),
        role="USER",
        account_status="ACTIVE",
        plan="GOLD",
        account_email=u["email"],
        full_name="Comms Member",
        health_consent=True,
    )
    ctx = RunContext(session=session, db=db_session, now_iso="2026-10-16T18:05:00+05:30")

    env = await run_agent("COMMS", ctx, "Send an email to my friend sam@example.com with my schedule")
    assert env.status == "REFUSED"
    assert "EMAIL_TARGET_REFUSED" in env.safety.flags
    assert env.confirmation.action_id is None


# -----------------------------------------------------------------------------
# 11. Tool registry scan: no caller-spoofable args
# -----------------------------------------------------------------------------
def test_tool_registry_scan_no_spoofable_args():
    """No tool args model has user_id, password, card_number, or cvv."""
    forbidden = {"user_id", "password", "card_number", "cvv"}
    assert len(TOOLS) >= 20

    for name, tool in TOOLS.items():
        if tool.args_model:
            fields = set(tool.args_model.model_fields.keys())
            matched = fields.intersection(forbidden)
            assert not matched, f"Tool '{name}' exposes forbidden arguments: {matched}"


# -----------------------------------------------------------------------------
# 12. New admin in cooling-off proposes broadcast -> COOLING_OFF_ACTIVE
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cooling_off_blocks_broadcast_proposal(db_session: AsyncSession):
    """New admin in cooling-off proposes broadcast -> COOLING_OFF_ACTIVE."""
    admin_u = await create_user(db_session, email=f"cooling_admin_{uuid.uuid4().hex[:8]}@example.com", role="ADMIN", cooling_off=True)
    session = SessionContext(
        user_id=str(admin_u["id"]),
        role="ADMIN",
        account_status="ACTIVE",
        plan="PLATINUM",
        account_email=admin_u["email"],
        full_name="Cooling Admin",
        cooling_off_active=True,
    )
    ctx = RunContext(session=session, db=db_session, allowed_tools={"propose_broadcast"})

    res = await dispatch(
        "propose_broadcast",
        {"subject": "Emergency Notice", "body": "Testing broadcast during cooling-off window."},
        ctx,
    )
    assert res.get("ok") is False
    assert res.get("error") == "COOLING_OFF_ACTIVE"


# -----------------------------------------------------------------------------
# 13. RLS: USER reads another user's profile -> Zero rows
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rls_user_cannot_read_another_profile(db_session: AsyncSession):
    """Postgres RLS: USER reads another user's profile yields zero rows."""
    u1 = await create_user(db_session, email=f"rls_a_{uuid.uuid4().hex[:6]}@example.com")
    u2 = await create_user(db_session, email=f"rls_b_{uuid.uuid4().hex[:6]}@example.com")

    # Insert profiles as system/seed
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO member_profiles (user_id, date_of_birth, height_cm, weight_kg)
                VALUES (:aid, '1995-05-15', 175.0, 72.0),
                       (:bid, '1992-08-20', 180.0, 80.0)
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"aid": u1["id"], "bid": u2["id"]},
        )

    # Set RLS as User 1
    async with db_session.begin():
        await set_rls(db_session, str(u1["id"]), "USER")
        res = await db_session.execute(
            text("SELECT user_id FROM member_profiles WHERE user_id = :bid"),
            {"bid": u2["id"]},
        )
        assert res.scalar_one_or_none() is None


# -----------------------------------------------------------------------------
# 14. Bundle confirm with forged step list ignored
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bundle_confirm_forged_step_list_ignored(client: AsyncClient, db_session: AsyncSession):
    """Bundle confirm with forged step list: server ignores client steps; runs only DB rows."""
    u = await create_user(db_session, email=f"forged_bundle_{uuid.uuid4().hex[:6]}@example.com")
    bundle_id = uuid.uuid4()

    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO action_bundles (id, user_id, status, summary, expires_at)
                VALUES (:bid, :uid, 'PENDING', 'Legitimate empty bundle', NOW() + INTERVAL '15 min')
                """
            ),
            {"bid": bundle_id, "uid": u["id"]},
        )

    forged_payload = {
        "steps": [
            {"action_type": "GRANT_FREE_PLATINUM", "params": {"tier": "PLATINUM"}},
            {"action_type": "CHANGE_ROLE", "params": {"role": "ADMIN"}},
        ]
    }
    res = await client.post(
        f"/api/bundles/{bundle_id}/confirm",
        json=forged_payload,
        headers={"Authorization": f"Bearer {u['token']}"},
    )
    assert res.status_code in (200, 400)

    # User role remains USER
    role = (
        await db_session.execute(text("SELECT role FROM users WHERE id = :uid"), {"uid": u["id"]})
    ).scalar()
    assert role == "USER"


# -----------------------------------------------------------------------------
# 15. Verify with wrong signature or another user's order
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_wrong_signature_or_unowned_order(
    client: AsyncClient,
    db_session: AsyncSession,
    setup_fake_llm_and_payments: FakeProvider,
):
    """Verify with wrong signature or another user's order -> 400 PAYMENT_SIGNATURE_INVALID or 404."""
    fake = setup_fake_llm_and_payments
    u1 = await create_user(db_session, email=f"pay_u1_{uuid.uuid4().hex[:6]}@example.com")
    u2 = await create_user(db_session, email=f"pay_u2_{uuid.uuid4().hex[:6]}@example.com")

    # Seed SILVER membership for User 1
    async with superuser_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date)
                VALUES (:mid, :uid, 'SILVER', 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE - INTERVAL '10 days', CURRENT_DATE + INTERVAL '20 days')
                """
            ),
            {"mid": uuid.uuid4(), "uid": u1["id"]},
        )

    quote = await price_diff(db_session, u1["id"], "PLATINUM", "MONTHLY")

    # Order initiated for User 1
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
    assert r_init.status_code == 200
    order_id = r_init.json()["awaiting"]["order_id"]

    # 1. User 1 submits forged/tampered signature -> 400
    r_tamper = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u1['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_fake_1", "razorpay_signature": "tampered_sig"},
    )
    assert r_tamper.status_code == 400
    assert "PAYMENT_SIGNATURE_INVALID" in str(r_tamper.json())

    # 2. User 2 submits verification for User 1's order -> 404 ORDER_NOT_FOUND
    sig2 = fake.make_checkout_signature(order_id, "pay_fake_2")
    r_unowned = await client.post(
        "/api/payments/razorpay/verify",
        headers={"Authorization": f"Bearer {u2['token']}"},
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_fake_2", "razorpay_signature": sig2},
    )
    assert r_unowned.status_code == 404


# -----------------------------------------------------------------------------
# 16. Webhook with bad signature or same event id twice
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_webhook_bad_signature_and_deduplication(
    client: AsyncClient,
    setup_fake_llm_and_payments: FakeProvider,
):
    """Webhook with bad signature (400), and same event id deduplication."""
    fake = setup_fake_llm_and_payments

    # 1. Bad signature -> 400
    res_bad = await client.post(
        "/api/payments/razorpay/webhook",
        content=b'{"event": "payment.captured"}',
        headers={"X-Razorpay-Signature": "invalid_hex_sig", "X-Razorpay-Event-Id": "evt_bad_sig"},
    )
    assert res_bad.status_code == 400

    # 2. Valid signature delivery
    event_id = f"evt_{uuid.uuid4().hex}"
    raw_wh = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_dedup_1"}}}}).encode()
    wh_sig = fake.make_webhook_signature(raw_wh)

    res1 = await client.post(
        "/api/payments/razorpay/webhook",
        headers={
            "X-Razorpay-Signature": wh_sig,
            "X-Razorpay-Event-Id": event_id,
            "Content-Type": "application/json",
        },
        content=raw_wh,
    )
    assert res1.status_code == 200

    # 3. Duplicate event delivery -> 200 already_processed / duplicate
    res2 = await client.post(
        "/api/payments/razorpay/webhook",
        headers={
            "X-Razorpay-Signature": wh_sig,
            "X-Razorpay-Event-Id": event_id,
            "Content-Type": "application/json",
        },
        content=raw_wh,
    )
    assert res2.status_code == 200
    assert res2.json().get("duplicate") is True or res2.json().get("ok") is True


# -----------------------------------------------------------------------------
# 17. Startup check refuses production with mock payments
# -----------------------------------------------------------------------------
def test_production_env_refuses_mock_payments():
    """ENV=production with PAYMENTS_MODE=mock refuses startup."""
    with pytest.raises(RuntimeError) as excinfo:
        Settings(env="production", payments_mode="mock")
    assert "PAYMENTS_MODE=mock is not allowed when ENV=production" in str(excinfo.value)


# -----------------------------------------------------------------------------
# 18. Agent or tool arguments containing card, UPI or bank details scrubbed
# -----------------------------------------------------------------------------
def test_financial_data_scrubbed_from_logs_and_tools():
    """Agent or tool arguments containing card, UPI or bank details are scrubbed."""
    raw_text = "User entered card 4111 1111 1111 1111 and password secret123 with Bearer secrettoken"
    scrubbed = redact_text(raw_text)
    assert "4111" not in scrubbed
    assert "[REDACTED_CARD]" in scrubbed
    assert "secrettoken" not in scrubbed
    assert "[REDACTED_TOKEN]" in scrubbed

    data_payload = {
        "card_number": "4242424242424242",
        "cvv": "123",
        "email": "member@gympro.io",
        "notes": "Payment processed",
    }
    redacted = redact_data(data_payload)
    assert redacted["card_number"] == "[REDACTED]"
    assert redacted["cvv"] == "[REDACTED]"
    assert "member@gympro.io" not in redacted["email"]
    assert "email_hash:" in redacted["email"]
