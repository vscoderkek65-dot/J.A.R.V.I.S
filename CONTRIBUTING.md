# Contributing to J.A.R.V.I.S

Thank you for your interest in contributing! Here's how you can help.

---

## 🧪 Local Checks

Run the acceptance gate before submitting any change:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
```

For live Windows smoke validation:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

---

## 📝 Commit Hygiene

- **Keep runtime data out of git.**
- Do not commit `config/api_keys.json`, `*.sqlite3`, traces, audit logs, smoke
  reports, or plugin state files.
- Follow the [Conventional Commits](https://www.conventionalcommits.org/) style:
  - `feat:` — new capability
  - `fix:` — bug fix
  - `refactor:` — code restructuring
  - `docs:` — documentation
  - `test:` — test changes
  - `ci:` — CI/CD configuration
  - `chore:` — maintenance tasks
- Prefer small, focused commits over large monolithic ones.
- Preserve existing tool names and config compatibility unless a migration is
  explicitly documented.

---

## 🛡️ Safety Requirements

Any new tool **must** be registered in the central safety registry with a
risk class. Unknown tools are blocked by default.

For high-risk operations:
- Add an entry to `TOOL_RISK_REGISTRY` with the appropriate risk level
- Ensure the approval workflow is triggered
- Log all invocations through the audit system

See `actions/safety.py` for the existing risk policies and registry format.

---

## 🧪 Testing

- Add unit tests in the `tests/` directory following existing patterns
- Tests should be self-contained and not require live API keys
- Run tests locally: `python -m unittest discover -s tests -v`
- For integration tests, use the smoke test framework

---

## 🔧 Development Setup

```powershell
# 1. Fork and clone the repository
git clone https://github.com/your-username/J.A.R.V.I.S.git
cd J.A.R.V.I.S

# 2. Create a feature branch
git checkout -b feat/your-feature

# 3. Set up the environment
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

# 4. Make your changes and test
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1

# 5. Commit and push
git add .
git commit -m "feat: your feature description"
git push origin feat/your-feature

# 6. Open a Pull Request
```

---

## 📋 Pull Request Checklist

- [ ] Acceptance gate passes (compileall + tests + secret scan)
- [ ] New tools have safety registry entries
- [ ] No runtime data or secrets committed
- [ ] CHANGELOG.md updated under "Unreleased" section
- [ ] Documentation updated if API or behavior changed

---

## 📖 Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md). All
contributors are expected to create a welcoming and respectful environment.
