<#
.SYNOPSIS
    Automated company PC setup orchestrator for GymPro AI.
.DESCRIPTION
    Executes the exact Part C run order from prompts/P14_company_pc_migration.md:
    1. Verifies prerequisites using check_prereqs.ps1.
    2. Bootstraps .env from .env.example if missing.
    3. Runs backend/db/00_create_databases.sql as postgres superuser.
    4. Applies schema.sql to gympro and gympro_test.
    5. Applies seed_dev.sql to gympro dev database.
    6. Creates backend/venv and installs pinned requirements.txt.
    7. Generates cryptographic RS256 keypair via scripts/gen_keys.py.
    8. Installs frontend dependencies via npm ci.
    9. Configures RabbitMQ messaging topology.
    10. Ingests knowledge base starter corpus into ChromaDB.
#>

[CmdletBinding()]
param (
    [string]$PgUser = "postgres",
    [string]$PgHost = "localhost",
    [string]$PgPort = "5432",
    [string]$AdminEmail = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path "$ScriptDir\..").Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " GymPro AI: Company PC Migration & Setup" -ForegroundColor Cyan
Write-Host " Repository Root: $RepoRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Run Prerequisites Check
Write-Host "[Step 1/11] Checking prerequisites..." -ForegroundColor Yellow
& "$ScriptDir\check_prereqs.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Prerequisites check failed. Please resolve missing tools before continuing." -ForegroundColor Red
    exit 1
}

# Step 2: Environment File (.env)
Write-Host "`n[Step 2/11] Checking .env configuration..." -ForegroundColor Yellow
$EnvPath = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $EnvPath)) {
    Write-Host "Creating .env from .env.example with safe defaults (LLM_PROVIDER=fake, PAYMENTS_MODE=mock)..." -ForegroundColor Cyan
    Copy-Item $EnvExample $EnvPath
    Write-Host "[OK] .env created." -ForegroundColor Green
} else {
    Write-Host "[OK] Existing .env detected." -ForegroundColor Green
}

# Find psql executable
$PsqlCmd = Get-Command "psql" -ErrorAction SilentlyContinue
$PsqlExe = if ($PsqlCmd) { $PsqlCmd.Source } else {
    $found = Get-ChildItem "C:\Program Files\PostgreSQL" -Recurse -Filter "psql.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $found.FullName } else { "psql" }
}

# Step 3: Create Databases (00_create_databases.sql)
Write-Host "`n[Step 3/11] Bootstrapping PostgreSQL databases (gympro, gympro_test)..." -ForegroundColor Yellow
try {
    & $PsqlExe -U $PgUser -h $PgHost -p $PgPort -f "$RepoRoot\backend\db\00_create_databases.sql"
    Write-Host "[OK] Databases bootstrapped successfully." -ForegroundColor Green
} catch {
    Write-Host "[WARN] Database creation reported an issue (they may already exist). Continuing..." -ForegroundColor Gray
}

# Step 4: Apply Database Schema to gympro and gympro_test
Write-Host "`n[Step 4/11] Applying schema.sql with RLS, triggers, and least-privilege roles..." -ForegroundColor Yellow
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro" -f "$RepoRoot\backend\db\schema.sql"
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro_test" -f "$RepoRoot\backend\db\schema.sql"
Write-Host "[OK] Schemas applied to gympro and gympro_test." -ForegroundColor Green

# Step 5: Seed Development Database
Write-Host "`n[Step 5/11] Seeding development database (plans, trainers, frozen-clock classes)..." -ForegroundColor Yellow
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro" -f "$RepoRoot\backend\db\seed_dev.sql"
Write-Host "[OK] Dev database seeded." -ForegroundColor Green

# Step 6: Backend Virtual Environment & Pinned Dependencies
Write-Host "`n[Step 6/11] Setting up backend Python virtual environment..." -ForegroundColor Yellow
$VenvDir = Join-Path $RepoRoot "backend\venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating Python venv at $VenvDir..." -ForegroundColor Cyan
    python -m venv $VenvDir
}

Write-Host "Installing pinned backend dependencies from requirements.txt..." -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip -q
& $PythonExe -m pip install -r "$RepoRoot\backend\requirements.txt" -q
Write-Host "[OK] Backend dependencies installed." -ForegroundColor Green

# Step 7: Generate Cryptographic Keys
Write-Host "`n[Step 7/11] Generating machine-specific RS256 JWT keypair and token secret..." -ForegroundColor Yellow
& $PythonExe "$RepoRoot\scripts\gen_keys.py"
Write-Host "[OK] Cryptographic keys written to .env." -ForegroundColor Green

# Step 8: Frontend Dependencies via npm ci
Write-Host "`n[Step 8/11] Installing frontend dependencies via npm ci (reproducible build)..." -ForegroundColor Yellow
Push-Location "$RepoRoot\frontend"
try {
    npm ci --silent
    Write-Host "[OK] Frontend dependencies installed cleanly." -ForegroundColor Green
} finally {
    Pop-Location
}

# Step 9: Configure RabbitMQ Messaging Topology
Write-Host "`n[Step 9/11] Setting up RabbitMQ exchanges, dead-letter queues, and retries..." -ForegroundColor Yellow
Push-Location "$RepoRoot\backend"
try {
    & $PythonExe -m app.messaging.topology
    Write-Host "[OK] RabbitMQ topology configured." -ForegroundColor Green
} catch {
    Write-Host "[WARN] RabbitMQ topology initialization skipped or broker not running yet." -ForegroundColor Gray
} finally {
    Pop-Location
}

# Step 10: Ingest Knowledge Base
Write-Host "`n[Step 10/11] Ingesting knowledge base starter corpus into ChromaDB..." -ForegroundColor Yellow
Push-Location "$RepoRoot\backend"
try {
    & $PythonExe -m app.kb.ingest
    Write-Host "[OK] Knowledge base corpus ingested." -ForegroundColor Green
} catch {
    Write-Host "[WARN] KB ingest deferred (will use fixture in tests)." -ForegroundColor Gray
} finally {
    Pop-Location
}

# Step 11: Seed Admin Guidance
Write-Host "`n[Step 11/11] Administrative bootstrap..." -ForegroundColor Yellow
if ($AdminEmail) {
    Push-Location "$RepoRoot\backend"
    try {
        & $PythonExe -m app.seed_admin --email $AdminEmail
    } finally {
        Pop-Location
    }
} else {
    Write-Host "To create the initial system administrator, run:" -ForegroundColor Cyan
    Write-Host "  cd backend" -ForegroundColor Gray
    Write-Host "  .\venv\Scripts\python -m app.seed_admin --email <your-company-email>" -ForegroundColor Gray
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Setup Complete! Next Steps:" -ForegroundColor Green
Write-Host " 1. Run smoke tests:" -ForegroundColor Yellow
Write-Host "      cd backend" -ForegroundColor Gray
Write-Host "      .\venv\Scripts\pytest tests/db tests/auth tests/messaging -q" -ForegroundColor Gray
Write-Host " 2. Launch all services:" -ForegroundColor Yellow
Write-Host "      .\scripts\start_all.ps1" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Green
