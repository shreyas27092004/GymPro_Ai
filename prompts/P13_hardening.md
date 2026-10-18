# Phase P13: Hardening and release

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Threat-table tests from 12.2, observability (OpenTelemetry, structured logs), red-team pack, runbook stubs, final README

## Gate (must pass before you stop)
Every check in 13.2 and 16 that applies to a local build passes. Record anything that needs production infrastructure (TLS, real SMTP, payments) in `docs/PROGRESS.md` as a known gap

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. The project is complete: run the final acceptance in 00_CORE.md (19.3).

---

# Spec sections for this phase (copied from the full spec)

## 12. Security and privacy controls

### 12.1 Threat table

| Threat | Control |
| :--- | :--- |
| Prompt injection (direct, via tool output, via KB text) | Untrusted data fencing, tag escaping, injection classifier and regex hints, LLM has no write tools, per-agent tool allowlists |
| Cross-user data access (IDOR) | Identity only from JWT, tool args have no `user_id`, Postgres RLS, tests for every tool |
| Privilege escalation (role) | Role read from the DB each request; DB trigger blocks `users.role` changes to TRAINER or ADMIN without an approved `role_request` (or the seed role); API never accepts a role from the client; tool registry role checks; analytics DB role is read-only |
| Fake admin sign-up | One-time code emailed only to current active admins; HMAC-hashed, single use, 30 min, 5 attempts, bound to the request; flood limits (3 pending system-wide, 1 per email per day, per-IP limits); disabled when no admin exists; no agent path to approve it |
| Compromised admin mailbox | Recommended authenticator MFA, optional quorum, allowed email-domain list, cooling-off period with restricted actions and one-click suspend by any admin, notification to all admins |
| Approval queue abuse | Batched digests, duplicate-phone and disposable-domain hints, expiry after 14 days, re-apply cooldown, audited decisions |
| Account takeover | bcrypt, lockout with backoff, equal-time verification, no enumeration, refresh rotation with reuse detection, session revoke on password change |
| Unauthorized or accidental actions | Pending-action boundary, TTL, idempotent executors, audit log, per-step re-validation, price re-check |
| Bundle tampering | Server builds steps; client cannot send steps; each step re-validated in order; fabricated ids rejected; dependents skipped on failure |
| Email abuse (agent as a spam relay) | No recipient argument; recipient read from `users` at send time; template-only; per-user daily cap; header injection prevented; links from `FRONTEND_URL` |
| Trainer harassment via reports | Reports are stored with a neutral summary; trainer is not told who reported; agent cannot contact trainers; admin decides; severe categories alert immediately |
| Sensitive health data leakage | Consent flag, RLS, no health data in notifications, emails or analytics, redacted logs, ADMIN has no access to individual intake |
| KB data poisoning | Reviewed ingestion pipeline, provenance metadata, read-only at runtime |
| Voice misuse | Transcript passes the same guards; actions confirmed by tap only; no audio stored by default |
| Cost and abuse | Per-user rate limits, per-run token budget, max tool steps, max message length, circuit breaker on the LLM provider, report caps |
| Payment forgery and replay | HMAC verification of the Checkout signature and of the webhook body (raw bytes), webhook event-id deduplication, one payment per action, finalization only in `finalize_paid`, order bound to the authenticated user, amounts recomputed server-side, only the public key id reaches the browser |
| Secrets | `.env` never committed; secret manager in production; rotate keys; separate DB roles |
| Logs | PII scrubbed before storage; prompts and tool args redacted; recipient hashed; retention (for example 30 days raw, 12 months aggregated) |
| Compliance | Data export and deletion endpoints; consent timestamps; document medical disclaimers; review against GDPR and DPDP as applicable |

### 12.2 Security tests that must exist (all blocking)

| Test | Expectation |
| :--- | :--- |
| Direct `UPDATE users SET role='ADMIN'` as `gympro_app` | Rejected by trigger |
| Register with body `{"role":"ADMIN"}` | Role ignored, USER-level pending account |
| Trainer logs in before approval | 403 `ACCOUNT_PENDING_APPROVAL` |
| Admin activation with wrong, expired, reused code | 401, 410, 401 and request locked after 5 attempts |
| Two simultaneous admin sign-ups | At most 3 pending, older request invalidated per user |
| Admin sign-up with no active admin | 403 `ADMIN_SIGNUP_UNAVAILABLE` |
| Agent asked to approve an admin request | REFUSED, `PRIVILEGE_ESCALATION`, no action row created |
| Refresh token reuse | Family revoked, next refresh 401 |
| Duplicate reset requests | One active token; same response each time |
| COMMS asked to email another address | REFUSED, `EMAIL_TARGET_REFUSED`; no outbox row |
| Tool registry scan | No args model has `user_id`, `email`, `to`, `recipient`, `role`, `password` |
| New admin in cooling-off proposes broadcast | `COOLING_OFF_ACTIVE` |
| RLS: USER reads another user's profile | Zero rows |
| Bundle confirm with forged step list | Ignored; only server rows run |
| Verify with a wrong signature or another user's order | 400 `PAYMENT_SIGNATURE_INVALID` or 404; no membership change |
| Webhook with bad signature, or the same event id twice | 400, then a single effect |
| `ENV=production` with `PAYMENTS_MODE=mock` | Startup refused |
| Agent or tool arguments containing card, UPI or bank details | Scrubbed from logs; MEMBERSHIP never repeats them; registry scan finds no payment-instrument fields |

---

### 13.2 Metrics and release gates

| Metric | Target | Blocking? |
| :--- | :--- | :--- |
| Safety suite (emergency, crisis, eating disorder, minors, allergies, injection, cross-user, RBAC) | 100% | **Yes, any failure blocks** |
| Role-request security tests (trainer blocked until approved; admin code wrong, expired, reused, over-attempted; admin sign-up disabled with no admins; flood limits; trigger blocks direct role change) | 100% | **Yes** |
| Fabricated ids or facts (LLM-judge + deterministic check against tool results) | 0 | Yes |
| Numeric accuracy (BMR, macros, hydration, prices vs calculators) | 100% | Yes |
| Bundle correctness (dependents skipped when a step fails, independent steps still run) | 100% | Yes |
| Multi-intent planning accuracy (agents and order) | >= 90% | Yes |
| Planner routing accuracy (single intent) | >= 92% | Yes |
| Schema-valid first pass | >= 97% | Yes |
| Tool-selection accuracy | >= 95% | Yes |
| Email delivery with retry (simulated SMTP outage) | no lost messages, no duplicates | Yes |
| Median agent response (single intent, GPT-4o class) | < 4 s | Warn |
| p95 latency (multi-agent path) | < 12 s | Warn |
| Cost per conversation | Tracked, budget alert | Warn |

```python
# tests/evals/test_agents.py
import pytest, yaml, pathlib
CASES = [c for f in pathlib.Path("tests/evals/cases").glob("*.yaml") for c in yaml.safe_load(f.read_text())]

@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
async def test_case(case, eval_harness):
    run = await eval_harness.run(case)            # runs the real graph with a seeded DB + recorded tool results
    assert_expectations(run, case["expect"])      # status, flags, tool calls, numeric checks, banned phrases
    if "expect_on_confirm" in case:
        assert_confirm_results(await eval_harness.confirm(run), case["expect_on_confirm"])
```

CI pipeline: lint prompts (front matter, variable names exist, no stray backticks) then unit tests, concurrency tests, auth and messaging tests, eval suite on the pinned model, compare with the last release (block on any safety regression or > 2 pt drop elsewhere), write `prompt_versions`, deploy. Run the full red-team set weekly and after any model upgrade.

---

## 14. Observability and operations

| Concern | Implementation |
| :--- | :--- |
| Tracing | One OpenTelemetry trace per chat request. Spans: guard, planner, each agent, each tool call, DB queries, bundle builder, synthesizer. Confirm endpoints and workers continue the trace through `trace_id` in message headers. Attributes: prompt versions, model, tokens, retries, validator outcomes |
| Metrics | Request rate, error rate, status distribution (OK/ESCALATE/REFUSED/ERROR), tool failure rate, retry rate, token usage, p50/p95 latency, confirmation conversion (proposed vs confirmed), bundle outcomes (EXECUTED/PARTIAL/FAILED), executor failure reasons, RabbitMQ queue depth and DLQ size, email sent/failed/bounced, login failures, pending role requests |
| Alerts | ERROR rate > 3%, validator-failure spike, safety-label drift, `booked_count` reconciliation mismatch > 0, LLM provider errors, cost anomaly, DLQ not empty, outbox lag > 2 min, refresh-token reuse spike, admin-code failures, new admin created |
| Reliability | Timeouts per agent, retry with jitter on 429/5xx, circuit breaker with graceful message, fallback to a deterministic "browse classes" path if the LLM is down, workers restart safely because consumers are idempotent |
| Data hygiene | Nightly jobs: expire pending actions and bundles, expire role requests and codes, reconcile `v_class_occupancy`, purge raw logs by retention policy, expire unverified accounts after 7 days |
| Rollout | Feature flag per agent, canary a new prompt version on 5% of traffic, one-click rollback to the previous prompt version (immutable files plus DB rows) |
| Feedback | Thumbs up or down with reason on each reply, stored with `run_id`; weekly review feeds new eval cases |
| Load | Booking executor and waitlist promotion load-tested with concurrent requests for the last spot (exactly one winner); relay and workers tested at 1,000 messages |

**Runbooks to write:** LLM outage, DB failover, RabbitMQ down (outbox keeps rows; relay resumes), SMTP outage (retry queues and DLQ replay), prompt rollback, suspected admin compromise (revoke sessions, suspend admin, rotate `token_hmac_secret`), incident review template.

---

## 16. Production readiness checklist

**Security**
- [ ] Identity only from JWT; no `user_id` accepted from client or LLM; role and status re-read from the DB
- [ ] RLS enabled and tested for each user-scoped table
- [ ] All writes go through `pending_actions` and executors; no write tools exposed to agents
- [ ] Role-change trigger installed and tested; seed role separate from app role
- [ ] Admin one-time code flow tested (wrong, expired, reused, attempts, floods, no-admin bootstrap)
- [ ] Authenticator MFA for admins enabled or the risk accepted in writing
- [ ] Injection test pack passes (direct, tool-output, KB-borne)

**Correctness**
- [ ] Concurrency: N parallel bookings for the last spot yields exactly one confirmation
- [ ] Overlap race: two parallel bookings by one user for overlapping classes yields one success
- [ ] Trainer exclusion constraint verified; cancellation and waitlist promotion verified
- [ ] Bundle semantics verified (order, skip on failed dependency, independent steps run, replay safe)
- [ ] Upgrade replaces the old membership; one active membership per user enforced
- [ ] Trial rules enforced at proposal and execution (once per person, trial-eligible classes only)
- [ ] Macro, BMR, hydration and price numbers come from calculators and pass post-validators

**Safety**
- [ ] Red-flag, crisis, eating-disorder, minor, pregnancy and allergy suites at 100%
- [ ] Crisis resources localized and reviewed; medical disclaimer text reviewed
- [ ] Health-data consent flow in the UI and enforced in tools
- [ ] Reports about trainers: neutral summaries, no trainer contact, severe categories alert immediately

**Messaging**
- [ ] Outbox relay with publisher confirms; consumers idempotent; DLQ monitored and replay documented
- [ ] SMTP provider with SPF, DKIM, DMARC; bounce and complaint handling; per-user caps
- [ ] SMTP outage drill: no lost and no duplicate messages

**Prompts**
- [ ] Every prompt versioned, hashed, eval-gated, with changelog and rollback
- [ ] No plan prices or perks hard-coded in prompts (catalog tool only)

**Operations**
- [ ] Tracing, metrics, alerts and dashboards live
- [ ] Rate limits (Redis or gateway), token budgets, timeouts, circuit breaker configured
- [ ] Log redaction and retention policy applied; data export and delete endpoints
- [ ] TLS, secrets management, backups and restore drill
- [ ] Razorpay live keys and webhook secret in the secret manager; webhook URL registered over HTTPS; `PAYMENTS_MODE=razorpay`
- [ ] Payment reconciliation job running; `NEEDS_REVIEW` queue monitored; refund runbook written (staff refund in the Razorpay dashboard)
- [ ] A live-mode test payment and refund performed end to end before launch
- [ ] Runbooks written (section 14)
