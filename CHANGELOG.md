# Changelog

## [Unreleased]

### Added

- Persistent SQLite conversation history with selectable previous chats.
- Voice and text commands for creating and switching conversations.
- Context-aware follow-up media commands such as "YouTube'dan ac".
- Repetition guards for streaming Gemini and text-agent responses.
- Windowed desktop mode and a conversation-focused workspace layout.

### Changed

- Improved microphone device selection and text-mode degradation.
- Hardened provider configuration, logging redaction and public repository CI.

### Fixed

- Prevented malformed provider output from flooding the conversation panel.
- Corrected OpenAI-compatible configuration and settings validation paths.
- Removed tracked backup artifacts and repaired public documentation encoding.

All notable changes to J.A.R.V.I.S are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-06-13

### Added

- **Gemini Live Voice Pipeline** — real-time audio streaming with Gemini 2.5 Flash
  via WebSocket, bidirectional send/receive with interrupt support.
- **Text Agent (OpenAI-compatible)** — fallback text generation supporting any
  OpenAI-compatible endpoint (9Router, direct OpenAI, local LLM).
- **Hybrid Mode** — automatic routing between cloud and local LLM based on task
  complexity and connectivity.
- **Agent Runtime** — plan/execute/evaluate loop with ~70 tools dispatched to
  specialist agents (Research, Desktop, File, Browser, Comms, Memory, Safety,
  Task, Plugin).
- **Web Research Engine** — multi-engine fallback (Tavily, Google News, Bing,
  DuckDuckGo, Jina, Yahoo News) with configurable depth and summarization.
- **Browser Agent** — Playwright-based headless browser for URL reading, form
  filling, clicking, and web research.
- **Desktop Automation** — window listing/focus, hotkey sending, app launching,
  clipboard read/write, screen vision (OCR + Gemini analysis).
- **File Operations** — read, write, append, move, delete, find, and summarize
  text files with path traversal protection.
- **Calendar Integration** — Outlook (Windows) and Google Calendar (OAuth)
  event create/read/delete with multi-calendar support.
- **Reminders & Tasks** — SQLite-backed reminder and follow-up task system with
  Windows startup integration and notification support.
- **WhatsApp Integration** — send messages, find/list contacts, import phone
  books from VCF files.
- **Memory System** — SQLite (FTS5) long-term memory with automatic learning,
  JSON identity/preferences store, and conversation summarization.
- **Plugin System** — MCP-based plugin architecture supporting stdio,
  streamable HTTP, and SSE transports with permission-based safety gates.
- **Wake Word Detection** — Porcupine and Vosk wake-word engines with lazy
  initialization.
- **TTS Engine** — pyttsx3 (Windows) and `say` (macOS) speech synthesis with
  interrupt and voice selection.
- **Central Safety Registry** — 50+ tool risk policies with approval workflow
  for write/send/execute/delete operations; untrusted content isolation.
- **Audit Logging** — JSONL audit trail with secret redaction.
- **Trace Manager** — JSONL trace logging with run tracking, tool logging,
  error capture, and research detail extraction.
- **Smoke Test System** — 7-step automated smoke sequence (UI, command, web
  research, file read, app launch, screen analysis, TTS) with timeout reporting.
- **Cyberpunk UI** — Tkinter full-screen ORB animation with real-time stats
  panels (time, weather, system, health), conversation log, and setup dialog.
- **Scheduler** — background task scheduler with configurable intervals,
  follow-up task creation, and Windows startup tracking.
- **Calendar Helper (macOS)** — Swift-based EventKit integration for macOS
  calendar querying and event management.
- **Screen Helper (macOS)** — Swift-based active window screen capture.
- **MCP Client** — universal MCP client supporting stdio, streamable HTTP, and
  SSE transports with tool discovery.
- **Platform Abstraction** — unified `platform_utils.py` for Windows/macOS
  detection and cross-platform URL opening.

### Infrastructure

- GitHub Actions CI pipeline with Windows/macOS runners.
- Acceptance gate with compileall, unittest discovery, and secret scanning.
- pip-audit dependency vulnerability scanning.
- `setup_windows.ps1` / `run_windows.ps1` — PowerShell installation and launch
  scripts.
- `setup.sh` — macOS installation script with Homebrew and PortAudio support.
- Pyright configuration for type checking.
- `.gitignore` covering runtime data, secrets, caches, and build artifacts.

### Security

- All API keys and OAuth tokens excluded from version control.
- Central risk classification for every tool (`read`, `write`, `send`,
  `execute`, `delete`, `external`).
- Approval gate for all high-risk operations.
- Audit logging with automatic secret redaction.
- Command allowlist for shell execution.
- Plugin permission system with per-tool allowlists.
- Path traversal protection in file operations.
- Untrusted content isolation (web, files, clipboard, OCR).

[1.0.0]: https://github.com/vscoderkek65-dot/J.A.R.V.I.S/releases/tag/v1.0.0
