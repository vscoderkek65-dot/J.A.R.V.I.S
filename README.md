<div align="center">

# 🤖 J.A.R.V.I.S

**Just A Rather Very Intelligent System**

*Windows/macOS desktop assistant powered by Gemini, OpenAI, and local AI*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/ci.yml/badge.svg)](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/ci.yml)
[![CodeQL](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/codeql.yml/badge.svg)](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/vscoderkek65-dot/J.A.R.V.I.S)](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey)](README.md)

</div>

---

## ✨ Overview

J.A.R.V.I.S is a desktop AI assistant that combines **voice interaction**, **text-based AI**, **web research**, **desktop automation**, **memory**, and **task management** into a single cyberpunk-themed UI.

It supports three operating modes:

| Mode | Description |
|------|-------------|
| **Cloud** | Uses OpenAI / 9Router API for intelligent responses |
| **Local** | Runs entirely offline via Foundry Local or any OpenAI-compatible local endpoint |
| **Hybrid** | Smart routing — local for fast/offline tasks, cloud for web research and complex planning |

### Key Capabilities

- 🎤 **Gemini Live Voice** — real-time voice conversation with Gemini 2.5 Flash
- 💬 **Text Agent** — OpenAI-compatible chat for typed commands
- 🌐 **Web Research** — multi-engine search with Tavily, Google News, Bing, DuckDuckGo & more
- 🖥️ **Desktop Control** — window management, hotkeys, app launching, clipboard
- 📁 **File Operations** — read, write, search, organize files with safety gates
- 🧠 **Memory System** — long-term SQLite + JSON memory with auto-learning
- 📅 **Calendar & Tasks** — Outlook/Google Calendar integration + follow-up task scheduler
- 📱 **WhatsApp** — send messages and manage contacts
- 🔌 **Plugin System** — MCP-based extensibility with permission controls
- 🛡️ **Security First** — every action is classified, risky ones require approval

---

## 🚀 Quick Start

### Windows

```powershell
# 1. Install
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

# 2. Configure API keys (edit config/api_keys.json)
#    Or use the setup dialog when the app launches.

# 3. Run
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1
```

### macOS

```bash
chmod +x setup.sh && ./setup.sh
```

> The setup script creates a `venv`, installs dependencies, and copies
> `config/api_keys.example.json` to `config/api_keys.json`.

---

## ⚙️ Configuration

Edit `config/api_keys.json` after first run:

```json
{
  "agent_mode": "hybrid",
  "cloud_base_url": "https://api.9router.com/v1",
  "cloud_model": "gpt-4o",
  "cloud_api_key": "<your-key>",
  "local_base_url": "http://localhost:1234/v1",
  "local_model": "",
  "local_api_key": "",
  "voice_input_mode": "ptt",
  "wake_word_enabled": false
}
```

### Agent Modes

| Setting    | Behavior |
|------------|----------|
| `cloud`    | All requests go to the cloud API |
| `local`    | All requests go to the local endpoint |
| `hybrid`   | Smart routing based on task and connectivity |

### Voice Input Modes

| Setting | Behavior |
|---------|----------|
| `ptt`   | Push-to-talk (hold to speak) |
| `wake`  | Wake-word activated ("Jarvis" / "Computer") |
| `live`  | Gemini Live streaming (always listening) |

---

## 🧪 Smoke Testing

```powershell
# Quick acceptance gate (compile + unit tests + secret scan)
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1

# Full live smoke test (requires working API keys)
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

Smoke reports are saved to `memory/smoke/` (excluded from git).

---

## 🛡️ Security Model

J.A.R.V.I.S uses a **central safety registry** that classifies every tool:

| Risk Level | Requires Approval | Examples |
|------------|-------------------|----------|
| `read`     | ❌ No             | Read files, clipboard, system info |
| `external` | ❌ No             | Web searches, URL fetching |
| `write`    | ✅ Yes            | Create/modify files, set clipboard |
| `send`     | ✅ Yes            | WhatsApp, email |
| `execute`  | ✅ Yes            | Shell commands, hotkeys, browser automation |
| `delete`   | ✅ Yes            | Delete files, calendar events |

All high-risk operations:
- ⏳ Pause for user approval
- 📝 Log to the audit trail (with secret redaction)
- 🚫 Block untrusted content from being treated as instructions

---

## 📂 Project Structure

```
J.A.R.V.I.S/
├── actions/            # Tool implementations (browser, files, desktop, etc.)
├── config/             # API keys (gitignored) and example config
├── core/               # Core engine: agent runtime, LLM client, live pipeline
├── docs/               # Architecture, roadmap, release notes
├── Fonts/              # Grift font family for UI
├── helpers/            # macOS Swift helpers (calendar, screen capture)
├── memory/             # SQLite + JSON storage (gitignored runtime data)
├── plugins/            # MCP plugin manifests
├── SFX/                # Sound effects
├── tests/              # Unit and integration tests
├── main.py             # Entry point
├── ui.py               # Tkinter UI (ORB animation, panels, dialogs)
├── app_config.py       # Configuration loader
├── VERSION             # Current version (semver)
└── CHANGELOG.md        # Release history
```

---

## 🔌 Optional Dependencies

```powershell
# Playwright (browser automation)
.\venv\Scripts\python.exe -m playwright install chromium

# PyAudio (microphone input)
.\venv\Scripts\python.exe -m pip install -r requirements-voice.txt

# Tesseract OCR (screen text recognition)
winget install UB-Mannheim.TesseractOCR
```

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for our contribution guidelines.

- All new tools **must** be registered in the safety registry
- Run `.\test_acceptance.ps1` before submitting changes
- Never commit API keys or runtime databases

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <sub>Built with Python, Tkinter, and too much coffee ☕</sub>
</div>
