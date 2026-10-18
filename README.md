# GymPro AI

GymPro AI is an enterprise-grade multi-agent gym management and AI coaching platform built natively for Windows (PowerShell) without Docker.

## Tech Stack
- **Frontend:** React 18 + TypeScript, Vite, Tailwind CSS, TanStack Query, React Router DOM, Lucide Icons, Vitest
- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (asyncio + asyncpg)
- **Auth:** RS256 JWT (15 min) + opaque rotating refresh tokens, PBKDF2/Bcrypt, role-based access control
- **Database:** PostgreSQL 15+ (RLS, row locks, exclusion constraints, triggers)
- **Queue/Bus:** RabbitMQ (topic exchange, dead letter exchanges, retries)
- **Vector DB:** ChromaDB (local embedded)
- **Mail:** SMTP / Mailpit (local testing)

---

## Getting Started (Windows Native Setup)

### Prerequisites
1. **Python 3.11+** (Python 3.12 recommended)
2. **Node.js 20+**
3. **PostgreSQL 15+** (Service running on port 5432)
4. **RabbitMQ 3.12+** (Service running on port 5672)
5. **Mailpit** (Running on port 1025 SMTP / 8025 Web UI)

---

### 1. Environment & Key Generation
Clone the repository and set up environment variables:

```powershell
# In project root:
Copy-Item .env.example .env
```

Create virtual environment and install backend dependencies:
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg pydantic pydantic-settings openai chromadb `
            langgraph pyjwt cryptography bcrypt aio-pika aiosmtplib jinja2 python-dateutil icalendar httpx `
            opentelemetry-sdk pytest pytest-asyncio pyyaml
```

Generate RS256 key pair and HMAC token secret into `.env`:
```powershell
python ..\scripts\gen_keys.py
```

---

### 2. Database Setup (Phase P1)
Create databases and apply schemas:
```powershell
createdb -U postgres gympro
createdb -U postgres gympro_test
psql -U postgres -d gympro      -f backend/db/schema.sql
psql -U postgres -d gympro      -f backend/db/seed_dev.sql
psql -U postgres -d gympro_test -f backend/db/schema.sql
```

---

### 3. Run Backend API
```powershell
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```
- API Health Check: `http://localhost:8000/health`
- API Readiness Check: `http://localhost:8000/ready`
- Swagger Docs: `http://localhost:8000/docs`

---

### 4. Run Frontend App
```powershell
cd frontend
npm install
npm run dev
```
Frontend runs at: `http://localhost:5173`

---

### 5. Running Tests
Run all backend tests:
```powershell
cd backend
.\venv\Scripts\pytest.exe -q
```

Run Phase P1 database gate tests:
```powershell
cd backend
.\venv\Scripts\pytest.exe tests/db -q
```

Run Phase P2 auth gate tests:
```powershell
cd backend
.\venv\Scripts\pytest.exe tests/auth -q
```

Run Phase P3 messaging gate tests:
```powershell
cd backend
.\venv\Scripts\pytest.exe tests/messaging -q
```

Run Phase P4 role requests & security gate tests:
```powershell
cd backend
.\venv\Scripts\pytest.exe tests/roles -q
```

Run frontend build & tests:
```powershell
cd frontend
npm run build
npm test
```
