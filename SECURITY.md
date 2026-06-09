# Security Policy

## Supported Scope

This project targets Windows 10/11 desktop usage. Security fixes focus on the current `main` branch.

## Secret Handling

Do not commit real API keys, OAuth tokens, sqlite runtime databases, traces, audit logs, smoke reports, or plugin state. The `.gitignore` file excludes the expected runtime paths.

Before publishing changes, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
```

## Risk Model

Risky actions must go through the central approval/audit layer:

- file write, move, delete
- shell command execution
- desktop hotkeys and automation
- browser click, fill, submit
- WhatsApp send-now flows
- startup/system changes

Web pages, files, clipboard text, OCR text, and MCP/plugin output are untrusted content. They must not be treated as system instructions.

## Reporting

If you find a vulnerability, open a private report or contact the repository owner through GitHub. Do not include live secrets in an issue, pull request, screenshot, trace, or smoke report.
