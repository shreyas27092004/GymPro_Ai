# tests/roles/test_roles.py
import datetime
import uuid
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.security import create_access_token, hash_password, new_admin_code
from app.jobs.expiry import run_expiry_jobs
from app.main import app
from app.seed_admin import seed_first_admin
from app.settings import settings
from tests.conftest import TestAppSession, TestSeedSession


async def create_test_admin(db: AsyncSession, email: str = "active_admin@gympro.test", cooling_off: bool = False) -> dict[str, str]:
    """Helper to seed an active admin directly."""
    aid = uuid.uuid4()
    cooling_until = "NOW() + INTERVAL '24 hours'" if cooling_off else "NULL"
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                f"""
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at, cooling_off_until)
                VALUES (:id, :email, :pw, 'Test Admin', 'ADMIN', 'ACTIVE', NOW(), {cooling_until})
                """
            ),
            {"id": aid, "email": email, "pw": hash_password("adminpassword123")},
        )
        await seed_db.commit()

    token = create_access_token(str(aid), token_version=0)
    return {"id": str(aid), "email": email, "token": token}


# -------------------------------------------------------------------------
# 1. No-Admin Bootstrap
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_admin_bootstrap(client: AsyncClient, db_session: AsyncSession):
    """Verify admin sign-up is unavailable when no active admin exists, and seed command creates first admin."""
    # 1. Without any active admin, registering with ADMIN account_type is refused
    res = await client.post(
        "/api/auth/register",
        json={
            "email": "bootstrap_admin@gympro.test",
            "password": "validpassword123",
            "full_name": "Bootstrap Admin",
            "account_type": "ADMIN",
        },
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "ADMIN_SIGNUP_UNAVAILABLE"

    # 2. Seed first admin using seed command logic
    first_admin_email = "first_seeded_admin@gympro.test"
    admin_id = seed_first_admin(first_admin_email, "supersecretpassword123", use_test_db=True)
    assert admin_id is not None

    # Verify admin in DB
    chk = await db_session.execute(
        text("SELECT role, account_status FROM users WHERE email = :email"),
        {"email": first_admin_email},
    )
    row = chk.mappings().one()
    assert row["role"] == "ADMIN"
    assert row["account_status"] == "ACTIVE"

    # 3. Attempting to seed again when an active admin already exists is strictly refused
    with pytest.raises(RuntimeError, match="Active admin already exists"):
        seed_first_admin("second_admin@gympro.test", "anotherpassword123", use_test_db=True)


# -------------------------------------------------------------------------
# 2. Admin Code Flow (Wrong, Expired, Reused, Five Attempts Lock)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_code_security_and_lockout(client: AsyncClient, db_session: AsyncSession):
    """Verify wrong code, reused code, expired code, and 5-attempt lockout."""
    # Ensure active admin exists so admin requests are allowed
    admin = await create_test_admin(db_session, email="system_boss@gympro.test")

    applicant_email = "applicant_lockout@gympro.test"
    password = "validpassword123"

    # 1. Register as ADMIN
    reg_res = await client.post(
        "/api/auth/register",
        json={
            "email": applicant_email,
            "password": password,
            "full_name": "Lockout Applicant",
            "account_type": "ADMIN",
        },
    )
    assert reg_res.status_code == 200

    # 2. Get verification token from DB and verify email
    v_res = await db_session.execute(
        text(
            """
            SELECT v.id, u.id as user_id FROM email_verifications v
            JOIN users u ON v.user_id = u.id
            WHERE u.email = :email
            """
        ),
        {"email": applicant_email},
    )
    v_row = v_res.mappings().one()

    # Manually update verification and trigger create_admin_request
    from app.auth.roles import create_admin_request
    await db_session.execute(
        text("UPDATE email_verifications SET used_at = NOW() WHERE id = :id"),
        {"id": v_row["id"]},
    )
    await db_session.execute(
        text("UPDATE users SET email_verified_at = NOW(), account_status = 'PENDING_ADMIN_CODE' WHERE id = :uid"),
        {"uid": v_row["user_id"]},
    )
    await create_admin_request(db_session, v_row["user_id"], applicant_email, "Lockout Applicant")
    await db_session.commit()

    # Fetch code_hmac from role_requests
    r_res = await db_session.execute(
        text("SELECT id, code_hmac FROM role_requests WHERE user_id = :uid AND requested_role = 'ADMIN'"),
        {"uid": v_row["user_id"]},
    )
    r_row = r_res.mappings().one()

    # Test 4 wrong code attempts -> 401 INVALID_CODE
    for attempt in range(1, 5):
        w_res = await client.post(
            "/api/auth/activate-admin",
            json={"email": applicant_email, "password": password, "code": "WRONGCOD"},
        )
        assert w_res.status_code == 401
        assert w_res.json()["detail"]["error"] == "INVALID_CODE"

    # 5th failed attempt locks the request -> 423 REQUEST_LOCKED
    lock_res = await client.post(
        "/api/auth/activate-admin",
        json={"email": applicant_email, "password": password, "code": "WRONGCOD"},
    )
    assert lock_res.status_code in (401, 423)

    # Subsequent attempt is locked
    sub_res = await client.post(
        "/api/auth/activate-admin",
        json={"email": applicant_email, "password": password, "code": "WRONGCOD"},
    )
    assert sub_res.status_code == 423
    assert sub_res.json()["detail"]["error"] == "REQUEST_LOCKED"


@pytest.mark.asyncio
async def test_admin_code_single_use_and_expiry(client: AsyncClient, db_session: AsyncSession):
    """Verify successful code activation is single-use and expired code is rejected."""
    await create_test_admin(db_session, email="system_boss2@gympro.test")

    # A. Expired Code
    exp_uid = uuid.uuid4()
    code, code_hmac = new_admin_code()
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
            VALUES (:uid, 'expired_code@gympro.test', :pw, 'Expired User', 'USER', 'PENDING_ADMIN_CODE', NOW())
            """
        ),
        {"uid": exp_uid, "pw": hash_password("validpassword123")},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO role_requests (user_id, requested_role, status, code_hmac, code_expires_at, expires_at)
            VALUES (:uid, 'ADMIN', 'PENDING', :hmac, NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '5 minutes')
            """
        ),
        {"uid": exp_uid, "hmac": code_hmac},
    )
    await db_session.commit()

    exp_res = await client.post(
        "/api/auth/activate-admin",
        json={"email": "expired_code@gympro.test", "password": "validpassword123", "code": code},
    )
    assert exp_res.status_code == 410
    assert exp_res.json()["detail"]["error"] == "CODE_EXPIRED"

    # B. Single Use: Valid activation succeeds, reuse fails
    valid_uid = uuid.uuid4()
    v_code, v_hmac = new_admin_code()
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
            VALUES (:uid, 'valid_activation@gympro.test', :pw, 'Valid User', 'USER', 'PENDING_ADMIN_CODE', NOW())
            """
        ),
        {"uid": valid_uid, "pw": hash_password("validpassword123")},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO role_requests (user_id, requested_role, status, code_hmac, code_expires_at, expires_at)
            VALUES (:uid, 'ADMIN', 'PENDING', :hmac, NOW() + INTERVAL '30 minutes', NOW() + INTERVAL '30 minutes')
            """
        ),
        {"uid": valid_uid, "hmac": v_hmac},
    )
    await db_session.commit()

    # 1st activation: succeeds!
    act1 = await client.post(
        "/api/auth/activate-admin",
        json={"email": "valid_activation@gympro.test", "password": "validpassword123", "code": v_code},
    )
    assert act1.status_code == 200
    assert "access_token" in act1.json()

    # 2nd activation with same code: reuse rejected!
    act2 = await client.post(
        "/api/auth/activate-admin",
        json={"email": "valid_activation@gympro.test", "password": "validpassword123", "code": v_code},
    )
    assert act2.status_code in (401, 410)


# -------------------------------------------------------------------------
# 3. Flood Limits (Max 3 Pending System-Wide, 1 Request Per Email/24h)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flood_limits(db_session: AsyncSession):
    """Verify at most 3 pending admin requests system-wide and max 1 request/day per email."""
    from app.auth.roles import create_admin_request
    await create_test_admin(db_session, email="system_boss3@gympro.test")

    # Create 3 users
    uids = []
    for i in range(4):
        uid = uuid.uuid4()
        uids.append(uid)
        async with TestSeedSession() as seed_db:
            await seed_db.execute(
                text(
                    """
                    INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
                    VALUES (:uid, :email, 'fakehash', 'User', 'USER', 'PENDING_ADMIN_CODE', NOW())
                    """
                ),
                {"uid": uid, "email": f"flood_{i}@gympro.test"},
            )
            await seed_db.commit()

    # 1. Create first 3 admin requests -> succeeds
    req1 = await create_admin_request(db_session, uids[0], "flood_0@gympro.test", "User 0")
    req2 = await create_admin_request(db_session, uids[1], "flood_1@gympro.test", "User 1")
    req3 = await create_admin_request(db_session, uids[2], "flood_2@gympro.test", "User 2")
    await db_session.commit()
    assert req1 and req2 and req3

    # 2. 4th pending request exceeds system-wide limit (3 max) -> 429 TOO_MANY_PENDING_ADMIN_REQUESTS
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await create_admin_request(db_session, uids[3], "flood_3@gympro.test", "User 3")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "TOO_MANY_PENDING_ADMIN_REQUESTS"

    # 3. Cancel one pending request
    await db_session.execute(
        text("UPDATE role_requests SET status = 'CANCELLED' WHERE id = :id"),
        {"id": req1},
    )
    await db_session.commit()

    # 4. Now user 0 trying again within 24h is blocked by ONE_REQUEST_PER_DAY
    with pytest.raises(HTTPException) as exc_info2:
        await create_admin_request(db_session, uids[0], "flood_0@gympro.test", "User 0")
    assert exc_info2.value.status_code == 429
    assert exc_info2.value.detail["error"] == "ONE_REQUEST_PER_DAY"


# -------------------------------------------------------------------------
# 4. Cooling-Off Enforcement
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cooling_off_blocks_restricted_actions(client: AsyncClient, db_session: AsyncSession):
    """Verify new admins in cooling-off are blocked from restricted actions (staff invites, decisions, broadcasts)."""
    # 1. Admin in cooling-off
    co_admin = await create_test_admin(db_session, email="cooling_admin@gympro.test", cooling_off=True)
    headers_co = {"Authorization": f"Bearer {co_admin['token']}"}

    # 2. Admin NOT in cooling-off
    mature_admin = await create_test_admin(db_session, email="mature_admin@gympro.test", cooling_off=False)
    headers_mature = {"Authorization": f"Bearer {mature_admin['token']}"}

    # Action A: Staff Invites
    res_co_inv = await client.post(
        "/api/admin/staff/invites",
        headers=headers_co,
        json={"email": "new_trainer@gympro.test", "role": "TRAINER"},
    )
    assert res_co_inv.status_code == 403
    assert res_co_inv.json()["detail"]["error"] == "COOLING_OFF_ACTIVE"

    res_mat_inv = await client.post(
        "/api/admin/staff/invites",
        headers=headers_mature,
        json={"email": "new_trainer@gympro.test", "role": "TRAINER"},
    )
    assert res_mat_inv.status_code == 200

    # Action B: Trainer Decisions
    fake_req_id = str(uuid.uuid4())
    res_co_dec = await client.post(
        f"/api/admin/trainer-requests/{fake_req_id}/decision",
        headers=headers_co,
        json={"decision": "APPROVE"},
    )
    assert res_co_dec.status_code == 403
    assert res_co_dec.json()["detail"]["error"] == "COOLING_OFF_ACTIVE"

    # Action C: Broadcasts
    res_co_bc = await client.post(
        "/api/admin/broadcasts",
        headers=headers_co,
        json={"title": "Test Broadcast", "content": "Hello"},
    )
    assert res_co_bc.status_code == 403
    assert res_co_bc.json()["detail"]["error"] == "COOLING_OFF_ACTIVE"

    # Non-restricted endpoints (e.g. GET admin requests) succeed even in cooling-off
    res_co_get = await client.get("/api/admin/admin-requests", headers=headers_co)
    assert res_co_get.status_code == 200


# -------------------------------------------------------------------------
# 5. Security Constraint: No Code Path Approves an Admin Request
# -------------------------------------------------------------------------
def test_no_code_path_approves_admin_request():
    """Verify that NO route or endpoint exists that allows manual approval of admin requests."""
    admin_routes = [r for r in app.routes if getattr(r, "path", "").startswith(("/api/admin", "/admin"))]

    for route in admin_routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        # Ensure no endpoint matches /admin-requests/{...}/approve
        assert "approve" not in path.lower() or "trainer" in path.lower(), f"Forbidden approve endpoint found: {path}"
        if "admin-requests" in path:
            # Only GET (view queue) and POST/DELETE reject/revoke are allowed
            assert "approve" not in getattr(route, "name", "").lower()

    # Verify admin_router itself has no approval function for admin requests
    import app.auth.admin_router as ar
    for attr in dir(ar):
        assert "approve_admin" not in attr.lower(), f"Forbidden admin approval function found: {attr}"


# -------------------------------------------------------------------------
# 6. Trainer Approval Flow & Privilege Escalation Guard
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trainer_approval_flow_and_reapplication_rule(client: AsyncClient, db_session: AsyncSession):
    """Verify trainer approval satisfies guard_role_change, and rejection enforces 7-day wait."""
    mature_admin = await create_test_admin(db_session, email="trainer_boss@gympro.test")
    admin_headers = {"Authorization": f"Bearer {mature_admin['token']}"}

    # 1. Create applicant
    t_uid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
                VALUES (:uid, 'applicant_trainer@gympro.test', 'pw', 'Applicant Trainer', 'USER', 'PENDING_APPROVAL', NOW())
                """
            ),
            {"uid": t_uid},
        )
        await seed_db.commit()

    from app.auth.roles import create_trainer_request
    req_id = await create_trainer_request(
        db_session,
        t_uid,
        specializations=["HIIT", "Strength"],
        claimed_certifications=["ACE"],
        bio="Experienced fitness trainer.",
    )
    await db_session.commit()

    # 2. View queue
    q_res = await client.get("/api/admin/trainer-requests", headers=admin_headers)
    assert q_res.status_code == 200
    requests = q_res.json()
    assert any(r["request_id"] == str(req_id) for r in requests)

    # 3. Approve trainer request
    app_res = await client.post(
        f"/api/admin/trainer-requests/{req_id}/decision",
        headers=admin_headers,
        json={"decision": "APPROVE", "reason": "Credentials verified"},
    )
    assert app_res.status_code == 200

    # Verify user promoted to TRAINER and ACTIVE
    chk = await db_session.execute(
        text("SELECT role, account_status FROM users WHERE id = :uid"),
        {"uid": t_uid},
    )
    t_row = chk.mappings().one()
    assert t_row["role"] == "TRAINER"
    assert t_row["account_status"] == "ACTIVE"

    # Verify trainer_profiles row created
    p_chk = await db_session.execute(
        text("SELECT specializations FROM trainer_profiles WHERE trainer_id = :uid"),
        {"uid": t_uid},
    )
    assert p_chk.scalar_one() == ["HIIT", "Strength"]

    # 4. Test Rejection & 7-Day Reapply Rule
    rej_uid = uuid.uuid4()
    async with TestSeedSession() as seed_db:
        await seed_db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
                VALUES (:uid, 'rejected_trainer@gympro.test', 'pw', 'Rejected Trainer', 'USER', 'PENDING_APPROVAL', NOW())
                """
            ),
            {"uid": rej_uid},
        )
        await seed_db.commit()

    rej_req = await create_trainer_request(db_session, rej_uid)
    await db_session.commit()

    # Reject
    await client.post(
        f"/api/admin/trainer-requests/{rej_req}/decision",
        headers=admin_headers,
        json={"decision": "REJECT", "reason": "Insufficient experience"},
    )

    # Reapplying immediately raises 400 REJECTED_WAIT_7_DAYS
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await create_trainer_request(db_session, rej_uid)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "REJECTED_WAIT_7_DAYS"


# -------------------------------------------------------------------------
# 7. Staff Invite Flow (Decision 16)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_staff_trainer_invites_and_acceptance(client: AsyncClient, db_session: AsyncSession):
    """Verify admin can invite trainers, admin invites are refused, and acceptance promotes user safely."""
    mature_admin = await create_test_admin(db_session, email="invite_boss@gympro.test")
    admin_headers = {"Authorization": f"Bearer {mature_admin['token']}"}

    # 1. Admin invites are prohibited in v1
    adm_inv = await client.post(
        "/api/admin/staff/invites",
        headers=admin_headers,
        json={"email": "attempt_admin@gympro.test", "role": "ADMIN"},
    )
    assert adm_inv.status_code == 400
    assert adm_inv.json()["detail"]["error"] == "ADMIN_INVITES_DISABLED"

    # 2. Trainer invite succeeds
    tr_email = "invited_coach@gympro.test"
    inv_res = await client.post(
        "/api/admin/staff/invites",
        headers=admin_headers,
        json={"email": tr_email, "role": "TRAINER"},
    )
    assert inv_res.status_code == 200
    token = inv_res.json()["token"]
    assert token is not None

    # 3. Invited trainer accepts invite
    acc_res = await client.post(
        "/api/auth/accept-invite",
        json={
            "token": token,
            "password": "validpassword123",
            "full_name": "Invited Coach",
            "phone": "+919876543210",
        },
    )
    assert acc_res.status_code == 200
    data = acc_res.json()
    assert data["role"] == "TRAINER"
    assert data["status"] == "ACTIVE"

    # Verify user in DB is TRAINER and ACTIVE
    u_chk = await db_session.execute(
        text("SELECT role, account_status FROM users WHERE email = :email"),
        {"email": tr_email},
    )
    row = u_chk.mappings().one()
    assert row["role"] == "TRAINER"
    assert row["account_status"] == "ACTIVE"


# -------------------------------------------------------------------------
# 8. Nightly Expiry Hygiene
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nightly_expiry_job(db_session: AsyncSession):
    """Verify expiry job cancels stale role requests and unverified accounts."""
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    # Stale trainer request (>14 days)
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status)
            VALUES (:u1, 'stale_tr@gympro.test', 'pw', 'Stale TR', 'USER', 'PENDING_APPROVAL')
            """
        ),
        {"u1": u1},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO role_requests (user_id, requested_role, status, created_at, expires_at)
            VALUES (:u1, 'TRAINER', 'PENDING', NOW() - INTERVAL '15 days', NOW() - INTERVAL '1 day')
            """
        ),
        {"u1": u1},
    )

    # Stale unverified user (>7 days)
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status, created_at)
            VALUES (:u2, 'stale_unverified@gympro.test', 'pw', 'Stale Unverified', 'USER', 'PENDING_EMAIL', NOW() - INTERVAL '8 days')
            """
        ),
        {"u2": u2},
    )
    await db_session.commit()

    # Run expiry job
    counts = await run_expiry_jobs(db_session)
    assert counts["expired_trainer_requests"] >= 1
    assert counts["expired_unverified_users"] >= 1

    # Verify status changed in DB
    chk1 = await db_session.execute(text("SELECT status FROM role_requests WHERE user_id = :u1"), {"u1": u1})
    assert chk1.scalar_one() == "EXPIRED"

    chk2 = await db_session.execute(text("SELECT account_status FROM users WHERE id = :u2"), {"u2": u2})
    assert chk2.scalar_one() == "EXPIRED"
