# Release and Packaging Notes

## Pre-release Gate

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

Release is blocked if:

- compileall fails
- unit/regression tests fail
- secret scan finds a high-confidence secret
- live smoke has a critical `fail`

`degraded` smoke is acceptable only when the reason is documented, for example missing microphone, optional TTS voice, missing Gemini key, or screen permission limits.

## Portable Package Shape

Recommended first public package:

- source zip from GitHub Release
- `setup_windows.ps1`
- `run_windows.ps1`
- `config/api_keys.example.json`
- documented optional commands for Playwright, PyAudio, Tesseract, and Local AI

Do not package:

- `venv/`
- `config/api_keys.json`
- sqlite databases
- OAuth tokens
- audit, trace, and smoke reports

## Future Installer

The first installer should remain conservative:

- create a project folder
- run setup
- create a Start Menu/Desktop shortcut to `run_windows.ps1`
- open first-run config wizard
- never collect or upload local logs automatically

## Release Notes Checklist

- Summarize feature changes.
- Include acceptance gate result.
- Include live smoke status and report reason codes.
- Call out breaking config changes, if any.
- List optional dependencies that changed.
