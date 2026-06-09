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

Write-Host "[1/3] Static parse: python -m compileall -q ."
& $venvPython -m compileall -q .
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[2/3] Unit/regression tests: python -m unittest discover -s tests -v"
& $venvPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[3/3] Secret scan: committed text files"
$patterns = @(
    @{Name='openai_like_key'; Regex='sk-[A-Za-z0-9_\-]{20,}'},
    @{Name='tavily_key'; Regex='tvly-[A-Za-z0-9_\-]{20,}'},
    @{Name='google_api_key'; Regex='AIza[A-Za-z0-9_\-]{20,}'},
    @{Name='bearer_token'; Regex='Bearer\s+[A-Za-z0-9._\-]{20,}'},
    @{Name='long_secret_assignment'; Regex='(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*["''][^"'']{12,}["'']'}
)
$trackedFiles = git ls-files | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
$hits = @()
foreach ($file in $trackedFiles) {
    $lineNo = 0
    try {
        Get-Content -LiteralPath $file -ErrorAction Stop | ForEach-Object {
            $lineNo += 1
            $line = $_
            foreach ($pattern in $patterns) {
                if ($line -match $pattern.Regex) {
                    $hits += [pscustomobject]@{ File=$file; Line=$lineNo; Pattern=$pattern.Name }
                }
            }
        }
    } catch {
        # Binary or unreadable tracked files are skipped.
    }
}
if ($hits.Count -gt 0) {
    Write-Host "Potential committed secrets found:" -ForegroundColor Red
    $hits | Sort-Object File,Line,Pattern | Format-Table -AutoSize
    exit 1
}

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
