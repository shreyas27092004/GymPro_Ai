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


