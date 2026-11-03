# ChiefMailVault - local dev launcher
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"
$BindAddress = "127.0.0.1"

Set-Location $Root

function Get-PortListenerPids {
    param([int]$TargetPort)
    $pids = [System.Collections.Generic.HashSet[int]]::new()
    try {
        $conns = Get-NetTCPConnection -LocalPort $TargetPort -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' }
        foreach ($c in $conns) { [void]$pids.Add($c.OwningProcess) }
    } catch { }
    $netstat = netstat -ano | Select-String ":$TargetPort\s+.*LISTENING"
    foreach ($line in $netstat) {
        if ($line -match '\s+(\d+)\s*$') { [void]$pids.Add([int]$Matches[1]) }
    }
    return @($pids | Where-Object { $_ -gt 0 -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
}

function Stop-PortListeners {
    param([int]$TargetPort)
    foreach ($procId in (Get-PortListenerPids -TargetPort $TargetPort)) {
        if ($procId -eq $PID) { continue }
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Write-Host "Stopping process on port ${TargetPort} (PID $procId, $($proc.ProcessName))..." -ForegroundColor Yellow
        cmd /c "taskkill /F /PID $procId /T" 2>$null | Out-Null
    }
    Start-Sleep -Seconds 1
}

function Test-PortBindable {
    param([int]$TargetPort, [string]$BindHost)
    $code = @"
import socket, sys
s = socket.socket()
try:
    s.bind(('$BindHost', $TargetPort))
except OSError:
    sys.exit(1)
finally:
    s.close()
"@
    & $VenvPython -c $code
    return ($LASTEXITCODE -eq 0)
}

function Find-AvailablePort {
    param([int[]]$Candidates, [string]$BindHost)
    foreach ($p in $Candidates) {
        Stop-PortListeners -TargetPort $p
        if (Test-PortBindable -TargetPort $p -BindHost $BindHost) {
            return $p
        }
        Write-Host "Port $p is blocked (possibly a ghost listener) - trying next..." -ForegroundColor DarkYellow
    }
    return $null
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

if (-not (Test-Path (Join-Path $Root ".venv\Lib\site-packages\fastapi"))) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    & $VenvPip install -r requirements.txt -q
}

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "No .env found - copying from .env.example" -ForegroundColor Yellow
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
}

$preferred = if ($env:CMV_PORT) { [int]$env:CMV_PORT } else { 8088 }
$candidates = @($preferred) + @(18088, 9088, 8188, 8888) | Select-Object -Unique
$Port = Find-AvailablePort -Candidates $candidates -BindHost $BindAddress

if (-not $Port) {
    Write-Host ""
    Write-Host "ERROR: No available port found. Tried: $($candidates -join ', ')" -ForegroundColor Red
    Write-Host "Run .\stop.ps1 or restart Windows to clear ghost listeners." -ForegroundColor Yellow
    exit 1
}

if ($Port -ne $preferred) {
    Write-Host "Note: Port $preferred was blocked - using port $Port instead." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "ChiefMailVault" -ForegroundColor Cyan
Write-Host "  URL:  http://${BindAddress}:${Port}" -ForegroundColor Green
Write-Host "  Login: admin / admin123 (change in .env)" -ForegroundColor DarkGray
Write-Host "  Press Ctrl+C to stop  |  Run .\stop.ps1 to stop from another terminal" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython -m uvicorn app.main:app --host $BindAddress --port $Port
