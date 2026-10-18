<#
.SYNOPSIS
    Starts all GymPro AI services in coordinated background windows.
.DESCRIPTION
    Launches:
    1. Mailpit or Fallback Dev SMTP Sink on port 1025 / 8025
    2. FastAPI Backend on http://localhost:8000
    3. Messaging Relay Worker
    4. Email Consumer Worker
    5. In-App Notification Worker
    6. Daily Digest Worker
    7. React Frontend Vite Dev Server on http://localhost:5173
#>

[CmdletBinding()]
param (
    [switch]$NoFrontend,
    [switch]$NoWorkers
)

$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path "$ScriptDir\..").Path
$VenvPython = Join-Path $RepoRoot "backend\venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment python not found at $VenvPython. Run scripts/setup_company_pc.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Starting GymPro AI Full Stack Services" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check / Start Mailpit or Dev SMTP Sink
$smtpRunning = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $iar = $tcp.BeginConnect("127.0.0.1", 1025, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(400)
    if ($ok -and $tcp.Connected) {
        $smtpRunning = $true
        $tcp.EndConnect($iar)
    }
    $tcp.Close()
} catch {}

if (-not $smtpRunning) {
    $mailpitCmd = Get-Command "mailpit" -ErrorAction SilentlyContinue
    $mailpitExe = if ($mailpitCmd) { $mailpitCmd.Source } else {
        $candidates = @($env:MAILPIT_PATH, "$RepoRoot\tools\mailpit.exe", "C:\tools\mailpit\mailpit.exe")
        ($candidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
    }

    if ($mailpitExe) {
        Write-Host "Launching Mailpit ($mailpitExe)..." -ForegroundColor Yellow
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Mailpit' -ForegroundColor Cyan; & '$mailpitExe'"
    } else {
        Write-Host "Launching Dev SMTP Sink (fallback)..." -ForegroundColor Yellow
        $sinkScript = Join-Path $ScriptDir "dev_smtp_sink.py"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Dev SMTP Sink' -ForegroundColor Cyan; & '$VenvPython' '$sinkScript'"
    }
} else {
    Write-Host "[OK] SMTP server already running on port 1025." -ForegroundColor Green
}

# 2. Launch FastAPI Backend
Write-Host "Launching FastAPI Backend on http://localhost:8000..." -ForegroundColor Yellow
$backendCmd = "cd '$RepoRoot\backend'; & '$VenvPython' -m uvicorn app.main:app --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Backend API' -ForegroundColor Cyan; $backendCmd"

# 3. Launch Workers
if (-not $NoWorkers) {
    Write-Host "Launching Transactional Outbox Relay..." -ForegroundColor Yellow
    $relayCmd = "cd '$RepoRoot\backend'; & '$VenvPython' -m app.messaging.relay"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Outbox Relay' -ForegroundColor Cyan; $relayCmd"

    Write-Host "Launching Email Worker..." -ForegroundColor Yellow
    $emailCmd = "cd '$RepoRoot\backend'; & '$VenvPython' -m app.messaging.workers.email"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Email Worker' -ForegroundColor Cyan; $emailCmd"

    Write-Host "Launching In-App Notify Worker..." -ForegroundColor Yellow
    $notifyCmd = "cd '$RepoRoot\backend'; & '$VenvPython' -m app.messaging.workers.notify"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Notify Worker' -ForegroundColor Cyan; $notifyCmd"

    Write-Host "Launching Daily Digest Worker..." -ForegroundColor Yellow
    $digestCmd = "cd '$RepoRoot\backend'; & '$VenvPython' -m app.messaging.workers.digest"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Digest Worker' -ForegroundColor Cyan; $digestCmd"
}

# 4. Launch Frontend
if (-not $NoFrontend) {
    Write-Host "Launching Vite Frontend on http://localhost:5173..." -ForegroundColor Yellow
    $frontendCmd = "cd '$RepoRoot\frontend'; npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'GymPro Frontend' -ForegroundColor Cyan; $frontendCmd"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " All services started in dedicated process windows." -ForegroundColor Green
Write-Host " Web UI:    http://localhost:5173" -ForegroundColor Cyan
Write-Host " API Docs:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host " Mail UI:   http://localhost:8025 (or mail_outbox/ folder)" -ForegroundColor Cyan
Write-Host " RabbitMQ:  http://localhost:15672 (guest / guest)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
