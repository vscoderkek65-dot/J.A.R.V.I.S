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

if (-not (Test-Path (Join-Path $PSScriptRoot "config\api_keys.json"))) {
    Copy-Item (Join-Path $PSScriptRoot "config\api_keys.example.json") (Join-Path $PSScriptRoot "config\api_keys.json")
}

$pythonArgs = @((Join-Path $PSScriptRoot "main.py"))
if ($Smoke) {
    $pythonArgs += "--smoke"
    $pythonArgs += "--smoke-timeout"
    $pythonArgs += "$SmokeTimeoutSeconds"
    $pythonArgs += "--smoke-app"
    $pythonArgs += "$SmokeApp"
}

& $venvPython @pythonArgs
exit $LASTEXITCODE
