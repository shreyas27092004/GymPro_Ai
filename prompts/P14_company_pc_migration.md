# Phase P14: Move to a company PC through GitHub

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
`.gitignore` and `.gitattributes` audit; pinned `backend/requirements.txt` and committed `package-lock.json`; `backend/db/00_create_databases.sql` (creates `gympro` and `gympro_test`; roles and grants already come from `schema.sql`, section 6.14); `scripts/check_prereqs.ps1`, `scripts/setup_company_pc.ps1`, `scripts/start_all.ps1`, `scripts/reset_dev_db.ps1`; complete `.env.example`; `LLM_PROVIDER=fake` option (scripted FakeLLM, refused in production) because Ollama is not allowed on the company PC; `docs/COMPANY_PC_SETUP.md` (tools, proxy, ports, run order, what not to run, troubleshooting); optional `.github/workflows/ci.yml`; secret scan with no findings

## Gate (must pass before you stop)
A fresh clone in an empty folder on a clean machine or new Windows profile, using new database names and following only `docs/COMPANY_PC_SETUP.md`, passes `pytest tests/db tests/auth tests/messaging -q` and the 1.5 demo script; `git ls-files` shows no `.env`, keys, `venv`, `node_modules`, vector store or dumps; the secret scan reports nothing; the P0 to P13 gates still pass

## Part A: Tools to install on the company PC (before running any project command)

Check with IT first: admin rights for installers, approved-software list, proxy settings (set `HTTP_PROXY` and `HTTPS_PROXY`, `pip config set global.proxy`, `npm config set proxy`), and that local ports are not blocked.

| Tool | Version | Status on your laptop | Action |
| :-- | :-- | :-- | :-- |
| Python | 3.11+ | Installed | Verify only: `python --version`, and that `pip` and `venv` work |
| Node.js | 20 LTS | Installed | Verify only: `node --version`, `npm --version` |
| PostgreSQL | 15+ | Installed | Verify only: `psql --version`, and that you know the `postgres` superuser password |
| Erlang and RabbitMQ | 3.12+ | Installed | Verify the service is running; enable `rabbitmq_management` if not enabled |
| Mailpit | latest | **Not installed** | Download the Windows zip from the official Mailpit releases page on GitHub (github.com/axllent/mailpit), unzip to a folder outside the repo (for example `C:\tools\mailpit`), run `mailpit.exe`. Single binary: no installer and no admin rights. Check IT policy before downloading |
| Antigravity | latest | Installed | Nothing to do |
| Git | latest | Not confirmed | `git --version`; install only if missing, then `git config core.autocrlf false` |
| Ollama | n/a | **Not allowed by company** | Do not install. See the LLM rule below |

`scripts/check_prereqs.ps1` must only check these tools and report what is missing. It must never install software. For Mailpit it checks that `mailpit.exe` is on PATH or at `MAILPIT_PATH` (set in `.env`), and that port 1025 accepts connections once started.

**If Mailpit cannot be downloaded (blocked by company policy):** add `scripts/dev_smtp_sink.py` (a small `aiosmtpd` server on port 1025 that saves each email as an `.eml` file under `./mail_outbox/`, which is git-ignored). Verification and reset links are then read from those files. Mailpit stays the primary choice.

**LLM rule (Ollama is not allowed):**
- Use `LLM_PROVIDER=azure` (or another company-approved endpoint) only after IT or your manager approves the endpoint and key. Keep the key in `.env` only.
- If no endpoint is approved yet, add a `fake` provider option to `Settings` and the LLM adapter (`LLM_PROVIDER=fake`, backed by the scripted `FakeLLM`), so the app, the tests and the demo flow run without any real model. `fake` must be refused when `ENV=production`.
- Everything in P0 to P13 tests already uses `FakeLLM`, so the gates do not need a real model.

Ports used: 5432, 5672, 15672, 1025, 8025, 8000, 5173.

## Part B: Do NOT run, copy or commit

- Do not copy `.env`, JWT key files, `venv/`, `node_modules/`, `gympro_vector_store/`, database dumps or `mailpit.exe` from the personal PC. Everything is rebuilt on the company PC.
- Do not move data from the personal database. Recreate it from `schema.sql` plus `seed_dev.sql`.
- Do not run `scripts/gen_keys.py` a second time on the same machine: it overwrites the JWT keys and invalidates every issued token. Run it once per machine.
- Do not run `seed_dev.sql` against any shared, staging or production database. It is for the local dev database only.
- Do not run `python -m app.seed_admin` before the schema is applied and the backend `.env` is complete.
- Do not run `python -m app.kb.ingest` before `CHROMA_PATH` is set and the embedding model is reachable.
- Do not set `PAYMENTS_MODE=razorpay` until test keys are in `.env`. Never use live Razorpay keys on this PC.
- Do not install Ollama or any local model runtime. Do not point the app at a personal API key (OpenAI, Azure or other) from the company PC. Use `LLM_PROVIDER=fake` or a company-approved endpoint.
- Do not run `@pytest.mark.live` tests unless an approved LLM endpoint is configured.
- Do not use real customer or employee data anywhere. Seed data only.

## Part C: Run order on the company PC (this is what `docs/COMPANY_PC_SETUP.md` and `scripts/setup_company_pc.ps1` must follow)

1. `git clone <private-repo-url>` and `cd` into it.
2. `scripts/check_prereqs.ps1`: verifies each tool version (no installing) and that ports 5432, 5672, 1025, 8025, 8000 and 5173 are free; prints what is missing and stops.
3. Copy `.env.example` to `.env` and edit placeholders (database passwords, `PAYMENTS_MODE=mock`, and `LLM_PROVIDER=fake` until a company-approved endpoint exists; never `ollama`).
4. As the PostgreSQL superuser, create the databases: `psql -U postgres -f backend/db/00_create_databases.sql` (creates `gympro` and `gympro_test`). The roles `gympro_app`, `gympro_seed` and `gympro_analytics` and their grants are already created by `schema.sql` (section 6.14, done in P1), so no separate role script is needed.
5. `psql -U postgres -d gympro -f backend/db/schema.sql`, then `psql -U postgres -d gympro_test -f backend/db/schema.sql`.
   Then set real passwords instead of the `change-me` placeholder: `ALTER ROLE gympro_app PASSWORD '...'` (same for `gympro_seed` and `gympro_analytics`) and put the same values in `.env`.
6. `psql -U postgres -d gympro -f backend/db/seed_dev.sql` (dev database only).
7. Start Mailpit and RabbitMQ, then `python -m app.messaging.topology`.
8. `cd backend`, create the venv, `pip install -r requirements.txt`.
9. `python ..\scripts\gen_keys.py` (once).
10. `cd ..\frontend` and `npm ci`.
11. `python -m app.kb.ingest` (if the embedding model needs a cloud call, use the approved endpoint or skip ingest and run KB tests with fixtures).
12. `python -m app.seed_admin --email <your company email>`.
13. `scripts/start_all.ps1`: backend on 8000, the four workers, frontend on 5173.
14. Smoke test: `pytest tests/db tests/auth tests/messaging -q`, then `pytest tests/evals -k "safety or schedule or bundle" -q`.

## Part D: Run only after everything above passes

- The full test suite and the 1.5 demo script against Mailpit.
- Switch `PAYMENTS_MODE` to `razorpay` with **test** keys, and repeat the payment tests.
- Once an endpoint is approved: set `LLM_PROVIDER=azure` (or the approved one) and re-run the evals on that model.
- Optional CI (`.github/workflows/ci.yml`) once the local run is green.
- Tag the release (`git tag v1.0.0`) and push.

## Part E: GitHub rules for this move

- Private repository, protected `main`, changes through pull requests.
- Commit lockfiles (`package-lock.json`, pinned `requirements.txt`). Never commit `.env`, keys, dumps, `venv`, `node_modules` or the vector store.
- Run a secret scan (for example `gitleaks detect`) on the full history before the first push to the company remote. If any secret was ever committed, rotate it and rewrite the history before pushing.
- Add `.gitattributes` so `*.sql`, `*.py`, `*.md` use LF and `*.ps1` uses CRLF.
- Record every ambiguity you resolve in `docs/DECISIONS.md`.

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. The project is complete: run the final acceptance in 00_CORE.md (19.3).

---

# Spec sections for this phase (copied from the full spec)

## 15. Running locally (Windows, no Docker)

All commands are PowerShell. Nothing here needs Docker.

1. **PostgreSQL 15+** (installer from postgresql.org)
   ```powershell
   createdb -U postgres gympro
   createdb -U postgres gympro_test
   psql -U postgres -d gympro      -f backend/db/schema.sql      # section 6, in order
   psql -U postgres -d gympro      -f backend/db/seed_dev.sql    # plans, trainers, classes
   psql -U postgres -d gympro_test -f backend/db/schema.sql
   ```
2. **RabbitMQ** (install Erlang, then the RabbitMQ Windows installer; enable the management plugin)
   ```powershell
   rabbitmq-plugins enable rabbitmq_management            # UI on http://localhost:15672 (guest / guest)
   python -m app.messaging.topology                       # declares exchange, queues, retry queues, DLX
   ```
3. **Mailpit** (download the Windows binary, run it, no install)
   ```powershell
   .\mailpit.exe                                           # SMTP localhost:1025, web UI http://localhost:8025
   ```
4. **Backend**
   ```powershell
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg pydantic pydantic-settings openai chromadb `
               langgraph pyjwt cryptography bcrypt aio-pika aiosmtplib jinja2 python-dateutil icalendar httpx `
               opentelemetry-sdk pytest pytest-asyncio pyyaml
   python ..\scripts\gen_keys.py                          # writes JWT keys and TOKEN_HMAC_SECRET into .env
   python -m app.kb.ingest                                 # loads the starter corpus into Chroma
   python -m app.seed_admin --email you@example.com        # first admin only (prompts for a password)
   uvicorn app.main:app --reload --port 8000
   ```
5. **Workers** (each in its own terminal, same virtual environment)
   ```powershell
   python -m app.messaging.relay
   python -m app.messaging.workers.email
   python -m app.messaging.workers.notify
   python -m app.messaging.workers.digest
   ```
6. **Frontend**
   ```powershell
   npm create vite@latest frontend -- --template react-ts      # once, in phase P0
   cd frontend
   npm install react-router-dom @tanstack/react-query lucide-react
   npm install -D tailwindcss vitest @testing-library/react @testing-library/jest-dom jsdom
   npm run dev                                                 # Vite on http://localhost:5173
   ```
7. **`.env`** (never committed; commit `.env.example` with the same keys and placeholder values). Multi-line PEM keys are stored on one line with `\n` escapes.
   ```env
   ENV=development
   DATABASE_URL=postgresql+asyncpg://gympro_app:change-me@localhost:5432/gympro
   TEST_DATABASE_URL=postgresql+asyncpg://gympro_app:change-me@localhost:5432/gympro_test
   SEED_DATABASE_URL=postgresql+asyncpg://gympro_seed:change-me@localhost:5432/gympro
   ANALYTICS_DATABASE_URL=postgresql+asyncpg://gympro_analytics:change-me@localhost:5432/gympro
   JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
   JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
   TOKEN_HMAC_SECRET=generated-by-gen_keys
   FRONTEND_URL=http://localhost:5173
   RABBITMQ_URL=amqp://guest:guest@localhost:5672/
   SMTP_HOST=localhost
   SMTP_PORT=1025
   MAIL_FROM="GymPro <no-reply@gympro.local>"
   PAYMENTS_MODE=mock                 # mock | razorpay | disabled. Production must not use mock
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxx      # public key id (test keys from the Razorpay dashboard)
   RAZORPAY_KEY_SECRET=change-me          # server only
   RAZORPAY_WEBHOOK_SECRET=change-me      # server only; same value as in the Razorpay webhook settings
   CHROMA_PATH=./gympro_vector_store

   # Fully local LLM (no cloud calls from the backend):
   LLM_PROVIDER=ollama
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_API_KEY=ollama
   LLM_MODEL=qwen2.5:14b-instruct

   # Or Azure OpenAI:
   # LLM_PROVIDER=azure
   # AZURE_ENDPOINT=https://your-resource.openai.azure.com/
   # LLM_API_KEY=your-key
   # LLM_MODEL=your-gpt-4o-deployment-name
   ```
   Local models follow schemas less reliably than GPT-4o class models: keep Pydantic validation and the retry path on, and run the eval suite on whichever model you ship. Add the extra connection settings above to `Settings` in 8.3 (`test_database_url`, `seed_database_url`, `analytics_database_url`). To try real payments, create a Razorpay account, copy the **test** key id and secret into `.env`, set `PAYMENTS_MODE=razorpay`, and follow the local-development note in 8.15 about webhooks.
8. **Smoke test:** `pytest tests/db tests/auth tests/messaging -q`, then `pytest tests/evals -k "safety or schedule or bundle" -q`. Then register a user in the UI and read the verification email in Mailpit.

---

### 6.14 Roles and grants (least privilege)

```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_app') THEN
    CREATE ROLE gympro_app LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_analytics') THEN
    CREATE ROLE gympro_analytics LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_seed') THEN
    CREATE ROLE gympro_seed LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;   -- first admin only, used by the seed command
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO gympro_app, gympro_analytics, gympro_seed;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gympro_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gympro_app;
REVOKE UPDATE, DELETE ON audit_log FROM gympro_app;
REVOKE UPDATE, DELETE ON member_intake_versions FROM gympro_app;
REVOKE UPDATE, DELETE ON email_log FROM gympro_app;
REVOKE DELETE ON payments, payment_events FROM gympro_app;

-- gympro_app : API, workers, executors
-- gympro_analytics : SELECT only on analytics views (v_*), statement_timeout = 5s, used by ADMIN_INSIGHTS tools
-- gympro_seed : INSERT/UPDATE on users only, used by `python -m app.seed_admin`
GRANT SELECT ON v_class_occupancy TO gympro_analytics;
GRANT SELECT, INSERT, UPDATE ON users TO gympro_seed;
ALTER ROLE gympro_analytics SET statement_timeout = '5s';
```

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
