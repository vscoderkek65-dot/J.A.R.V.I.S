# Contributing to J.A.R.V.I.S

## Development Setup

```powershell
git clone https://github.com/vscoderkek65-dot/J.A.R.V.I.S.git
cd J.A.R.V.I.S
git checkout -b feat/short-description
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

## Required Checks

Before opening a pull request:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
```

For UI, audio, browser or Windows integration changes:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

## Safety Requirements

- Every new tool must be listed in the central safety registry.
- `write`, `send`, `execute` and `delete` operations require explicit approval.
- Unknown tools and plugins remain blocked by default.
- Web, file, clipboard, OCR and MCP output must remain untrusted content.
- Secrets, tokens, OAuth caches, SQLite databases and runtime logs must never be committed.

## Code and Commit Standards

- Keep changes focused and include regression tests.
- Preserve public tool names and config compatibility unless a migration is documented.
- Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `ci:` or `chore:`.
- Update `CHANGELOG.md` under `Unreleased` for user-facing changes.
- Do not use `--no-verify` or force-push the default branch.

## Pull Requests

Describe:

1. What changed and why.
2. Security or compatibility impact.
3. Commands used to validate the change.
4. Known limitations or follow-up work.

By contributing, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
