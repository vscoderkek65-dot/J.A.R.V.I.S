from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "api_keys.json"


DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "voice": "Charon",
    "youtube_api_key": "",
    "youtube_channel_handle": "",
    "tavily_api_key": "",
    "agent_mode": "hybrid",
    "agent_provider": "hybrid",
    "cloud_base_url": "",
    "cloud_model": "",
    "cloud_api_key": "",
    "ninerouter_base_url": "",
    "ninerouter_model": "",
    "ninerouter_api_key": "",
    "local_provider": "foundry_local",
    "local_base_url": "",
    "local_model": "",
    "local_api_key": "",
    "local_foundry_model_alias": "qwen2.5-0.5b",
    "local_auto_start": True,
    "calendar_provider": "outlook",
    "outlook_client_id": "",
    "outlook_tenant_id": "common",
    "google_oauth_client_id": "",
    "google_oauth_client_secret": "",
    "email_provider": "",
    "plugins_enabled_default": False,
    "plugin_dirs": ["plugins"],
    "voice_input_mode": "ptt_wake",
    "push_to_talk_hotkey": "ctrl+space",
    "wake_word_enabled": False,
    "wake_engine": "porcupine",
    "wake_word": "jarvis",
    "porcupine_access_key": "",
    "vosk_model_path": "",
    "wake_capture_seconds": 8,
}


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "evet", "on"}


def normalize_agent_mode(value: str = "") -> str:
    mode = str(value or "").strip().casefold()
    if mode in {"cloud", "ninerouter", "openai", "openai_compatible"}:
        return "cloud"
    if mode in {"local", "offline", "foundry", "foundry_local"}:
        return "local"
    return "hybrid"


def normalize_local_provider(value: str = "") -> str:
    provider = str(value or "").strip().casefold()
    if provider in {"manual", "openai", "openai-compatible", "openai_compatible", "custom"}:
        return "openai_compatible"
    return "foundry_local"


def normalize_voice_mode(value: str = "") -> str:
    mode = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "ptt": "ptt_only",
        "push_to_talk": "ptt_only",
        "push_to_talk_only": "ptt_only",
        "ptt_only": "ptt_only",
        "wake": "wake_only",
        "wake_word": "wake_only",
        "wake_only": "wake_only",
        "always": "live_always",
        "live": "live_always",
        "live_always": "live_always",
        "ptt_wake": "ptt_wake",
        "wake_ptt": "ptt_wake",
        "ptt+wake": "ptt_wake",
    }
    return aliases.get(mode, "ptt_wake")


def normalize_app_config(config: dict, raw: dict | None = None) -> dict:
    raw = raw or {}
    config["agent_mode"] = normalize_agent_mode(config.get("agent_mode", "hybrid"))
    config["local_provider"] = normalize_local_provider(config.get("local_provider", "foundry_local"))
    config["local_auto_start"] = _truthy(config.get("local_auto_start", True))
    config["voice_input_mode"] = normalize_voice_mode(config.get("voice_input_mode", "ptt_wake"))
    config["wake_word_enabled"] = _truthy(config.get("wake_word_enabled", False))
    config["wake_engine"] = str(config.get("wake_engine", "porcupine") or "porcupine").strip().casefold()
    if config["wake_engine"] not in {"porcupine", "vosk"}:
        config["wake_engine"] = "porcupine"
    try:
        config["wake_capture_seconds"] = max(2, min(30, int(config.get("wake_capture_seconds", 8) or 8)))
    except Exception:
        config["wake_capture_seconds"] = 8

    if not str(config.get("cloud_base_url", "") or "").strip():
        config["cloud_base_url"] = str(config.get("ninerouter_base_url", "") or "")
    if not str(config.get("cloud_model", "") or "").strip():
        config["cloud_model"] = str(config.get("ninerouter_model", "") or "")
    if not str(config.get("cloud_api_key", "") or "").strip():
        config["cloud_api_key"] = str(config.get("ninerouter_api_key", "") or "")

    if not str(config.get("ninerouter_base_url", "") or "").strip():
        config["ninerouter_base_url"] = str(config.get("cloud_base_url", "") or "")
    if not str(config.get("ninerouter_model", "") or "").strip():
        config["ninerouter_model"] = str(config.get("cloud_model", "") or "")
    if not str(config.get("ninerouter_api_key", "") or "").strip():
        config["ninerouter_api_key"] = str(config.get("cloud_api_key", "") or "")

    if "agent_mode" in raw:
        mode = config["agent_mode"]
        config["agent_provider"] = "ninerouter" if mode == "cloud" else "hybrid"
    elif not str(config.get("agent_provider", "") or "").strip():
        config["agent_provider"] = "hybrid"
    return config


def load_app_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    raw = {}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            config.update(raw)
    except Exception:
        pass
    return normalize_app_config(config, raw if isinstance(raw, dict) else {})


def save_app_config(updates: dict) -> dict:
    config = load_app_config()
    for key, value in (updates or {}).items():
        if value is None:
            continue
        config[key] = value
    config = normalize_app_config(config, updates or {})
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    return config


def get_app_config_value(key: str, default=None):
    return load_app_config().get(key, default)


def has_gemini_api_key() -> bool:
    value = str(get_app_config_value("gemini_api_key", "") or "").strip()
    return bool(value)


def has_text_agent_config() -> bool:
    config = load_app_config()
    if has_cloud_agent_config(config):
        return True
    return has_local_agent_config(config)


def has_cloud_agent_config(config: dict | None = None) -> bool:
    config = config or load_app_config()
    return all(
        str(config.get(key, "") or "").strip()
        for key in ("cloud_base_url", "cloud_model", "cloud_api_key")
    )


def has_local_agent_config(config: dict | None = None) -> bool:
    config = config or load_app_config()
    provider = normalize_local_provider(config.get("local_provider", "foundry_local"))
    if provider == "openai_compatible":
        return all(str(config.get(key, "") or "").strip() for key in ("local_base_url", "local_model"))
    return bool(str(config.get("local_foundry_model_alias", "") or "").strip() and config.get("local_auto_start", True))
