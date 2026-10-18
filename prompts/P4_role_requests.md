# Phase P4: Role requests

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Trainer request queue and decisions, admin one-time code flow, seed command `python -m app.seed_admin`, cooling-off, trainer invite flow (decision 16), nightly expiry

## Gate (must pass before you stop)
`pytest tests/roles -q` at 100%: wrong, expired, reused code; five attempts lock; flood limits; no-admin bootstrap; at most 3 pending admin requests; cooling-off blocks restricted actions; no code path approves an admin request

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P5.

---

# Spec sections for this phase (copied from the full spec)

### 4.2 Trainer approval flow

1. Trainer registers and verifies the email. A `role_request` (TRAINER) and a `trainer_applications` row are created.
2. Admins see a **New trainer requests** queue with a live badge: name, verified email, phone, specializations, claimed certifications, bio, sign-up time, and risk hints (duplicate phone, disposable email domain).
3. Admin picks **Approve**, **Reject** (with reason) or **Ask for more information**. Each decision is a confirm-then-execute action with an audit entry. Decisions work from the dashboard or through ADMIN_INSIGHTS (propose, confirm).
4. The trainer gets an email with the decision. Approval activates the account; it does **not** mark certifications as verified. Verification is a separate badge and unverified credentials are never shown to users. (Configurable: classes of unverified trainers stay in draft until verified.)
5. Admins are told by the in-app badge and a **batched** digest email, not one email per sign-up.
6. Requests expire after 14 days. A rejected applicant waits 7 days before applying again.

---

### 4.3 Admin approval flow (one-time code)

1. The registrant verifies the email and sees "Waiting for an existing admin". The system creates a `role_request` (ADMIN) and an **8-character code**, stored only as an HMAC hash.
2. The code is emailed to **every active admin**, together with who is asking (name, verified email, time, approximate location) and a link to reject the request in the dashboard.
3. An admin who recognizes the person gives them the code. The registrant enters **email + password + code** on the activation screen.
4. Rules: single use, 30 minute expiry, bound to that request, 5 wrong attempts lock the request, a new request invalidates the older one, rate limits per IP and per email, at most 3 pending admin requests in the whole system, one request per email per 24 hours.
5. On success: the role becomes ADMIN, all admins get a "new admin added" email, an audit entry is written, and any admin can **suspend** the new admin during a cooling-off period (default 24 h) in which the new admin cannot invite staff, approve role requests, grant memberships or send broadcasts.
6. **Bootstrap:** the very first admin is created only by the seed command (a dedicated DB role). While no active admin exists, admin sign-up is unavailable.
7. Admin requests can never be approved through an AI agent. Only the code flow and the dashboard reject or revoke actions exist.

**Why this is safe enough, and where it is not.** The code proves an existing admin chose to share it, and the registrant owns a verified mailbox. It is only as strong as the admins' mailboxes. Recommended hardening: authenticator-app MFA for admins, an optional allowed-email-domain list for admin sign-up, a captcha on the sign-up form, and an optional quorum (for example 2 admins) before a code is released.

---

### 8.14 Authentication service (registration, login, refresh, reset, role requests)

```python
# app/auth/security.py
import hashlib, hmac, secrets, bcrypt
from ..settings import settings

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # no 0/O/1/I/L

def hash_password(pw: str) -> str:
    b = pw.encode()
    if not (10 <= len(b) <= 72):
        raise ValueError("password length")
    return bcrypt.hashpw(b, bcrypt.gensalt(12)).decode()

DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(12)).decode()

def verify_password(pw: str, hashed: str | None) -> bool:
    # equal-time: always run bcrypt, even when the user does not exist
    return bcrypt.checkpw(pw.encode()[:72], (hashed or DUMMY_HASH).encode()) and hashed is not None

def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()           # store only the hash

def sha256(raw: str) -> str: return hashlib.sha256(raw.encode()).hexdigest()

def new_admin_code() -> tuple[str, str]:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return code, hmac.new(settings.token_hmac_secret.encode(), code.encode(), "sha256").hexdigest()

def code_matches(code: str, code_hmac: str) -> bool:
    calc = hmac.new(settings.token_hmac_secret.encode(), code.strip().upper().encode(), "sha256").hexdigest()
    return hmac.compare_digest(calc, code_hmac)

def phone_hash(phone: str) -> str:
    return hmac.new(settings.token_hmac_secret.encode(), normalize_phone(phone).encode(), "sha256").hexdigest()
```

```python
# app/auth/service.py (reference, condensed: complete every function; each runs in one transaction)
async def register(db, body: RegisterBody, ip: str):
    await rate_limit_check(f"register:ip:{ip}", 10, 3600); await rate_limit_check(f"register:email:{body.email}", 3, 3600)
    if body.account_type == "ADMIN" and not await any_active_admin(db):
        raise HTTPException(403, "ADMIN_SIGNUP_UNAVAILABLE")                    # bootstrap is seed-only
    if await email_exists(db, body.email):
        await enqueue(db, user_id=None, routing_key="email.already_registered", template="ALREADY_REGISTERED",
                      params={"email": body.email}, dedupe_key=f"dup:{body.email}:{today()}")   # same API response either way
        return {"ok": True}
    user = User(email=body.email, password_hash=hash_password(body.password), full_name=body.full_name,
                role="USER",                                                    # NEVER taken from the client
                requested_role=None if body.account_type == "USER" else body.account_type,
                account_status="PENDING_EMAIL", phone=body.phone, phone_hash=phone_hash(body.phone) if body.phone else None)
    db.add(user); await db.flush()
    if body.account_type == "TRAINER":
        stash_trainer_application(db, user, body)                              # kept until verification creates the role_request
    raw, h = new_token()
    db.add(EmailVerification(user_id=user.id, token_hash=h, expires_at=in_hours(24)))
    await enqueue(db, user_id=user.id, routing_key="email.verify", template="VERIFY_EMAIL",
                  params={"link": f"{settings.frontend_url}/verify?token={raw}"}, dedupe_key=f"verify:{user.id}:{h[:8]}")
    return {"ok": True}                                                         # identical response whether or not the email existed

async def verify_email(db, raw_token: str):
    row = await get_verification(db, sha256(raw_token), for_update=True)
    if not row or row.used_at or row.expires_at < utcnow():
        raise HTTPException(400, "INVALID_OR_EXPIRED_TOKEN")
    row.used_at = utcnow()
    u = await get_user(db, row.user_id, for_update=True)
    u.email_verified_at = utcnow()
    if u.requested_role is None:
        u.account_status = "ACTIVE"
        await start_trial(db, u)                                                # unique per user and phone_hash; skipped on conflict
    elif u.requested_role == "TRAINER":
        u.account_status = "PENDING_APPROVAL"
        await create_trainer_request(db, u)                                     # role_requests + trainer_applications + risk hints
    else:
        u.account_status = "PENDING_ADMIN_CODE"
        await create_admin_request(db, u)                                       # code, emails to every active admin
    return {"status": u.account_status}

async def login(db, email: str, password: str, ip: str):
    await rate_limit_check(f"login:ip:{ip}", 30, 600); await rate_limit_check(f"login:email:{email}", 10, 600)
    u = await get_user_by_email(db, email)
    ok = verify_password(password, u.password_hash if u else None)
    if u and u.locked_until and u.locked_until > utcnow():
        raise HTTPException(429, "TRY_LATER")
    if not (u and ok):
        if u:
            u.failed_logins += 1
            if u.failed_logins >= 5:
                u.locked_until = utcnow() + backoff(u.failed_logins)
        raise HTTPException(401, "INVALID_CREDENTIALS")                         # never reveals account state on a wrong password
    u.failed_logins, u.locked_until = 0, None
    if not u.email_verified_at:
        raise HTTPException(403, {"error": "EMAIL_NOT_VERIFIED"})
    if u.account_status in ("PENDING_APPROVAL", "PENDING_ADMIN_CODE", "REJECTED", "EXPIRED", "SUSPENDED"):
        raise HTTPException(403, {"error": "ACCOUNT_" + u.account_status,
                                  "show_code_box": u.account_status == "PENDING_ADMIN_CODE"})   # password was correct, so state may be shown
    return await issue_tokens(db, u, ip)                                         # access JWT + refresh cookie (new family)

async def refresh(db, raw_refresh: str, ip: str):
    row = await get_refresh(db, sha256(raw_refresh), for_update=True)
    if not row or row.revoked_at or row.expires_at < utcnow():
        raise HTTPException(401)
    if row.rotated_at:                                                           # reuse of an old token: assume theft
        await revoke_family(db, row.family_id)
        await audit(db, None, "REFRESH_REUSE_DETECTED", "refresh_tokens", row.id)
        raise HTTPException(401)
    row.rotated_at = utcnow()
    return await issue_tokens(db, await get_user(db, row.user_id), ip, family_id=row.family_id)

async def forgot_password(db, email: str, ip: str):
    await rate_limit_check(f"forgot:ip:{ip}", 10, 3600); await rate_limit_check(f"forgot:email:{email}", 3, 3600)
    u = await get_user_by_email(db, email)
    if u and u.email_verified_at:
        await expire_active_resets(db, u.id)                                    # one active per user
        raw, h = new_token()
        db.add(PasswordReset(user_id=u.id, token_hash=h, expires_at=in_minutes(30)))
        await enqueue(db, user_id=u.id, routing_key="email.reset", template="RESET_PASSWORD",
                      params={"link": f"{settings.frontend_url}/reset?token={raw}"}, dedupe_key=f"reset:{u.id}:{h[:8]}")
    return {"ok": True}                                                          # always the same response

async def reset_password(db, raw_token: str, new_password: str):
    row = await get_reset(db, sha256(raw_token), for_update=True)
    if not row or row.used_at or row.expires_at < utcnow():
        raise HTTPException(400, "INVALID_OR_EXPIRED_TOKEN")
    row.used_at = utcnow()
    u = await get_user(db, row.user_id, for_update=True)
    u.password_hash = hash_password(new_password); u.token_version += 1          # kills access tokens
    await revoke_all_refresh(db, u.id)
    await enqueue(db, user_id=u.id, routing_key="email.password_changed", template="PASSWORD_CHANGED", params={}, dedupe_key=f"pwchg:{u.id}:{row.id}")
```

```python
# app/auth/roles.py
async def create_trainer_request(db, user):
    hints = {"duplicate_phone": await phone_seen_elsewhere(db, user), "disposable_email": is_disposable(user.email)}
    req = RoleRequest(user_id=user.id, requested_role="TRAINER", expires_at=in_days(14))
    db.add(req); await db.flush()
    db.add(TrainerApplication(request_id=req.id, risk_hints=hints, **user.stashed_application))
    await enqueue_admin_badge(db)                                               # in-app badge; batched digest, not one email per sign-up

async def create_admin_request(db, user):
    if await pending_admin_requests(db) >= settings_int(db, "admin_pending_max"):
        raise HTTPException(429, "TOO_MANY_PENDING_ADMIN_REQUESTS")
    if await admin_request_in_last_24h(db, user.email):
        raise HTTPException(429, "ONE_REQUEST_PER_DAY")
    await cancel_older_pending(db, user.id)                                      # a new request invalidates the older one
    code, code_hmac = new_admin_code()
    req = RoleRequest(user_id=user.id, requested_role="ADMIN", code_hmac=code_hmac,
                      code_expires_at=in_minutes(30), expires_at=in_minutes(30), request_ip_hash=ip_hash())
    db.add(req); await db.flush()
    for admin in await active_admins(db):                                        # the code goes to EVERY active admin, and is never logged
        await enqueue(db, user_id=admin.id, routing_key="email.admin_code", template="ADMIN_CODE",
                      params={"code": code, "name": user.full_name, "email": user.email, "when": iso_now(), "approx_location": geo_hint(),
                              "reject_link": f"{settings.frontend_url}/admin/requests/{req.id}"},
                      dedupe_key=f"admin-code:{req.id}:{admin.id}")

async def activate_admin(db, email: str, password: str, code: str, ip: str):
    await rate_limit_check(f"activate:ip:{ip}", 10, 3600); await rate_limit_check(f"activate:email:{email}", 10, 3600)
    u = await get_user_by_email(db, email, for_update=True)
    if not u or not verify_password(password, u.password_hash) or u.account_status != "PENDING_ADMIN_CODE":
        raise HTTPException(401, "INVALID_CREDENTIALS")
    req = await pending_request(db, u.id, "ADMIN", for_update=True)
    if not req or req.code_expires_at < utcnow():
        if req: req.status = "EXPIRED"
        u.account_status = "EXPIRED"
        raise HTTPException(410, "CODE_EXPIRED")
    if req.attempts >= settings_int(db, "admin_code_max_attempts"):
        req.status = "CANCELLED"; u.account_status = "EXPIRED"
        raise HTTPException(423, "REQUEST_LOCKED")
    if not code_matches(code, req.code_hmac):
        req.attempts += 1
        raise HTTPException(401, "INVALID_CODE")
    req.status, req.decided_at, req.code_hmac = "APPROVED", utcnow(), None        # single use: the hash is destroyed
    await db.flush()
    await db.execute(text("UPDATE users SET role='ADMIN', account_status='ACTIVE', cooling_off_until = now() + make_interval(hours => :h) WHERE id=:u"),
                     {"u": u.id, "h": settings_int(db, "admin_cooling_off_hours")})   # trigger satisfied by the APPROVED request
    await audit(db, u.id, "ADMIN_ACTIVATED", "users", u.id)
    for admin in await active_admins(db):
        await enqueue(db, user_id=admin.id, routing_key="email.admin_added", template="NEW_ADMIN_ADDED",
                      params={"name": u.full_name}, dedupe_key=f"admin-added:{u.id}:{admin.id}")
    return await issue_tokens(db, u, ip)
```

**Seed command (the only way to create the first admin):** `python -m app.seed_admin --email you@example.com` connects as `gympro_seed`, refuses to run if any active admin exists, prompts for a password (never an argument), inserts the user with `role='ADMIN'`, `account_status='ACTIVE'` and writes an audit row.

**Cooling-off enforcement:** `SessionContext.cooling_off_active = cooling_off_until > now()`. Tool registry blocks `blocked_in_cooling_off` tools and the executor rejects `ADMIN_ONLY` actions. REST endpoints for invite, role-request decisions, grants and broadcasts use a `require_not_cooling_off` dependency. Any active admin can suspend a new admin from the Security screen.

**Rate limit helper:** implement `app/ratelimit.py` as an in-process limiter behind `check(key, limit, window_s)`, acceptable for a single API worker. A Redis implementation can replace it later without touching callers. All limits above are per IP and per email as stated in the flows.

---

## 17. REST API catalog

All endpoints are under `/api`. "Active" means the caller has `account_status = ACTIVE`. Public endpoints are rate limited per IP and per email.

| Method and path | Role | Purpose |
| :--- | :--- | :--- |
| `POST /auth/register` | Public | Create account (USER, TRAINER or ADMIN request). Same response whether or not the email exists |
| `POST /auth/verify-email` | Public | Consume the verification token; moves the account to its next state |
| `POST /auth/login` | Public | Email and password only; returns access token, sets refresh cookie |
| `POST /auth/activate-admin` | Public | Email, password and one-time code for admin sign-ups |
| `POST /auth/refresh` | Public (cookie) | Rotate refresh token |
| `POST /auth/logout` | Active | Revoke the refresh family |
| `POST /auth/forgot-password`, `POST /auth/reset-password` | Public | Reset flow; all sessions revoked on success |
| `GET /me` | Active | Role, status, plan, consent flags, cooling-off flag |
| `GET/PUT /me/intake`, `POST /me/consent`, `DELETE /me/consent` | USER | Intake sections, health-data consent and withdrawal |
| `GET /me/memory`, `POST /me/export`, `DELETE /me/data` | USER | What the AI remembers, export, delete |
| `GET /plans`, `GET /trainers`, `GET /classes` | Active | Browse catalog (trainers show verified credentials only) |
| `GET /me/bookings`, `GET /me/membership`, `GET /me/trial` | USER | Own data |
| `POST /agent/chat` | Active | Text or voice transcript to the agent pipeline |
| `POST /actions/{id}/confirm` | Active (owner) | Execute one proposed action |
| `POST /bundles/{id}/confirm` | Active (owner) | Execute a bundle in order; may return `AWAITING_PAYMENT` with a checkout object |
| `POST /payments/razorpay/verify` | USER (owner of the order) | Verify the Checkout signature and finalize the payment |
| `GET /payments/{id}`, `POST /payments/{id}/cancel` | USER (owner) | Payment status and reopen data; abandon an unpaid order |
| `POST /payments/razorpay/webhook` | Public (HMAC signature only) | Razorpay events: captured, failed, refund processed. Deduplicated by event id |
| `GET /admin/payments?status=NEEDS_REVIEW` | ADMIN | Review queue for late or inconsistent payments |
| `POST /feedback` | USER | Class, trainer or answer feedback |
| `GET /notifications`, `POST /notifications/{id}/read`, `GET /notifications/stream` | Active | In-app notices and SSE stream |
| `GET/PUT /trainer/availability`, `POST /trainer/time-off` | TRAINER | Own availability |
| `GET /trainer/classes`, `GET /trainer/classes/{id}/roster`, `POST /trainer/classes/{id}/attendance` | TRAINER | Own classes, first-name rosters, attendance |
| `POST /trainer/series/preview` | TRAINER | Preview recurring series |
| `GET /admin/overview`, `GET /admin/metrics/{name}` | ADMIN | KPIs and catalog metrics |
| `GET /admin/trainer-requests`, `POST /admin/trainer-requests/{id}/decision` | ADMIN (not in cooling-off for decisions) | Queue and decisions (approve, reject with reason, ask for more information) |
| `GET /admin/admin-requests`, `POST /admin/admin-requests/{id}/reject`, `POST /admin/users/{id}/suspend` | ADMIN | Reject or revoke admin requests; suspend new admins. **No approve endpoint exists** |
| `GET /admin/issues`, `PATCH /admin/issues/{id}` | ADMIN | Triage |
| `POST /admin/staff/invites`, `POST /admin/broadcasts/preview`, `POST /admin/broadcasts` | ADMIN (not in cooling-off) | Invites and announcements (broadcast sending goes through confirm) |
| `GET /admin/security-log` | ADMIN | New admins, approvals, failed codes, suspensions |
| `GET /health`, `GET /ready` | Public | Liveness and readiness (DB, RabbitMQ, LLM) |

**Error code catalog (stable strings returned in `detail.error`)**

| Code | Meaning |
| :--- | :--- |
| `INVALID_CREDENTIALS`, `TRY_LATER` | Wrong login, lockout |
| `EMAIL_NOT_VERIFIED`, `ACCOUNT_PENDING_APPROVAL`, `ACCOUNT_PENDING_ADMIN_CODE`, `ACCOUNT_REJECTED`, `ACCOUNT_EXPIRED`, `ACCOUNT_SUSPENDED` | Account state after a correct password |
| `INVALID_OR_EXPIRED_TOKEN`, `INVALID_CODE`, `CODE_EXPIRED`, `REQUEST_LOCKED` | Token and code problems |
| `ADMIN_SIGNUP_UNAVAILABLE`, `TOO_MANY_PENDING_ADMIN_REQUESTS`, `ONE_REQUEST_PER_DAY` | Admin sign-up limits |
| `ACTION_EXPIRED`, `PRICE_CHANGED`, `CLASS_FULL`, `CONFLICT`, `NO_ENTITLEMENT`, `RULE_FAILED`, `ALREADY_BOOKED`, `CLASS_UNAVAILABLE` | Executor business errors |
| `DEPENDENCY_FAILED` | Bundle step skipped |
| `PAYMENT_PROVIDER_REQUIRED` | Payments disabled, or `mock` in production |
| `PAYMENT_SIGNATURE_INVALID`, `PAYMENT_FAILED`, `PAYMENT_EXPIRED`, `PAYMENT_CANCELLED`, `PAYMENT_NEEDS_REVIEW` | Payment outcomes |
| `REPORT_LIMIT_REACHED`, `EMAIL_CAP_REACHED` | Daily caps |
| `COOLING_OFF_ACTIVE`, `FORBIDDEN`, `CONSENT_REQUIRED`, `TOOL_NOT_ALLOWED` | Authorization |
