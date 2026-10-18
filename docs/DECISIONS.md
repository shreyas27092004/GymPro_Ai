# GymPro AI: Architecture & Design Decisions

This document records architectural decisions, resolutions of ambiguities, and implementation notes in accordance with `prompts/00_CORE.md` section 0.

## Locked Decisions (from Spec 0.3)
1. **Roles:** `USER`, `TRAINER`, `ADMIN`
2. **Agents:** 10 agents (SCHEDULE, MEMBERSHIP, FITNESS, WELLNESS, NUTRITION, TRAINER_INFO, SUPPORT, COMMS, TRAINER_OPS, ADMIN_INSIGHTS) + Supervisor (input guard, planner, bundle builder, synthesizer).
3. **Writes:** Each agent proposes at most one write per step; max 5 write steps per bundle.
4. **Planner:** Plan is a DAG with `depends_on`. Max 4 waves, max 6 agents. Rules fast path first, LLM fallback. Agents inside a wave run sequentially in v1.
5. **Orchestration:** LangGraph `StateGraph` without checkpointer in v1. Boundary is the database (`pending_actions`, `action_bundles`).
6. **Notifications:** Deterministic system templates. COMMS only proposes user-requested emails to verified addresses via outbox -> RabbitMQ -> worker -> SMTP.
7. **Admin copilot:** ADMIN_INSIGHTS uses metric catalog only (no free SQL). Never acts on admin-role requests.
8. **Member data:** `member_profiles` (current state) + append-only `member_intake_versions`.
9. **Account state:** `account_status` only (no `is_active`). Login succeeds only when `ACTIVE`.
10. **Tokens:** RS256 access JWT (15 min) + opaque refresh token (7 days) with rotation and reuse detection.
11. **Trial:** 3 classes within 14 days, once per person.
12. **Payments:** Razorpay Orders API + Checkout behind `PaymentProvider` adapter (`mock` mode for tests/keyless demos, prohibited in production).
13. **Downgrades:** Staff-handled at renewal. No downgrade tool in v1.
14. **Bundles:** Step-level transactions; failed step skips dependents; independent steps continue.
15. **Admin activation:** One-time code to all active admins; cooling-off 24h.
16. **Staff invites:** TRAINER invites only; ADMIN invites do not exist in v1.
17. **Unverified trainers:** Classes stay visible without credentials; `require_verified_trainer_for_publish` defaults to false.
18. **Reports to admin:** Trainer is never contacted or informed of reporter identity.
19. **Voice:** Browser Web Speech APIs. Voice never confirms an action.
20. **Rate limiting:** In-process limiter behind `check(key, limit, window_s)` interface.
21. **Vector store:** ChromaDB persistent client with default embedding function.
22. **Currency:** INR (paise for Razorpay), NUMERIC in DB.
23. **Migrations:** Canonical `backend/db/schema.sql` + `seed_dev.sql`. No Alembic in v1.
24. **Money rules:** One payment per action; `finalize_paid` is the sole paid activation point.

## Phase P0 Decisions
- **P0-1 (Python Runtime):** Used Python 3.12 in `backend/venv` to ensure stable wheel availability for asyncpg, pydantic, and cryptography on Windows.
- **P0-2 (Key Generation):** `scripts/gen_keys.py` generates 2048-bit RS256 keys, serializes to PEM format, and escapes newlines (`\n`) for single-line .env storage as instructed in Section 15.7.
- **P0-3 (Health & Readiness):** `GET /health` acts as lightweight liveness probe (`{"status": "ok"}`). `GET /ready` performs readiness checks against database connectivity and configuration integrity.
- **P0-4 (Frontend Build & Tooling):** Built React 18 + TypeScript scaffolding with Vite, Tailwind CSS v3, React Router v6, TanStack Query v5, Lucide React, and Vitest for testing.

## Phase P1 Decisions
- **P1-1 (Database Roles & Least Privilege):** Applied section 6.14 DDL creating `gympro_app` (NOSUPERUSER, NOBYPASSRLS), `gympro_seed` (bootstrap/fixtures only), and `gympro_analytics` (views only).
- **P1-2 (SQL Parameterized RLS Context):** Implemented `set_rls` using `SELECT set_config('app.user_id', :uid, true)` and `SELECT set_config('app.role', :role, true)` to ensure SQL-injection-proof setting of transaction-local RLS variables.
- **P1-3 (Connection Pooling in Asyncpg Tests):** Used `poolclass=NullPool` for pytest asyncpg test engines to prevent cross-test connection pool leaks across distinct event loops on Windows.
- **P1-4 (Seed Data):** Populated `seed_dev.sql` with the 3 membership plans, 3 trainers (inserted via `gympro_seed` role to satisfy `guard_role_change`), and 30 classes across the 14 days following the frozen clock (`2026-10-16T18:05:00+05:30`), covering both trial-eligible and contraindicated (knee-unsafe) classes.

## Phase P2 Decisions
- **P2-1 (RS256 JWT & Token Verification):** `create_access_token` and `decode_access_token` use RS256 with explicit audience `aud="gympro"` and subject claims. Access tokens verify that `ver` matches `users.token_version`. Algorithm `none` and symmetric forged signatures are strictly rejected.
- **P2-2 (Dynamic Database Role & Status):** User role and account status are always re-read from the database upon every request in `get_session`, ensuring immediate revocation and role propagation without trusting JWT claims.
- **P2-3 (Refresh Token Family Rotation & Reuse Detection):** Refresh tokens are grouped into families (`family_id`). Using an already-rotated refresh token triggers immediate theft detection: all tokens in the entire family are revoked, an audit log entry (`REFRESH_REUSE_DETECTED`) is written, and HTTP 401 is returned.
- **P2-4 (Equal-Time Password Check):** `verify_password` checks candidate passwords against a static `DUMMY_HASH` if the user is missing from the database, preventing username enumeration through timing attacks.
- **P2-5 (Account Lockout & Exponential Backoff):** 5 consecutive failed login attempts lock the user account for 15 minutes, with exponential doubling for subsequent failures.
- **P2-6 (No Account Enumeration):** Registration and forgot-password endpoints return identical HTTP 200 responses regardless of whether the email already exists in the system.
- **P2-7 (Transactional Notification Outbox):** All transactional emails (email verification, password reset, and registration collisions) are enqueued directly into `notification_outbox` within the database transaction.

## Phase P3 Decisions
- **P3-1 (RabbitMQ Topology & Retry Queues):** Declared `gympro.events` and `gympro.dlx` as durable topic exchanges. Configured `q.email` with dead-letter exchange `gympro.dlx` and dead-letter routing to `email.retry.30s`. Dedicated retry queues (`q.email.retry.30s`, `q.email.retry.5m`, `q.email.retry.30m`) dead-letter expired messages back to `gympro.events` under `email.retry.deliver`.
- **P3-2 (Bounded DLQ Progression):** Message headers track `x-retry-count`. When `x-retry-count >= 3`, messages route to `q.dlq` for manual inspection rather than infinite retry loops.
- **P3-3 (Outbox Publisher Confirms):** `publish_outbox_batch` uses aio-pika publisher confirms (`confirm_delivery=True`). Rows in `notification_outbox` are marked `sent_at = NOW()` only after broker ACK, preventing lost messages on broker restarts or network hiccups.
- **P3-4 (Idempotent Consumers):** Workers claim messages via `INSERT INTO processed_messages (message_id, consumer) ON CONFLICT DO NOTHING`. If a duplicate delivery occurs, the worker acknowledges and discards without duplicate side-effects.
- **P3-5 (Recipient Privacy & Email Logs):** Recipient addresses are always hashed with SHA-256 (`to_hash`) in `email_log`. No raw email address or health information is ever written to logs.
- **P3-6 (Transactional vs Marketing Suppression):** Transactional emails (verification, reset, security alerts, receipts) bypass unsubscribes and always deliver. Marketing emails check `unsubscribes` table and user `notification_prefs.marketing_opt_in`.
- **P3-7 (Token Sanitization from Stored Outbox):** After successful email delivery, sensitive authentication links/tokens are purged from `notification_outbox.params` (`params - 'link' - 'token' - 'code'`).
- **P3-8 (System RLS Context in Workers):** Background workers and the relay run with `set_rls_system(session)` (`app.role = 'SYSTEM'`), allowing safe cross-user notification writes while adhering strictly to PostgreSQL RLS policies.

## Phase P4 Decisions
- **P4-1 (Trainer Application Risk Hints):** Pre-calculated risk hints (`duplicate_phone`, `disposable_email`) are computed during `create_trainer_request` and stored on `trainer_applications` for admin queue visibility without blocking legitimate users automatically.
- **P4-2 (7-Day Reapplication Cooldown):** When a trainer request is rejected, the user cannot submit another trainer application for 7 days (`REJECTED_WAIT_7_DAYS`).
- **P4-3 (Admin Code Flow & Invariant: No Admin Approval Path):** System administrators can never approve other admin applications via API (`POST /api/admin/admin-requests/{id}/approve` does not exist and returns 404). Admin activation occurs strictly via one-time HMAC-SHA256 verified code sent to all active admins.
- **P4-4 (Admin Code Flood Limits & Locking):** At most 3 pending admin requests may exist system-wide at any time (`TOO_MANY_PENDING_ADMIN_REQUESTS`), and at most 1 request per 24 hours per email (`ONE_REQUEST_PER_DAY`). Submitting 5 wrong codes permanently cancels the request and expires the account (`REQUEST_LOCKED`).
- **P4-5 (Single-Use Hash Destruction):** Upon successful admin code activation, the code HMAC is overwritten with a dummy non-matching hash to satisfy `chk_admin_code` while preventing replay attacks.
- **P4-6 (First Admin Bootstrap):** Admin sign-up is disabled if no active admin exists (`ADMIN_SIGNUP_UNAVAILABLE`). `python -m app.seed_admin` connects as `gympro_seed` to bootstrap the initial administrator and logs an `ADMIN_SEEDED` audit row.
- **P4-7 (Cooling-off Protection):** Newly activated admins receive a 24-hour cooling-off window (`cooling_off_until = NOW() + 24 hours`). `require_not_cooling_off` blocks restricted operations (`staff/invites`, `trainer-requests/{id}/decision`, `broadcasts`) during this window.
- **P4-8 (Staff Trainer Invites):** Decision 16 is enforced: Admin invites are strictly prohibited (`ADMIN_INVITES_DISABLED`), while trainer invites generate a 7-day token. Accepting a trainer invite inserts a pre-approved `role_requests` row (`decided_by = inviter`) within the same transaction to satisfy the `guard_role_change()` trigger.
 
 ## Phase P5 Decisions
 - **P5-1 (Trial Grant Invariants):** Grants 3 free classes with a 14-day expiry window upon email verification. System enforces strict uniqueness: at most one trial grant per verified user (`user_id` unique constraint) and at most one trial grant per phone number hash across the platform (`phone_hash = sha256(phone)`).
 - **P5-2 (Entitlement Resolution Order & Precedence):** `entitlements(db, user_id, cls, *, projected_plan)` evaluates active membership first. If an active membership exists: verifies class plan restrictions against `allowed_plans`, verifies credit caps from plan perks against non-cancelled bookings (`status != 'CANCELLED'`) in the billing cycle, and returns membership-backed entitlement. Trial eligibility is evaluated second (requires `trial_eligible = True` on class and remaining credits). If neither applies, resolution returns `NO_PLAN_CHOOSE_ONE`.
 - **P5-3 (Membership Upgrade & Atomic Replacement):** Plan upgrades execute atomic replacement inside a single database transaction: marks old membership `status = 'REPLACED'`, `end_date = CURRENT_DATE`, and sets `replaced_by = new_membership.id`. This frees the PostgreSQL partial unique index `uq_one_active_membership` before creating the new ACTIVE membership row, preventing any window of duplicate or missing active memberships. A transactional `email.plan` confirmation is enqueued in the outbox.
 - **P5-4 (Proration Math & Invariants):** Price difference calculation (`price_diff`) computes cycle delta `new_price - old_price`. For positive deltas, prorated daily cost is `(delta_per_cycle * remaining_days) / total_days`, clamped to a minimum of 1.00 INR (`MIN_CHARGE = Decimal('1.00')`). Downgrades are strictly blocked with `DOWNGRADE_NOT_ALLOWED` in accordance with Decision 13.
 - **P5-5 (Health Data Consent & Intake History Audit):** Updating or reading member health data (injuries, allergies, goals) is gated on affirmative member consent (`health_data_consent = True`). Withdrawing consent immediately deletes health profile data and clears LLM memory. Profile updates write to `member_profiles` and trigger append-only audit snapshots in `member_intake_versions`. Safety validation blocks calorie-restriction fat loss for minors (`UNDERAGE_CALORIE_RESTRICTION`) and high-intensity fat loss goals during pregnancy (`PREGNANCY_GOAL_CONFLICT`).



