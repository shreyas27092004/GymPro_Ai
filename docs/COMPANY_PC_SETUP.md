# GymPro AI: Company PC Setup & Migration Guide

This guide describes the complete, compliant procedure for setting up and running GymPro AI on a company-managed Windows workstation, adhering strictly to enterprise security policies, zero-secret repository principles, and locked architecture decisions.

---

## Part A: IT Pre-approvals & Prerequisites

Before running any project commands, verify the following prerequisites with your IT department:
1. **Administrative Rights:** Needed for installing PostgreSQL and RabbitMQ (or request your IT administrator to install them).
2. **Corporate HTTP Proxy (if applicable):**
   ```powershell
   # Configure PowerShell session proxy
   $env:HTTP_PROXY = "http://proxy.company.com:8080"
   $env:HTTPS_PROXY = "http://proxy.company.com:8080"

   # Configure pip proxy
   pip config set global.proxy http://proxy.company.com:8080

   # Configure npm proxy
   npm config set proxy http://proxy.company.com:8080
   npm config set https-proxy http://proxy.company.com:8080
   ```
3. **Local Loopback Ports:** Verify that Windows Defender Firewall allows local connections on:
   - `5432` (PostgreSQL)
   - `5672` (RabbitMQ AMQP)
   - `15672` (RabbitMQ Management Dashboard)
   - `1025` (SMTP / Mailpit)
   - `8025` (Mailpit Web UI)
   - `8000` (FastAPI Backend)
   - `5173` (Vite Frontend)

### Software Checklist

| Tool | Required Version | Status / Location | Instructions |
| :--- | :--- | :--- | :--- |
| **Python** | 3.11+ (3.12 recommended) | Check: `python --version` | Ensure `pip` and `venv` are functional. |
| **Node.js** | 20 LTS or higher | Check: `node --version`, `npm --version` | Standard Node.js LTS installer. |
| **PostgreSQL** | 15+ (17 supported) | Check: `psql --version` | Default port 5432; retain superuser (`postgres`) password. |
| **Erlang & RabbitMQ** | 3.12+ | Check service running | Enable management UI: `rabbitmq-plugins enable rabbitmq_management`. |
| **Mailpit** | Latest release | Recommended | Download Windows release from GitHub (`axllent/mailpit`), extract to `C:\tools\mailpit\mailpit.exe`. **No installer or admin rights required.** |
| **Dev SMTP Sink** | Built-in | Fallback | If Mailpit binary download is blocked by IT policy, use `python scripts/dev_smtp_sink.py` (saves emails to `./mail_outbox/`). |
| **Git** | 2.40+ | Check: `git --version` | Configure line endings: `git config core.autocrlf false`. |
| **Ollama** | **N/A** | **DISALLOWED** | **Do NOT install Ollama on company PCs.** Use `LLM_PROVIDER=fake` (default) or company-approved Azure OpenAI. |

---

## Part B: Critical Prohibitions (What NOT to Copy or Run)

To guarantee compliance and prevent data/credential leakage:
- ❌ **NEVER copy `.env`, `*.pem`, `*.key`, `venv/`, `node_modules/`, `gympro_vector_store/`, or database dumps** from your personal computer. Everything must be cleanly initialized on the company workstation.
- ❌ **NEVER run `scripts/gen_keys.py` a second time** on an existing workstation unless performing an emergency key rotation. Running it regenerates RS256 keys and invalidates all existing user tokens.
- ❌ **NEVER execute `seed_dev.sql` against staging or production databases.** It is strictly reserved for the local development database `gympro`.
- ❌ **NEVER install Ollama or use personal API keys** (OpenAI/Anthropic) from a company machine.
- ❌ **NEVER configure live Razorpay keys.** Development uses `PAYMENTS_MODE=mock` or Razorpay **test** keys (`rzp_test_*`).
- ❌ **NEVER use real customer or employee personal data.** Use only seeded and synthetic test identities.

---

## Part C: Step-by-Step Setup Run Order

Open a native PowerShell terminal (Run as Administrator if needed for service configuration) and execute the steps in sequence:

### Step 1: Clone the Private Repository
```powershell
git clone <private-company-repo-url>
cd GenAi_Case_Study
```

### Step 2: Verify Prerequisites
Run the automated non-destructive prerequisites validator:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_prereqs.ps1
```
*Note: This script strictly verifies existing software and ports. It never modifies or installs software.*

### Step 3: Configure Environment
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Edit `.env` to set your PostgreSQL superuser password in `SUPERUSER_DATABASE_URL` and choose your preferred `change-me` passwords for application roles (`gympro_app`, `gympro_seed`, `gympro_analytics`). Notice that `LLM_PROVIDER=fake` and `PAYMENTS_MODE=mock` are preconfigured defaults.

### Step 4: Bootstrap PostgreSQL Databases
Run the database bootstrap script as the `postgres` superuser:
```powershell
psql -U postgres -f backend/db/00_create_databases.sql
```
*(Creates `gympro` and `gympro_test`).*

### Step 5: Apply Schemas and Least-Privilege Roles
Apply `schema.sql` (which creates least-privilege roles, RLS policies, triggers, and audit tables per Spec 6.14):
```powershell
psql -U postgres -d gympro      -f backend/db/schema.sql
psql -U postgres -d gympro_test -f backend/db/schema.sql
```
Set passwords matching your `.env`:
```powershell
psql -U postgres -d gympro -c "ALTER ROLE gympro_app PASSWORD 'change-me'; ALTER ROLE gympro_seed PASSWORD 'change-me'; ALTER ROLE gympro_analytics PASSWORD 'change-me';"
```

### Step 6: Seed Development Data
Seed plans, trainers, and classes (frozen clock `2026-10-16T18:05:00+05:30`):
```powershell
psql -U postgres -d gympro -f backend/db/seed_dev.sql
```

### Step 7: Initialize RabbitMQ Messaging Topology
Ensure the RabbitMQ service is running, then initialize exchanges and retry queues:
```powershell
rabbitmq-plugins enable rabbitmq_management
```

### Step 8: Setup Backend Virtual Environment & Dependencies
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m app.messaging.topology
```

### Step 9: Generate Cryptographic Keypair
Generate machine-local RS256 JWT keys and HMAC token secrets into `.env`:
```powershell
python ..\scripts\gen_keys.py
```

### Step 10: Setup Frontend Dependencies (Reproducible)
Install pinned dependencies via `npm ci`:
```powershell
cd ..\frontend
npm ci
```

### Step 11: Ingest Knowledge Base
Ingest the 21 curated markdown protocols and policies into local ChromaDB:
```powershell
cd ..\backend
python -m app.kb.ingest
```

### Step 12: Bootstrap Initial System Administrator
Seed the initial administrator account (prompts securely for password):
```powershell
python -m app.seed_admin --email admin@company.com
```

### Step 13: Execute Gate Smoke Tests
Run the core test gates:
```powershell
pytest tests/db tests/auth tests/messaging -q
pytest tests/evals -k "safety or schedule or bundle" -q
```

### Step 14: Launch All Services
Run the all-in-one launcher script:
```powershell
cd ..
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
```
Services will launch in coordinated process windows:
- **Frontend Web UI:** `http://localhost:5173`
- **FastAPI Backend & Swagger:** `http://localhost:8000/docs`
- **Mailpit Web UI:** `http://localhost:8025`
- **RabbitMQ Dashboard:** `http://localhost:15672` (guest / guest)

---

## Part D: Post-Setup Acceptance & Verification

1. **Full Test Suites:**
   ```powershell
   # Full backend suite (121 tests)
   cd backend
   .\venv\Scripts\pytest -q

   # Full frontend suite (14 tests)
   cd ..\frontend
   npm test
   npm run build
   ```
2. **End-to-End Registration & Verification:**
   - Navigate to `http://localhost:5173/register` and register a new test member.
   - Open Mailpit at `http://localhost:8025` (or check `./mail_outbox/` if using `dev_smtp_sink.py`).
   - Click the verification link to activate the account and claim the 3-class trial.
3. **Company-Approved LLM Endpoint (When Approved):**
   - Once IT approves an enterprise Azure OpenAI endpoint, update `.env`:
     ```env
     LLM_PROVIDER=azure
     AZURE_ENDPOINT=https://your-resource.openai.azure.com/
     LLM_API_KEY=your-key
     LLM_MODEL=your-deployment-name
     ```
   - Re-run agent evals: `pytest backend/tests/evals -q`.

---

## Part E: GitHub Workflow & Security Scans

1. **Branch Protection:**
   - Main branch is protected; all changes require pull requests with passing CI.
2. **Commit Hygiene & Secret Scan:**
   - Before pushing to the company remote, verify zero secrets are tracked:
     ```powershell
     # Check tracked files against sensitive patterns
     git ls-files | Select-String -Pattern "\.env|\.pem|\.key|venv|node_modules|gympro_vector_store|\.dump"
     ```
   - Run secret scanner (e.g. `gitleaks`):
     ```powershell
     gitleaks detect --verbose
     ```

---

## Troubleshooting

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| `Port 8000 (or 5173) already in use` | Lingering previous process | Run `Get-Process python, node -ErrorAction SilentlyContinue \| Stop-Process -Force`. |
| `psql : The term 'psql' is not recognized` | PostgreSQL bin directory not on system PATH | Add `C:\Program Files\PostgreSQL\<version>\bin` to your User PATH environment variable or let `scripts/setup_company_pc.ps1` auto-discover it. |
| `Cannot connect to RabbitMQ (5672)` | Service stopped | Open `services.msc`, start `RabbitMQ`, or run `net start RabbitMQ`. |
| `Mailpit cannot be downloaded due to IT proxy/group policy` | Corporate binary restriction | Run `python scripts/dev_smtp_sink.py` as an unprivileged Python SMTP receiver. |
| `LLM_PROVIDER=fake error in production` | Production guard | `fake` is intentionally prohibited when `ENV=production`. Set `ENV=development` in `.env` for local work. |
