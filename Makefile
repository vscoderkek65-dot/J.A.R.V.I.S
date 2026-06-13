.PHONY: setup test smoke clean lint format audit secret devcontainer

SHELL := powershell.exe
PYTHON := .\venv\Scripts\python.exe
PIP := .\venv\Scripts\pip.exe

# ── Setup ──────────────────────────────────────────────────────────────
setup:
	powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

setup-dev: setup
	$(PIP) install -r requirements-dev.txt
	$(PYTHON) -m playwright install chromium
	$(PYTHON) -m pre-commit install

# ── Testing ────────────────────────────────────────────────────────────
test:
	powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1

test-coverage:
	$(PYTHON) -m pytest tests/ -v --cov=actions --cov=core --cov=memory --cov-report=term --cov-report=html:test-reports/coverage

smoke:
	powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer

# ── Code Quality ───────────────────────────────────────────────────────
lint:
	$(PYTHON) -m ruff check actions/ core/ memory/ tests/ plugins/
	$(PYTHON) -m ruff format --check actions/ core/ memory/ tests/ plugins/

format:
	$(PYTHON) -m ruff check --fix actions/ core/ memory/ tests/ plugins/
	$(PYTHON) -m ruff format actions/ core/ memory/ tests/ plugins/

typecheck:
	$(PYTHON) -m mypy actions/ core/ memory/ --ignore-missing-imports --no-strict-optional

# ── Security ───────────────────────────────────────────────────────────
audit:
	$(PIP) install pip-audit
	$(PYTHON) -m pip_audit -r requirements.txt

secret:
	$(PYTHON) -m detect_secrets scan --baseline .secrets.baseline

bandit:
	$(PYTHON) -m bandit -r actions/ core/ --configfile pyproject.toml

# ── Git Hooks ──────────────────────────────────────────────────────────
pre-commit:
	$(PYTHON) -m pre-commit run --all-files

pre-commit-install:
	$(PYTHON) -m pre-commit install

# ── Dev Environment ───────────────────────────────────────────────────
devcontainer:
	@echo "Open in VS Code Dev Containers: Ctrl+Shift+P → Reopen in Container"

clean:
	@echo "Cleaning Python cache..."
	@for /r %%i in (__pycache__) do @if exist "%%i" rmdir /s /q "%%i"
	@echo "Cleaning test reports..."
	@if exist "test-reports" rmdir /s /q "test-reports"
	@echo "Done."

# ── Help ───────────────────────────────────────────────────────────────
help:
	@echo "J.A.R.V.I.S Makefile"
	@echo "━━━━━━━━━━━━━━━━━━━"
	@echo "setup      — Full environment setup"
	@echo "test       — Run acceptance gate"
	@echo "lint       — Run ruff linter"
	@echo "format     — Auto-format code"
	@echo "typecheck  — Run mypy type checker"
	@echo "audit      — Run pip-audit"
	@echo "secret     — Run detect-secrets scan"
	@echo "smoke      — Run live smoke test"
	@echo "clean      — Remove cache files"
