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
