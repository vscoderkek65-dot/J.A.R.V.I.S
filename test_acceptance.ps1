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

$exitCode = 0

Write-Host ""
Write-Host "========================================"
Write-Host "   J.A.R.V.I.S Acceptance Gate v1.0"
Write-Host "========================================"
Write-Host ""

# ── [1/5] Static parse ─────────────────────────────────────────────────
Write-Host "[1/5] Static parse: compileall -q" -ForegroundColor Cyan
& $venvPython -m compileall -q .
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: compileall failed" -ForegroundColor Red
    $exitCode = 1
} else {
    Write-Host "  PASS" -ForegroundColor Green
}

# ── [2/5] Ruff linting ─────────────────────────────────────────────────
Write-Host "[2/5] Code quality: ruff check" -ForegroundColor Cyan
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ruffCheck = & $venvPython -m ruff check actions/ core/ memory/ ui/ tests/ `
    --select E9,F63,F7,F82 --quiet 2>&1
$ruffExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($ruffExitCode -ne 0) {
    Write-Host "  Issues found:" -ForegroundColor Yellow
    $ruffCheck | ForEach-Object { Write-Host "    $_" }
    Write-Host "  Run 'ruff format' to auto-fix." -ForegroundColor Yellow
    # Non-blocking for now — warn but don't fail
    Write-Host "  WARN (non-blocking)" -ForegroundColor Yellow
} else {
    Write-Host "  PASS" -ForegroundColor Green
}

# ── [3/5] Unit/regression tests ───────────────────────────────────────
Write-Host "[3/5] Unit tests: unittest discover -s tests -v" -ForegroundColor Cyan
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $venvPython -m unittest discover -s tests -v 2>&1
$testExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($testExitCode -ne 0) {
    Write-Host "FAIL: Unit tests failed" -ForegroundColor Red
    $exitCode = 1
} else {
    Write-Host "  PASS" -ForegroundColor Green
}

# ── [4/5] Secret scan ──────────────────────────────────────────────────
Write-Host "[4/5] Secret scan: committed text files" -ForegroundColor Cyan
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
    Write-Host "FAIL: Potential committed secrets found:" -ForegroundColor Red
    $hits | Sort-Object File,Line,Pattern | Format-Table -AutoSize
    $exitCode = 1
} else {
    Write-Host "  PASS" -ForegroundColor Green
}

# ── [5/5] Version consistency ──────────────────────────────────────────
Write-Host "[5/5] Version consistency check" -ForegroundColor Cyan
$versionFile = Join-Path $PSScriptRoot "VERSION"
if (Test-Path $versionFile) {
    $version = Get-Content $versionFile -Raw | ForEach-Object { $_.Trim() }
    Write-Host "  VERSION file: $version" -ForegroundColor Green

    # Check git tag matches if on a tag
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $gitTag = git describe --exact-match --tags HEAD 2>$null
    $ErrorActionPreference = $previousErrorActionPreference
    if ($gitTag) {
        $tagVersion = $gitTag -replace "^v", ""
        if ($tagVersion -eq $version) {
            Write-Host "  Git tag matches: $gitTag" -ForegroundColor Green
        } else {
            Write-Host "  WARN: Git tag ($gitTag) != VERSION file ($version)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  WARN: VERSION file not found" -ForegroundColor Yellow
}

# ── Summary ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================"
if ($exitCode -eq 0) {
    Write-Host "  Acceptance gate PASSED" -ForegroundColor Green
} else {
    Write-Host "  Acceptance gate FAILED (exit code: $exitCode)" -ForegroundColor Red
}
Write-Host "========================================"
Write-Host ""

# ── Optional: live smoke ──────────────────────────────────────────────
if ($Smoke -and $exitCode -eq 0) {
    Write-Host "[Smoke] Running live Windows smoke..." -ForegroundColor Cyan
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_windows.ps1") -Smoke -SmokeTimeoutSeconds $SmokeTimeoutSeconds -SmokeApp $SmokeApp
    if ($LASTEXITCODE -ne 0) {
        $exitCode = $LASTEXITCODE
    }
}

exit $exitCode
