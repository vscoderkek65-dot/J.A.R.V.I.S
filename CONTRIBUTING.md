# Contributing

## Local Checks

Run the acceptance gate before submitting changes:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
```

For live Windows validation:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

## Commit Hygiene

- Keep runtime data out of git.
- Do not commit `config/api_keys.json`.
- Do not commit sqlite databases, traces, audit logs, smoke reports, or plugin state.
- Prefer small changes with tests.
- Preserve existing tool names and config compatibility unless a migration is explicit.

## Safety Requirements

Any new tool must be registered in the central safety registry with a risk class. Unknown tools are blocked by default. Risky actions must request approval and write audit events.
