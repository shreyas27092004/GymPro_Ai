# app/auth/security.py
import hashlib
import hmac
import re
import secrets
import time
import bcrypt
import jwt
from ..settings import settings

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # unambiguous: no 0/O/1/I/L

# Precomputed dummy hash for constant-time password checks
DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(12)).decode()


def hash_password(pw: str) -> str:
    b = pw.encode("utf-8")
    if not (10 <= len(b) <= 72):
        raise ValueError("Password must be between 10 and 72 bytes")
    return bcrypt.hashpw(b, bcrypt.gensalt(12)).decode()


def verify_password(pw: str, hashed: str | None) -> bool:
    """Equal-time password verification: always run bcrypt even if user does not exist."""
    b = pw.encode("utf-8")[:72]
    target = hashed if (hashed and hashed.startswith("$2")) else DUMMY_HASH
    try:
        match = bcrypt.checkpw(b, target.encode("utf-8"))
    except Exception:
        match = False
    return match and (hashed is not None)


def new_token() -> tuple[str, str]:
    """Generate a random 32-byte URL-safe token and its SHA-256 hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_admin_code() -> tuple[str, str]:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    code_hmac = hmac.new(
        settings.token_hmac_secret.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return code, code_hmac


def code_matches(code: str, code_hmac: str | None) -> bool:
    if not code or not code_hmac:
        return False
    calc = hmac.new(
        settings.token_hmac_secret.encode("utf-8"),
        code.strip().upper().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(calc, code_hmac)


def normalize_phone(phone: str) -> str:
    return re.sub(r"[^\d+]", "", phone.strip())


def phone_hash(phone: str) -> str:
    normalized = normalize_phone(phone)
    return hmac.new(
        settings.token_hmac_secret.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_access_token(
    user_id: str,
    token_version: int,
    expires_in_seconds: int = 900,
) -> str:
    """Create RS256 JWT access token with 15-minute lifetime."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "aud": "gympro",
        "ver": token_version,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    return jwt.encode(
        payload,
        settings.formatted_jwt_private_key,
        algorithm="RS256",
    )


def decode_access_token(token: str) -> dict:
    """Decode and verify RS256 JWT access token."""
    # Strict validation: algorithms explicitly restricted to RS256, audience="gympro"
    return jwt.decode(
        token,
        settings.formatted_jwt_public_key,
        algorithms=["RS256"],
        audience="gympro",
    )
