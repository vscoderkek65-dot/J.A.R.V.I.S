# Architecture Notes

## Stable Public Entrypoints

- `main.py`: application entrypoint, including normal UI mode and smoke mode.
- `run_windows.ps1`: Windows launcher.
- `setup_windows.ps1`: Windows setup.
- `config/api_keys.example.json`: documented config shape.
- Existing tool names: must remain backward compatible for Gemini/OpenAI-compatible tool calls.

## Current Refactor Pressure

`main.py` and `ui.py` are intentionally still stable public surfaces, but they should be split incrementally.

Recommended extraction order:

1. Tool dispatch from `main.py` into a runtime dispatcher module.
2. CLI and smoke startup from `main.py` into a small app entrypoint module.
3. Voice runtime from `main.py` into a dedicated voice service.
4. Settings screens from `ui.py` into UI settings modules.
5. Status widgets, log panel, and SFX controller from `ui.py` into smaller UI services.

Each extraction must preserve behavior and pass the acceptance gate before the next extraction starts.

## Security Boundaries

- Tool calls go through the central safety registry.
- Unknown tools are blocked by default.
- Risky actions require approval.
- Runtime traces, audit logs, sqlite state, OAuth tokens, smoke reports, and user config remain outside git.

## Provider Boundaries

- Gemini Live remains the voice-first core.
- OpenAI API and 9Router/OpenAI-compatible endpoints use cloud config fields.
- Local/Foundry endpoints use local config fields.
- ChatGPT Plus/Business OAuth is not a model API authentication path.
