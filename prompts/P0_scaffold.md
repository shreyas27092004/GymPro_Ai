# Phase P0: Scaffold and environment

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Repo layout from 8.2 (plus `docs/`, `backend/db/`, `scripts/`); `.env.example`; `scripts/gen_keys.py` (writes an RS256 key pair and a random `TOKEN_HMAC_SECRET` into `.env`); pytest config and DB fixtures; `GET /health` and `GET /ready`; Vite React TS app with Tailwind, React Router, TanStack Query, Lucide, Vitest; `README.md`

## Gate (must pass before you stop)
`pytest -q` runs; `uvicorn app.main:app` serves `/health`; `npm run build` succeeds

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P1.

---

# Spec sections for this phase (copied from the full spec)

### 8.2 Project layout

```
backend/
  app/
    main.py              # FastAPI app, routers, SSE
    settings.py          # pydantic-settings
    db.py                # engine, get_db, RLS session setup (SET LOCAL app.user_id / app.role)
    auth/
      deps.py            # JWT -> SessionContext (reads role and status from DB)
      service.py         # register, verify, login, refresh, forgot, reset
      roles.py           # trainer requests, admin one-time codes, invites, cooling-off
      security.py        # bcrypt, token hashing, HMAC code helpers, rate limits
    llm.py               # provider adapter
    prompts.py           # registry loader (+ sha256 check)
    agents/runner.py     # tool loop + validation + retries
    agents/schemas.py    # Envelope + per-agent data models
    tools/registry.py    # tool metadata, authz, dispatch
    tools/schedule.py membership.py wellness.py nutrition.py trainer_info.py
    tools/support.py comms.py trainer_ops.py admin.py calculators.py
    orchestrator/
      graph.py           # LangGraph pipeline (or plain async function)
      planner.py         # rules fast path, LLM fallback, validate_plan
      bundle.py          # bundle builder
      guards.py          # input and output guards
    executor/
      single.py          # POST /actions/{id}/confirm
      bundles.py         # POST /bundles/{id}/confirm
      handlers.py        # one function per action type
    messaging/
      outbox.py          # enqueue helpers
      relay.py           # outbox relay process (python -m app.messaging.relay)
      topology.py        # exchanges, queues, bindings
      workers/email.py notify.py digest.py
      templates/         # Jinja2 (auto-escaped) email templates
    kb/                  # Chroma ingestion and retrieval
    seed_admin.py        # python -m app.seed_admin (first admin only)
    ratelimit.py         # in-process limiter behind check(key, limit, window_s)
  db/
    schema.sql           # section 6, in order
    seed_dev.sql         # plans, trainers, classes (dev only)
  prompts/               # section 7.1 layout
  kb/corpus/             # starter knowledge base documents (section 11)
  tests/                 # db, auth, messaging, roles, entitlements, executor, tools, evals, e2e
scripts/gen_keys.py      # RS256 key pair + TOKEN_HMAC_SECRET into .env
docs/                    # DECISIONS.md, PROGRESS.md
frontend/                # Vite + React + TypeScript (section 10)
```

---

### 8.3 Settings and LLM adapter

```python
# app/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "production"] = "development"
    database_url: str                                   # postgresql+asyncpg://...
    jwt_private_key: str
    jwt_public_key: str
    token_hmac_secret: str                              # HMAC for admin codes, phone hashes
    frontend_url: str = "http://localhost:5173"         # links in emails come from here, never from the Host header

    llm_provider: Literal["azure", "openai", "ollama"] = "ollama"
    llm_model: str = "gpt-4o"                           # Azure: deployment name; Ollama: e.g. "qwen2.5:14b-instruct"
    llm_api_key: str = "ollama"
    llm_base_url: str | None = "http://localhost:11434/v1"
    azure_endpoint: str | None = None
    azure_api_version: str = "2024-10-21"
    agent_max_tool_steps: int = 6
    agent_timeout_s: float = 25.0
    run_token_budget: int = 20_000
    chroma_path: str = "./gympro_vector_store"

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    smtp_host: str = "localhost"                        # Mailpit default
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "GymPro <no-reply@gympro.local>"
    payments_mode: Literal["mock", "razorpay", "disabled"] = "mock"   # production must not use "mock" (startup check)
    razorpay_key_id: str | None = None                  # public, sent to the browser
    razorpay_key_secret: str | None = None              # server only
    razorpay_webhook_secret: str | None = None          # server only

if settings.env == "production" and settings.payments_mode == "mock":
    raise RuntimeError("PAYMENTS_MODE=mock is not allowed when ENV=production")
settings = Settings()
```

```python
# app/llm.py
from openai import AsyncOpenAI, AsyncAzureOpenAI
from .settings import settings

def build_llm():
    if settings.llm_provider == "azure":
        return AsyncAzureOpenAI(api_key=settings.llm_api_key, azure_endpoint=settings.azure_endpoint,
                                api_version=settings.azure_api_version)
    # OpenAI proper (base_url None) or Ollama's OpenAI-compatible endpoint
    return AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

llm = build_llm()
```

---

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
