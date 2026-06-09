# JARVIS Roadmap

## Phase 1 - Public Repo and Windows Setup Hardening

- Keep public docs current: README, security policy, contribution notes, CI.
- Keep PyAudio optional; text-mode must remain available when microphone setup fails.
- Keep Playwright, OCR, wake-word, and local AI setup clearly marked as optional.

## Phase 2 - Safety and Risk Model

- Replace broad shell execution with structured, read-only allowlisted commands.
- Keep risky desktop, browser, file, messaging, startup, and plugin actions behind approval.
- Keep prompt-injection tests for web/file/clipboard/OCR/plugin content.

## Phase 3 - Smoke, Trace, and Debug

- Use structured smoke step status and machine-readable reason codes.
- Keep quick acceptance fast and live smoke explicit.
- Add user-facing explanations for "why degraded" and "why not found" flows.

## Phase 4 - Research and Browser Agent Quality

- Improve source scoring by intent: local news, general research, technical research.
- Keep Tavily useful but non-required.
- Keep Jina Reader as page-reading fallback, not a search engine.
- Keep spoken answers concise and source-backed.

## Phase 5 - Architecture Modularization

- Split tool dispatch, CLI/smoke entrypoint, voice runtime, and provider routing out of `main.py`.
- Split settings screens, status widgets, log panel, and SFX controller out of `ui.py`.
- Preserve `main.py`, `run_windows.ps1`, tool names, and config compatibility.

## Phase 6 - Provider and Account Integrations

- Present provider choices clearly: OpenAI API, 9Router/OpenAI-compatible, Local, Hybrid.
- Make it clear that ChatGPT Plus/Business OAuth is not a substitute for model API access.
- Add OpenAI API preset support with `https://api.openai.com/v1`.
- Improve local/offline health messages.

## Phase 7 - Product Experience and Distribution

- Add first-run config wizard.
- Add portable Windows packaging and release artifacts.
- Keep UI states explicit: listening, thinking, researching, speaking, waiting approval, error.
- Publish releases with smoke results and upgrade notes.
