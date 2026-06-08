param(
    [switch]$Smoke,
    [int]$SmokeTimeoutSeconds = 90,
    [string]$SmokeApp = "explorer"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "venv bulunamadi. Once kurulumu calistirin:" -ForegroundColor Red
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1"
    exit 1
}

Write-Host ""
Write-Host "========================================"
Write-Host "        J.A.R.V.I.S Acceptance Gate"
Write-Host "========================================"
Write-Host ""

Write-Host "[1/2] Static parse: python -m compileall -q ."
& $venvPython -m compileall -q .

Write-Host "[2/2] Unit/regression tests: python -m unittest discover -s tests -v"
& $venvPython -m unittest discover -s tests -v

Write-Host ""
Write-Host "Acceptance gate passed." -ForegroundColor Green
Write-Host ""
Write-Host "Manual Windows smoke checklist:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\run_windows.ps1"
Write-Host "  - UI opens"
Write-Host "  - Written command works"
Write-Host "  - Web research works"
Write-Host "  - File read works"
Write-Host "  - App launching works"
Write-Host "  - Screen analysis works"
Write-Host "  - TTS works, or broken microphone/audio falls back to TEXT MODE without crashing"

if ($Smoke) {
    Write-Host ""
    Write-Host "[Smoke] Running live Windows smoke..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_windows.ps1") -Smoke -SmokeTimeoutSeconds $SmokeTimeoutSeconds -SmokeApp $SmokeApp
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
