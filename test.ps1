# ChiefMailVault - run test suite before committing changes
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"

Set-Location $Root

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    & $VenvPip install -r requirements.txt -q
}

Write-Host ""
Write-Host "Running ChiefMailVault tests..." -ForegroundColor Cyan
Write-Host ""

& $VenvPython -m pytest tests/ -v --tb=short
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "All tests passed." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Tests failed. Fix issues before deploying." -ForegroundColor Red
}

exit $exitCode
