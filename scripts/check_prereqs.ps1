<#
.SYNOPSIS
    Prerequisite verification script for GymPro AI company PC migration.
.DESCRIPTION
    Verifies that Python 3.11+, Node.js 20+, PostgreSQL 15+, RabbitMQ 3.12+,
    Mailpit (or dev_smtp_sink), and Git are installed.
    Checks port availability and reports missing software without installing anything.
.NOTES
    Conforms to Spec Phase P14 Part A. Never installs software.
#>

[CmdletBinding()]
param (
    [switch]$Detailed
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " GymPro AI: Company PC Prerequisites Verification" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$MissingCount = 0
$Results = @()

# Helper function to check command on PATH or specific paths
function Find-Tool {
    param (
        [string]$Name,
        [string[]]$CandidatePaths
    )
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    foreach ($p in $CandidatePaths) {
        if ($p -and (Test-Path $p)) {
            return (Resolve-Path $p).Path
        }
    }
    return $null
}

# 1. Python (3.11+)
$PythonPath = Find-Tool "python" @("C:\Python312\python.exe", "C:\Python311\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")
if ($PythonPath) {
    $pyVerStr = & $PythonPath --version 2>&1
    if ($pyVerStr -match "Python (\d+)\.(\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -ge 3 -and $minor -ge 11) {
            $Results += [PSCustomObject]@{ Tool = "Python"; Status = "OK"; Version = $pyVerStr; Path = $PythonPath }
        } else {
            $Results += [PSCustomObject]@{ Tool = "Python"; Status = "OUTDATED"; Version = "$pyVerStr (Requires 3.11+)"; Path = $PythonPath }
            $MissingCount++
        }
    } else {
        $Results += [PSCustomObject]@{ Tool = "Python"; Status = "UNKNOWN"; Version = $pyVerStr; Path = $PythonPath }
    }
} else {
    $Results += [PSCustomObject]@{ Tool = "Python"; Status = "MISSING"; Version = "Not found"; Path = "N/A" }
    $MissingCount++
}

# 2. Node.js (20+) & npm
$NodePath = Find-Tool "node" @("C:\Program Files\nodejs\node.exe")
if ($NodePath) {
    $nodeVer = & $NodePath --version 2>&1
    if ($nodeVer -match "v(\d+)\.") {
        $nodeMajor = [int]$Matches[1]
        if ($nodeMajor -ge 20) {
            $Results += [PSCustomObject]@{ Tool = "Node.js"; Status = "OK"; Version = $nodeVer; Path = $NodePath }
        } else {
            $Results += [PSCustomObject]@{ Tool = "Node.js"; Status = "OUTDATED"; Version = "$nodeVer (Requires v20+)"; Path = $NodePath }
            $MissingCount++
        }
    }
} else {
    $Results += [PSCustomObject]@{ Tool = "Node.js"; Status = "MISSING"; Version = "Not found"; Path = "N/A" }
    $MissingCount++
}

# 3. PostgreSQL (15+)
$PsqlPath = Find-Tool "psql" @("C:\Program Files\PostgreSQL\17\bin\psql.exe", "C:\Program Files\PostgreSQL\16\bin\psql.exe", "C:\Program Files\PostgreSQL\15\bin\psql.exe")
if ($PsqlPath) {
    $psqlVerStr = & $PsqlPath --version 2>&1
    if ($psqlVerStr -match "psql \(PostgreSQL\) (\d+)\.") {
        $pgMajor = [int]$Matches[1]
        if ($pgMajor -ge 15) {
            $Results += [PSCustomObject]@{ Tool = "PostgreSQL"; Status = "OK"; Version = $psqlVerStr; Path = $PsqlPath }
        } else {
            $Results += [PSCustomObject]@{ Tool = "PostgreSQL"; Status = "OUTDATED"; Version = "$psqlVerStr (Requires 15+)"; Path = $PsqlPath }
            $MissingCount++
        }
    } else {
        $Results += [PSCustomObject]@{ Tool = "PostgreSQL"; Status = "OK"; Version = $psqlVerStr; Path = $PsqlPath }
    }
} else {
    $Results += [PSCustomObject]@{ Tool = "PostgreSQL"; Status = "MISSING"; Version = "Not found"; Path = "N/A" }
    $MissingCount++
}

# 4. RabbitMQ & Erlang
$RmqPath = Find-Tool "rabbitmqctl" @("C:\Program Files\RabbitMQ Server\rabbitmq_server-*\sbin\rabbitmqctl.bat")
$rmqRunning = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $iar = $tcp.BeginConnect("127.0.0.1", 5672, $null, $null)
    $success = $iar.AsyncWaitHandle.WaitOne(1000)
    if ($success -and $tcp.Connected) {
        $rmqRunning = $true
        $tcp.EndConnect($iar)
    }
    $tcp.Close()
} catch {}

if ($rmqRunning) {
    $Results += [PSCustomObject]@{ Tool = "RabbitMQ"; Status = "OK"; Version = "Running on port 5672"; Path = "127.0.0.1:5672" }
} elseif ($RmqPath) {
    $Results += [PSCustomObject]@{ Tool = "RabbitMQ"; Status = "INSTALLED (NOT RUNNING)"; Version = "Found rabbitmqctl"; Path = $RmqPath }
} else {
    $Results += [PSCustomObject]@{ Tool = "RabbitMQ"; Status = "MISSING"; Version = "Service not detected on 5672"; Path = "N/A" }
    $MissingCount++
}

# 5. Mailpit / SMTP Sink
$MailpitEnv = $env:MAILPIT_PATH
$MailpitPath = Find-Tool "mailpit" @($MailpitEnv, "tools\mailpit.exe", "..\tools\mailpit.exe", "C:\tools\mailpit\mailpit.exe")
$mailpitListening = $false
try {
    $tcpM = New-Object System.Net.Sockets.TcpClient
    $iarM = $tcpM.BeginConnect("127.0.0.1", 1025, $null, $null)
    $successM = $iarM.AsyncWaitHandle.WaitOne(1000)
    if ($successM -and $tcpM.Connected) {
        $mailpitListening = $true
        $tcpM.EndConnect($iarM)
    }
    $tcpM.Close()
} catch {}

if ($mailpitListening) {
    $Results += [PSCustomObject]@{ Tool = "Mailpit/SMTP"; Status = "OK"; Version = "Listening on port 1025"; Path = "127.0.0.1:1025" }
} elseif ($MailpitPath) {
    $Results += [PSCustomObject]@{ Tool = "Mailpit/SMTP"; Status = "INSTALLED"; Version = "Ready to start"; Path = $MailpitPath }
} else {
    # Check fallback sink availability
    $sinkPath = Join-Path $PSScriptRoot "dev_smtp_sink.py"
    if (Test-Path $sinkPath) {
        $Results += [PSCustomObject]@{ Tool = "Mailpit/SMTP"; Status = "FALLBACK READY"; Version = "dev_smtp_sink.py available"; Path = $sinkPath }
    } else {
        $Results += [PSCustomObject]@{ Tool = "Mailpit/SMTP"; Status = "MISSING"; Version = "Mailpit binary not found"; Path = "N/A" }
        $MissingCount++
    }
}

# 6. Git
$GitPath = Find-Tool "git" @("C:\Program Files\Git\cmd\git.exe")
if ($GitPath) {
    $gitVer = & $GitPath --version 2>&1
    $Results += [PSCustomObject]@{ Tool = "Git"; Status = "OK"; Version = $gitVer; Path = $GitPath }
} else {
    $Results += [PSCustomObject]@{ Tool = "Git"; Status = "MISSING"; Version = "Not found"; Path = "N/A" }
    $MissingCount++
}

# Display results table
$Results | Format-Table -AutoSize -Property Tool, Status, Version, Path

# Port Status Overview
Write-Host ""
Write-Host "Port Availability Check:" -ForegroundColor Yellow
$Ports = @(
    @{ Port = 5432; Service = "PostgreSQL" },
    @{ Port = 5672; Service = "RabbitMQ AMQP" },
    @{ Port = 15672; Service = "RabbitMQ Web UI" },
    @{ Port = 1025; Service = "Mailpit / Dev SMTP" },
    @{ Port = 8025; Service = "Mailpit Web UI" },
    @{ Port = 8000; Service = "GymPro Backend API" },
    @{ Port = 5173; Service = "GymPro Frontend Vite" }
)

foreach ($p in $Ports) {
    $pNum = $p.Port
    $pSvc = $p.Service
    $active = $false
    try {
        $t = New-Object System.Net.Sockets.TcpClient
        $iar = $t.BeginConnect("127.0.0.1", $pNum, $null, $null)
        $conn = $iar.AsyncWaitHandle.WaitOne(400)
        if ($conn -and $t.Connected) {
            $active = $true
            $t.EndConnect($iar)
        }
        $t.Close()
    } catch {}

    if ($active) {
        Write-Host "  Port $pNum ($pSvc): [ACTIVE / BOUND]" -ForegroundColor Green
    } else {
        Write-Host "  Port $pNum ($pSvc): [AVAILABLE]" -ForegroundColor Gray
    }
}

Write-Host ""
if ($MissingCount -eq 0) {
    Write-Host "[PASS] All prerequisites are satisfied for company PC operation." -ForegroundColor Green
    exit 0
} else {
    Write-Host "[FAIL] $MissingCount prerequisite tool(s) are missing or outdated." -ForegroundColor Red
    Write-Host "Consult docs/COMPANY_PC_SETUP.md for IT approval and installation instructions." -ForegroundColor Yellow
    exit 1
}
