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

## Phase P6 Decisions
- **P6-1 (Advisory Locking for User Action Serialization):** Uses `SELECT pg_advisory_xact_lock(hashtextextended(:u, 0))` on user UUID during booking and membership change handlers to eliminate user-level race conditions and enforce strict double-booking prevention.
- **P6-2 (Row Locking for Class Capacity Serialization):** `SELECT ... FROM fitness_classes WHERE id = :cid FOR UPDATE` serializes capacity incrementing and prevents overbooking beyond physical room limits during concurrent confirmations.
- **P6-3 (Deterministic Execution Flow & Replay Idempotency):** Calling `/api/actions/{id}/confirm` on an already-`EXECUTED` action or bundle immediately returns the cached `result` payload without invoking handlers again or duplicating outbox messages.
- **P6-4 (Step-Level Bundle Transactions & Topological Ordering):** Each action inside an `action_bundles` executes in an isolated transaction in dependency order (`step_no`, DAG). If step `N` fails, all actions declaring `N` in `depends_on` are marked `SKIPPED` with `DEPENDENCY_FAILED`, while independent steps continue. Bundles with partial failures are marked `PARTIAL` rather than rolling back completed steps.
- **P6-5 (Price Fluctuation Guard):** Plan changes compare the user's `confirmed_total` against the live recalculated `quote.prorated_today`. Deltas greater than `0.01` INR trigger immediate rejection with `PRICE_CHANGED` without charging or activating plans.
- **P6-6 (Foreign Key Order on Plan Replacement):** In `activate_plan`, old active membership is marked `REPLACED` before inserting the new membership row, which in turn is followed by linking `old.replaced_by = new.id`, maintaining both foreign key integrity and `uq_one_active_membership` constraint satisfaction.

## Phase P6b Decisions
- **P6b-1 (Payment Provider Protocol & Test Fake):** `PaymentProvider` abstract protocol encapsulates order creation, signature verification, and payment listing. `RazorpayProvider` connects to Razorpay REST APIs, `MockProvider` simulates instant paid confirmations for local testing, and `FakeProvider` provides deterministic signature generation and order capture simulation for hermetic unit testing without network dependencies.
- **P6b-2 (Paise Minor Unit Exact Arithmetic):** All monetary amounts are quantized to integer paise (`ROUND_HALF_UP`) with `to_minor()`. No float calculations or drifting rounding errors touch financial tables.
- **P6b-3 (Single Authority for Paid Activation):** `finalize_paid` is the unique entrypoint for converting payment capture into active memberships. Idempotent across callers (`verify`, `webhook`, `reconciler`) using row locking (`FOR UPDATE`) on `payments`. If payment arrives late, expired, or after plan conflict, state transitions to `NEEDS_REVIEW` with an admin notification, never activating silently.
- **P6b-4 (Non-Terminal Payment Failure & Attempt Tracking):** Webhook events for `payment.failed` increment the attempt counter on the open payment row without terminating it, allowing user retry within the Checkout modal. Terminal failures only occur upon order expiry, user cancellation, or reconciler expiration.
- **P6b-5 (Raw Bytes Webhook HMAC & Event Deduplication):** `POST /api/payments/razorpay/webhook` strictly reads raw request body bytes for SHA-256 HMAC verification before any JSON deserialization. Unique `X-Razorpay-Event-Id` headers are inserted into `payment_events` with `ON CONFLICT DO NOTHING`, discarding duplicate deliveries safely.
- **P6b-6 (Production Guard):** Server refuses to start if `ENV=production` and `PAYMENTS_MODE=mock` (verified at Pydantic settings initialization and FastAPI startup).

## Phase P7 Decisions
- **P7-1 (Declarative Invariant Scans & Tool Safety):** System enforces by automated reflection scan: (1) no tool has `kind="write"`, only `read`, `calc`, `propose`; (2) no tool accepts caller identity arguments (`user_id`, `actor_id`, `recipient`, `from_user`, etc.) which are strictly injected from authenticated `ctx.session`; (3) all tools declare explicit role authorization sets.
- **P7-2 (Strict Extra Attributes & Pydantic Validation):** All tool parameter schemas inherit from `BaseArgs` with `ConfigDict(extra="forbid")`. Dispatcher parses and strictly validates arguments, rejecting unexpected arguments before invoking tool logic.
- **P7-3 (Declarative Health Consent Gating):** Tools accessing sensitive biometric, injury, or diet profiles (`get_my_intake`, `get_my_health_profile`, `get_my_nutrition_inputs`) declare `needs_health_consent=True`. Dispatcher checks `ctx.session.health_data_consent` and immediately refuses execution if consent is not granted (`CONSENT_REQUIRED`), protecting user privacy before any database query runs.
- **P7-4 (Admin Cooling-Off Protection in Tool Registry):** Tools performing privileged modifications (`propose_decide_trainer_request`, `propose_verify_trainer`, `propose_broadcast`, `propose_invite_staff`) declare `restricted_cooling_off=True`. If `ctx.session.is_cooling_off` is true, the tool call is rejected (`ACTION_BLOCKED_COOLING_OFF`).
- **P7-5 (Deterministic Calculators):** Metabolic and training formulas are executed strictly as deterministic Python calculators (Mifflin-St Jeor BMR, activity multipliers for TDEE, WHO BMI bands, hydration baseline, Epley 1RM with progressive overload increments, and exact macronutrient caloric distributions obeying the 4/4/9 kcal rule) rather than delegating arithmetic to LLM generation.
- **P7-6 (Allergen Fail-Closed Filtering):** `find_foods` matches food allergens against the member's recorded profile. If a food item contains any recorded allergy or cannot be verified safe, it is excluded (`fail-closed`).
- **P7-7 (No Recipient Injection in Comms):** `propose_send_email` rejects any caller-specified email address. The recipient is unconditionally resolved from `ctx.session.email` (or `users.email`), preventing arbitrary outbound mail relay.

## Phase P8 Decisions
- **P8-1 (Five-Layer Prompt Hierarchy & SHA-256 Versioning):** Prompt composition strictly stacks: (1) Base System Policy, (2) Domain Agent Prompt, (3) Session Context JSON, (4) User Input, and (5) Tool Results wrapped in XML tags. System prompts are versioned by front matter semver (`version: 1.0.0`) and stored in the database `prompt_versions` table with SHA-256 integrity hashes on startup.
- **P8-2 (Hermetic Agent Runner & Bounded Tool Loop):** The agent runner executes a maximum 5-turn tool loop within a strict wall-clock timeout (`AGENT_TIMEOUT_SECONDS = 15s`) and token budget (`AGENT_MAX_TOTAL_TOKENS = 3500`). Token consumption is tracked across LLM calls; budget exhaustion or timeout triggers immediate deterministic safe fallback.
- **P8-3 (Single Retry with Error Feedback):** When the model returns invalid JSON or fails Pydantic schema validation, the runner provides exactly one corrective turn (`attempt 2`) feeding the validation error back to the model before falling back to `safe_fallback(agent)`.
- **P8-4 (Deterministic Multi-Stage Post-Validators):** Before returning an envelope response to the caller, the runner passes the envelope through agent-specific post-validators:
  - **Word limit:** `user_message` clamped/verified <= 90 words.
  - **Schedule confirmation:** Ensures proposals link to real classes and do not claim completed booking when status is `NEEDS_CONFIRMATION`.
  - **Membership downgrade prevention:** Post-validator rejects any attempt to downgrade plan.
  - **Wellness red flags & crisis escalation:** Immediate elevation to `status = ESCALATE` and safety flags (`RED_FLAG_SYMPTOM`, `CRISIS`) with empty exercise suggestions when acute symptoms (chest pain, shortness of breath, suicidal ideation) are detected.
  - **Nutrition minor safety & fail-closed allergen audit:** Calorie deficit recommendations for minors (< 18) are blocked; meal plans containing allergens matching the member profile are rejected.
- **P8-5 (Hermetic Eval Harness & FakeLLM):** All eval cases are specified in YAML under `tests/evals/cases/` and tested against a scriptable `FakeLLM` mock that faithfully adheres to the OpenAI chat completions schema. No network calls or API keys are required for 100% reproducible safety gates.

## Phase P9 Decisions
- **P9-1 (Supervisor Architecture & LangGraph StateGraph):** Structured the Supervisor pipeline as an explicit LangGraph `StateGraph(State)` containing: `input_guard -> planner -> run_waves -> make_bundle -> synthesize -> output_guard -> END`, with conditional branch routers for input guard decisions (`CONTINUE`, `ESCALATE`, `REFUSE`, `CLARIFY`).
- **P9-2 (Two-Tier Input Guarding):** First evaluates high-speed deterministic regex passes to instantly catch crisis/self-harm keywords and common prompt injection patterns, followed by LLM classification over 10 closed-set labels. Injection attempts and acute self-harm route cleanly to terminal nodes without spawning agent waves.
- **P9-3 (Deterministic Plan Validation & Topological Wave Sort):** LLM DAG plans are strictly sanitized by `validate_plan()`: role-based intent filtering (e.g. blocking admin actions from non-admins), clamping to at most 4 waves and 6 agents, and Kahn's algorithm topological sort recomputation so agents only execute after all prerequisite dependencies finish.
- **P9-4 (Whitelisted Inter-Agent Handoffs):** Agents run hermetically without full shared memory; state passing across waves is constrained to an explicit whitelist of safe fields (`projected_plan`, `preferred_activities`, `selected_class`, `step_refs`), preventing prompt leakage and malicious payload propagation.
- **P9-5 (Deterministic Bundle Builder with DB Verification):** Actions proposed by domain agents are checked against the database (`pending_actions`) to ensure validity, correct user ownership, and unexpired pending status. If 2 or more write steps exist, a multi-step `action_bundles` row is created with ordered step dependencies; single actions return a plain action card; clarifying questions from `NEEDS_INPUT` agents are extracted alongside the confirmation card.
- **P9-6 (Dual Delivery via SSE & JSON):** `POST /api/agent/chat` accepts an `Accept: text/event-stream` header to stream progressive execution events (`guard`, `plan`, `agent_start`, `agent_done`, `bundle`, `synth`, `done`) or returns a full JSON payload for non-streaming clients, persisting run metrics and token meter totals to `agent_runs`.

## Phase P10 Decisions
- **P10-1 (ChromaDB Persistent Store & Collection Schema):** Deployed Chroma persistent client (`chromadb.PersistentClient`) with 4 distinct collections: `injury_protocols`, `exercises`, `nutrition_science`, and `gym_policies`. Storage is kept local and isolated on disk at `./gympro_vector_store`.
- **P10-2 (Idempotent Corpus Ingestion Pipeline):** Structured `app.kb.ingest` to parse YAML front matter from markdown docs under `backend/kb/corpus/` and upsert into Chroma keyed idempotently by document id. All complex metadata fields (lists, dicts, dates) are flattened to strings to adhere strictly to Chroma's scalar metadata type system.
- **P10-3 (12-Month Staleness Filtering for Injury Protocols):** Enforced a hard filter in `query_kb` that excludes any protocol in `injury_protocols` whose `reviewed_at` date is older than 365 days relative to the reference clock (`2026-10-16` / now).
- **P10-4 (Untrusted Context Tagging & Indirect Injection Defense):** All retrieved knowledge base text is encapsulated in `<retrieved_context id="..." collection="...">` XML tags and treated as untrusted reference facts. Agent prompts instruct the model never to treat text inside retrieved context as instructions, and post-validators verify that injected instructions do not trigger privilege escalation or unauthorized tools.
- **P10-5 (Post-Validators for Remaining User Agents):**
  - **FITNESS:** Verified class recommendations respect avoid_categories and max_impact limits, enforces that based_on is populated with input parameters, and blocks high-impact consecutive days.
  - **TRAINER_INFO:** Clamped to max 3 trainers, enforces that trainers with < 5 reviews are marked `is_new: true` without star ratings, advertises only verified certifications, and strictly forbids physical outcome promises.
  - **SUPPORT:** Clamped `neutral_summary` to <= 40 words, enforced third-person objective tone without trainer blame adjectives, and refused direct trainer messaging.
  - **COMMS:** Strictly enforced account email recipient matching, required calendar file attachment for `BOOKING_DETAILS`, and barred personal health/injury details from email subjects and preview copy.

## Phase P11 Decisions
- **P11-1 (Staff Copilots Prompt Hierarchy & Front Matter Versioning):** Authored `trainer_ops.md` and `admin_insights.md` with version `1.0.0`, matching Spec 7.12 and 7.13 requirements. Prompts are automatically indexed and synchronized with `prompt_versions` in the database.
- **P11-2 (Trainer Recurring Series Preview & Conflict Engine):** In `preview_series`, instance status is evaluated across 4 states: `OK`, `CONFLICT_TRAINER_OVERLAP` (trainer already has class at that time), `TIME_OFF` (trainer has approved leave), and `OUTSIDE_AVAILABILITY` (outside regular working hours).
- **P11-3 (Staff Privacy Invariants & K-Anonymity):**
  - **Attendee Health Protection:** Trainers can never access attendee medical intake, health profiles, or injury records via copilot or direct queries (guarded at prompt layer, post-validator `_validate_trainer_ops`, and database RLS). `get_class_roster` strictly filters out emails, phone numbers, and last names, only surfacing first names and booking status.
  - **Admin Anonymization:** Admin copilots never reveal individual member health or per-member attendance (`CROSS_USER_REQUEST` refusal). In `get_issue`, the reporter is masked to `"a member"` and all PII is scrubbed.
  - **Feedback K-Anonymity:** In `get_feedback_summary`, if a trainer has fewer than 5 reviews, qualitative and numerical details are suppressed (`suppressed = True`).
- **P11-4 (Admin Privilege Escalation Refusal):** `ADMIN_INSIGHTS` strictly refuses any request to approve, activate, share a code for, or create an admin account, setting `status = REFUSED` with `PRIVILEGE_ESCALATION` flag and instructing the admin on the secure one-time code flow. No approve endpoint exists anywhere in the codebase.
- **P11-5 (Staff Sensitive Action Cooling-Off Blocking):** Tools performing privileged proposals (`propose_invite_staff`, `propose_decide_trainer_request`, `propose_grant_membership`, `propose_broadcast`) strictly check `session.cooling_off_active` and reject with `COOLING_OFF_ACTIVE`.
- **P11-6 (Issue Triage REST Endpoints):** Exposed `GET /api/admin/issues`, `GET /api/admin/issues/{id}`, and `POST /api/admin/issues/{id}/triage` on `admin_router` with `ADMIN` role requirement, executing under system RLS context to allow safe admin issue audits without exposing member PII.

## Phase P12 Decisions
- **P12-1 (Frontend Client Architecture & Zero-Secret State):** React 18, React Router v7, TanStack Query v5, and Lucide icons. Native `fetch` HTTP wrapper manages Bearer tokens, token refresh on 401 (`POST /api/auth/refresh`), and uniform error mapping to friendly user guidance. Client never sends `user_id` or secret payment keys.
- **P12-2 (Database-Enforced Role Routing):** `RequireRole` reads role directly from `GET /api/me` (which queries PostgreSQL), never from client JWT tokens. Non-matching roles or unauthenticated requests redirect to `/login` or the role's home view.
- **P12-3 (AI Coach Voice Invariant):** Voice input via Web Speech API fills the chat message only; action confirmation is tap-only. The spoken or typed phrase "yes, confirm" is never executed as an action confirmation. Inputs are disabled while mutations are in flight.
- **P12-4 (Server-Rendered Bundle Cards & Dependency Chains):** Action cards and multi-step bundles are rendered strictly from server responses. Bundle steps visualize `depends_on` constraints ("Goes ahead only if step N succeeds") and update step execution statuses (`EXECUTED`, `SKIPPED`, `PARTIAL`).
- **P12-5 (Razorpay Modal Flow):** On receiving `status: AWAITING_PAYMENT`, client loads `checkout.js` and opens the payment modal with public key, order ID, and integer paise amount (never secrets). Signature verification executes server-side via `POST /api/payments/razorpay/verify`.
- **P12-6 (Roster Privacy & K-Anonymity):** Trainer console strictly renders first names only for class attendees. Member feedback summary is suppressed if fewer than 5 reviews exist.
## Phase P13 Decisions
- **P13-1 (Threat Model Verification & Invariant Suite):** Implemented automated threat table tests covering all 18 security invariants from Spec 12.2: database role triggers blocking direct role promotion, admin registration ignoring role body parameters, trainer approval gate before login, one-time admin code lifecycle (wrong codes, 15m expiry, 5-attempt locking, flood limits, bootstrap invariant), privilege escalation agent refusals, refresh token family reuse theft detection, single active reset token, COMMS refusal of cross-user email targets, tool registry scan rejecting spoofable identity/payment arguments, cooling-off broadcast restrictions, PostgreSQL RLS cross-user isolation, bundle confirm ignoring client-forged step lists, payment signature verification and duplicate webhook deduplication, production startup refusal with mock payments, and PII/financial scrubbers.
- **P13-2 (Observability Layer Architecture):**
  - **Structured Logging:** Configured `setup_logging` emitting JSON log records with automatic redacting of 13-19 digit credit cards (`[REDACTED_CARD]`), bearer tokens (`[REDACTED_TOKEN]`), CVVs, UPI IDs, bank accounts, and SHA-256 email masking.
  - **OpenTelemetry Tracing:** `TracerProvider` and `trace_span` context manager instrument chat requests, guards, planners, agents, tools, and DB queries. Injects and propagates `X-Trace-Id` across HTTP headers, agent run records, and worker event headers.
  - **Prometheus Metrics Registry:** In-memory `MetricsRegistry` tracking request count, error rates, agent run status distribution, tool calls, token usage, and p50/p95 latency histograms. Exposed in standard Prometheus exposition format at `GET /metrics` and JSON summary at `GET /metrics/json`.
- **P13-3 (Red-Team Adversarial Evaluation Pack):** Authored `test_red_team.py` testing direct system prompt extraction attempts, multi-qualifier prompt injection attacks, delimiter and XML/Markdown breakout attacks, roleplay DAN jailbreaks, indirect knowledge base injection resistance, IDOR tampering on single pending actions and multi-step bundles, tool-level cross-user cancellation attempts, and parameterized SQL injection fuzzing.
## Phase P14 Decisions
- **P14-1 (Zero-Secret Repository & .gitattributes Line Endings):** Configured strict line ending normalization in `.gitattributes` (`eol=lf` for `*.py`, `*.sql`, `*.md`, `*.json`, `*.ts`, `*.tsx`; `eol=crlf` for `*.ps1`, `*.bat`). Updated `.gitignore` to bar `mail_outbox/`, `*.dump`, `*.sql.tar`, `*.bak`, and `tools/`. Added automated test `test_git_tracked_files_secret_hygiene` ensuring zero secret files or dumps are tracked.
- **P14-2 (Hermetic Pinned Dependencies & Reproducible Installs):** Pinned exact dependency versions in `backend/requirements.txt` matching Python 3.12 verified environment. Committed `frontend/package-lock.json` for deterministic `npm ci`.
- **P14-3 (Fake LLM Provider for Corporate Policy Compliance):** Designed and integrated `LLM_PROVIDER=fake` backed by deterministic `FakeLLM` adapter in `backend/app/llm_fake.py`. Since Ollama and personal API keys are prohibited on company PCs, this allows full development, smoke testing, and demo execution without cloud calls. Enforced fail-fast runtime refusal: `LLM_PROVIDER=fake` is strictly prohibited if `ENV=production`.
- **P14-4 (Enterprise Migration & Automation Tooling):**
  - `check_prereqs.ps1`: Non-destructive validator reporting installed versions and port availability (5432, 5672, 15672, 1025, 8025, 8000, 5173). Never installs software.
  - `setup_company_pc.ps1`: End-to-end setup script automating databases, schemas, seed data, virtual environment, keypair generation, and topology setup.
  - `start_all.ps1`: Multi-process launcher orchestrating backend API, 4 messaging workers, frontend Vite server, and SMTP services.
  - `reset_dev_db.ps1`: Safe development database teardown and recreation script.
  - `dev_smtp_sink.py`: Zero-dependency asynchronous SMTP sink listening on port 1025 and saving `.eml` files to `./mail_outbox/` when IT binary policies prevent running Mailpit.


