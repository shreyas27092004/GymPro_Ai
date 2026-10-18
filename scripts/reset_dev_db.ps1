<#
.SYNOPSIS
    Resets the development and test databases for GymPro AI.
.DESCRIPTION
    Disconnects active backends, drops and recreates `gympro` and `gympro_test`,
    applies `backend/db/schema.sql` to both, applies `backend/db/seed_dev.sql` to dev,
    and initializes RabbitMQ messaging topology.
#>

[CmdletBinding()]
param (
    [string]$PgUser = "postgres",
    [string]$PgHost = "localhost",
    [string]$PgPort = "5432"
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path "$ScriptDir\..").Path
$VenvPython = Join-Path $RepoRoot "backend\venv\Scripts\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " GymPro AI: Development Database Reset" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Find psql executable
$PsqlCmd = Get-Command "psql" -ErrorAction SilentlyContinue
$PsqlExe = if ($PsqlCmd) { $PsqlCmd.Source } else {
    $found = Get-ChildItem "C:\Program Files\PostgreSQL" -Recurse -Filter "psql.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $found.FullName } else { "psql" }
}

Write-Host "Terminating active connections to gympro and gympro_test..." -ForegroundColor Yellow
$terminateSql = @"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname IN ('gympro', 'gympro_test')
  AND pid <> pg_backend_pid();
"@
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d postgres -c $terminateSql | Out-Null

Write-Host "Dropping and recreating databases..." -ForegroundColor Yellow
$recreateSql = @"
DROP DATABASE IF EXISTS gympro;
DROP DATABASE IF EXISTS gympro_test;
CREATE DATABASE gympro;
CREATE DATABASE gympro_test;
"@
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d postgres -c $recreateSql

Write-Host "Applying schema.sql to gympro..." -ForegroundColor Yellow
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro" -f "$RepoRoot\backend\db\schema.sql"

Write-Host "Applying schema.sql to gympro_test..." -ForegroundColor Yellow
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro_test" -f "$RepoRoot\backend\db\schema.sql"

Write-Host "Applying seed_dev.sql to gympro..." -ForegroundColor Yellow
& $PsqlExe -U $PgUser -h $PgHost -p $PgPort -d "gympro" -f "$RepoRoot\backend\db\seed_dev.sql"

# Re-run messaging topology
if (Test-Path $VenvPython) {
    Write-Host "Resetting messaging topology..." -ForegroundColor Yellow
    Push-Location "$RepoRoot\backend"
    try {
        & $VenvPython -m app.messaging.topology
    } catch {
        Write-Host "[WARN] Messaging topology initialization skipped." -ForegroundColor Gray
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "[SUCCESS] gympro and gympro_test have been cleanly reset." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
