import time
import uuid
import jwt
import pytest
from httpx import AsyncClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.security import create_access_token, hash_password
from app.settings import settings


# Helper to create a verified active user in DB
async def create_active_user(
    db: AsyncSession,
    email: str = "active_user@gympro.test",
    password: str = "securepassword123",
    role: str = "USER",
) -> tuple[uuid.UUID, str]:
    uid = uuid.uuid4()
    pw_hash = hash_password(password)
    async with db.begin():
        await db.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
                VALUES (:id, :email, :pw, 'Test User', :role, 'ACTIVE', NOW())
                """
            ),
            {"id": uid, "email": email, "pw": pw_hash, "role": role},
        )
    return uid, password


@pytest.mark.asyncio
async def test_token_rejections(client: AsyncClient, db_session: AsyncSession):
    """Verify forged, alg:none, expired, and wrong-audience tokens are rejected."""
    uid, _ = await create_active_user(db_session, "token_test@gympro.test")

    # 1. Forged token: valid RS256 structure but signed with an untrusted private key
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign_pem = foreign_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    forged_token = jwt.encode(
        {"sub": str(uid), "aud": "gympro", "ver": 0, "exp": int(time.time()) + 900},
        foreign_pem,
        algorithm="RS256",
    )
    res_forged = await client.get("/api/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert res_forged.status_code == 401
    assert "Invalid token" in res_forged.text

    # 2. alg:none token
    alg_none_token = jwt.encode(
        {"sub": str(uid), "aud": "gympro", "ver": 0, "exp": int(time.time()) + 900},
        key="",
        algorithm="none",
    )
    res_none = await client.get("/api/me", headers={"Authorization": f"Bearer {alg_none_token}"})
    assert res_none.status_code == 401

    # 3. Expired token
    expired_token = jwt.encode(
        {"sub": str(uid), "aud": "gympro", "ver": 0, "exp": int(time.time()) - 3600},
        settings.formatted_jwt_private_key,
        algorithm="RS256",
    )
    res_expired = await client.get("/api/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res_expired.status_code == 401
    assert "expired" in res_expired.text.lower()

    # 4. Wrong audience token
    wrong_aud_token = jwt.encode(
        {"sub": str(uid), "aud": "malicious_service", "ver": 0, "exp": int(time.time()) + 900},
        settings.formatted_jwt_private_key,
        algorithm="RS256",
    )
    res_aud = await client.get("/api/me", headers={"Authorization": f"Bearer {wrong_aud_token}"})
    assert res_aud.status_code == 401
    assert "audience" in res_aud.text.lower() or "invalid token" in res_aud.text.lower()

    # 5. Valid token succeeds
    valid_token = create_access_token(str(uid), 0)
    res_valid = await client.get("/api/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert res_valid.status_code == 200
    data = res_valid.json()
    assert data["user_id"] == str(uid)
    assert data["role"] == "USER"


@pytest.mark.asyncio
async def test_role_injection_at_registration_ignored(client: AsyncClient, db_session: AsyncSession):
    """Verify role injection in registration payload is completely ignored."""
    payload = {
        "email": "injected@gympro.test",
        "password": "validpassword123",
        "full_name": "Injected Attacker",
        "role": "ADMIN",
        "account_type": "USER",
    }
    res = await client.post("/api/auth/register", json=payload)
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # Verify role in DB is USER, not ADMIN
    async with db_session.begin():
        row = (
            await db_session.execute(
                text("SELECT role, requested_role, account_status FROM users WHERE email = :email"),
                {"email": payload["email"]},
            )
        ).mappings().one()
        assert row["role"] == "USER"
        assert row["requested_role"] is None
        assert row["account_status"] == "PENDING_EMAIL"


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_the_family(client: AsyncClient, db_session: AsyncSession):
    """Verify reuse of an already-rotated refresh token revokes the entire token family."""
    email = "family_reuse@gympro.test"
    password = "validpassword123"
    await create_active_user(db_session, email=email, password=password)

    # 1. Login to obtain access token and initial refresh token
    login_res = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200
    tokens1 = login_res.json()
    rf1 = tokens1["refresh_token"]

    # 2. First refresh with rf1: succeeds and issues rf2
    ref_res1 = await client.post("/api/auth/refresh", json={"refresh_token": rf1})
    assert ref_res1.status_code == 200
    tokens2 = ref_res1.json()
    rf2 = tokens2["refresh_token"]
    assert rf2 != rf1

    # 3. Reuse rf1 (already rotated): triggers theft detection and revokes family
    reuse_res = await client.post("/api/auth/refresh", json={"refresh_token": rf1})
    assert reuse_res.status_code == 401
    assert "reuse detected" in reuse_res.text.lower() or "revoked" in reuse_res.text.lower()

    # 4. Now rf2 in the same family must ALSO be rejected because the whole family is revoked
    subsequent_res = await client.post("/api/auth/refresh", json={"refresh_token": rf2})
    assert subsequent_res.status_code == 401


@pytest.mark.asyncio
async def test_no_account_enumeration(client: AsyncClient, db_session: AsyncSession):
    """Verify registration, forgot-password, and login do not leak whether an account exists."""
    existing_email = "existing_enum@gympro.test"
    nonexistent_email = "nonexistent_enum@gympro.test"
    password = "validpassword123"

    await create_active_user(db_session, email=existing_email, password=password)

    # 1. Registration endpoint: duplicate returns identical response
    reg_existing = await client.post(
        "/api/auth/register",
        json={"email": existing_email, "password": "anotherpassword123", "full_name": "Duplicate User"},
    )
    reg_new = await client.post(
        "/api/auth/register",
        json={"email": "brandnew@gympro.test", "password": "anotherpassword123", "full_name": "New User"},
    )
    assert reg_existing.status_code == 200
    assert reg_new.status_code == 200
    assert reg_existing.json() == reg_new.json() == {"ok": True}

    # 2. Forgot-password endpoint: existing vs non-existent return identical response
    fp_existing = await client.post("/api/auth/forgot-password", json={"email": existing_email})
    fp_nonexistent = await client.post("/api/auth/forgot-password", json={"email": nonexistent_email})
    assert fp_existing.status_code == 200
    assert fp_nonexistent.status_code == 200
    assert fp_existing.json() == fp_nonexistent.json() == {"ok": True}

    # 3. Login endpoint: wrong password on existing vs wrong email return identical 401 error
    login_wrong_pw = await client.post(
        "/api/auth/login",
        json={"email": existing_email, "password": "wrongpassword123"},
    )
    login_wrong_email = await client.post(
        "/api/auth/login",
        json={"email": nonexistent_email, "password": "wrongpassword123"},
    )
    assert login_wrong_pw.status_code == 401
    assert login_wrong_email.status_code == 401
    assert login_wrong_pw.json() == login_wrong_email.json() == {"detail": {"error": "INVALID_CREDENTIALS"}}


@pytest.mark.asyncio
async def test_equal_time_login(client: AsyncClient, db_session: AsyncSession):
    """Verify login executes bcrypt password hashing even when user does not exist (equal-time)."""
    existing_email = "timing_test@gympro.test"
    nonexistent_email = "nonexistent_timing@gympro.test"
    await create_active_user(db_session, email=existing_email, password="validpassword123")

    # Warm-up bcrypt
    await client.post("/api/auth/login", json={"email": nonexistent_email, "password": "wrongpassword123"})

    # Measure existing user with wrong password
    t0 = time.perf_counter()
    res1 = await client.post("/api/auth/login", json={"email": existing_email, "password": "wrongpassword123"})
    dur1 = time.perf_counter() - t0
    assert res1.status_code == 401

    # Measure non-existent email
    t0 = time.perf_counter()
    res2 = await client.post("/api/auth/login", json={"email": nonexistent_email, "password": "wrongpassword123"})
    dur2 = time.perf_counter() - t0
    assert res2.status_code == 401

    # Bcrypt takes ~0.15s - 0.4s for 12 rounds. Both durations should be within a 3x ratio
    # If nonexistent email skipped bcrypt, it would return in < 0.005s (a 50x+ difference)
    ratio = max(dur1, dur2) / max(min(dur1, dur2), 0.001)
    assert ratio < 3.0, f"Login timing discrepancy too high: dur1={dur1:.4f}s, dur2={dur2:.4f}s, ratio={ratio:.2f}"


@pytest.mark.asyncio
async def test_lockout(client: AsyncClient, db_session: AsyncSession):
    """Verify account locks after 5 failed login attempts with 429 TRY_LATER."""
    email = "lockout_user@gympro.test"
    password = "correctpassword123"
    await create_active_user(db_session, email=email, password=password)

    # 4 failed attempts should return 401
    for _ in range(4):
        res = await client.post("/api/auth/login", json={"email": email, "password": "badpassword"})
        assert res.status_code == 401
        assert res.json() == {"detail": {"error": "INVALID_CREDENTIALS"}}

    # 5th failed attempt should trigger lockout and return 401
    res5 = await client.post("/api/auth/login", json={"email": email, "password": "badpassword"})
    assert res5.status_code == 401

    # 6th attempt (even with correct password!) must return 429 TRY_LATER
    res6 = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert res6.status_code == 429
    assert res6.json() == {"detail": {"error": "TRY_LATER"}}
