from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app_config import (
    load_app_config,
    normalize_agent_mode,
    normalize_local_provider,
    save_app_config,
)
from core.llm_client import OpenAICompatibleConfig, _extract_message_text, _post_chat_completion


@dataclass
class FoundryEndpoint:
    base_url: str
    model: str


_FOUNDRY_MANAGER: Any | None = None
_FOUNDRY_MODEL: Any | None = None
_FOUNDRY_ENDPOINT: FoundryEndpoint | None = None
_NET_CACHE: tuple[float, bool] = (0.0, False)


def _value(config: dict, key: str) -> str:
    return str(config.get(key, "") or "").strip()


def _bool_value(config: dict, key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "evet", "on"}


def _append_v1(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/v1") or value.endswith("/chat/completions"):
        return value
    return value + "/v1"


def cloud_agent_config(config: dict | None = None) -> OpenAICompatibleConfig:
    config = config or load_app_config()
    return OpenAICompatibleConfig(
        base_url=_value(config, "cloud_base_url") or _value(config, "ninerouter_base_url"),
        model=_value(config, "cloud_model") or _value(config, "ninerouter_model"),
        api_key=_value(config, "cloud_api_key") or _value(config, "ninerouter_api_key"),
        provider_name="Cloud/OpenAI-compatible",
        field_prefix="cloud",
        require_api_key=True,
    )


def local_agent_config(config: dict | None = None, *, start_foundry: bool = False) -> OpenAICompatibleConfig:
    config = config or load_app_config()
    provider = normalize_local_provider(config.get("local_provider", "foundry_local"))
    if provider == "openai_compatible":
        return OpenAICompatibleConfig(
            base_url=_value(config, "local_base_url"),
            model=_value(config, "local_model"),
            api_key=_value(config, "local_api_key"),
            provider_name="Local/OpenAI-compatible",
            field_prefix="local",
            require_api_key=False,
            api_key_fallback="none",
        )

    manual_foundry_url = _append_v1(_value(config, "local_base_url"))
    if manual_foundry_url:
        return OpenAICompatibleConfig(
            base_url=manual_foundry_url,
            model=_value(config, "local_model") or _value(config, "local_foundry_model_alias"),
            api_key=_value(config, "local_api_key") or "none",
            provider_name="Microsoft Foundry Local",
            field_prefix="local",
            require_api_key=False,
            api_key_fallback="none",
        )

    if start_foundry and _bool_value(config, "local_auto_start", True):
        endpoint = _ensure_foundry_endpoint(config)
        return OpenAICompatibleConfig(
            base_url=endpoint.base_url,
            model=endpoint.model,
            api_key=_value(config, "local_api_key") or "none",
            provider_name="Microsoft Foundry Local",
            field_prefix="local",
            require_api_key=False,
            api_key_fallback="none",
        )

    return OpenAICompatibleConfig(
        base_url=_append_v1(_value(config, "local_base_url")),
        model=_value(config, "local_model") or _value(config, "local_foundry_model_alias"),
        api_key=_value(config, "local_api_key") or "none",
        provider_name="Microsoft Foundry Local",
        field_prefix="local",
        require_api_key=False,
        api_key_fallback="none",
    )


def local_agent_config_ready(config: dict | None = None) -> bool:
    config = config or load_app_config()
    provider = normalize_local_provider(config.get("local_provider", "foundry_local"))
    if provider == "openai_compatible":
        return bool(_value(config, "local_base_url") and _value(config, "local_model"))
    if _value(config, "local_base_url") and (_value(config, "local_model") or _value(config, "local_foundry_model_alias")):
        return True
    return bool(_value(config, "local_foundry_model_alias") and _bool_value(config, "local_auto_start", True))


def _foundry_sdk_available() -> bool:
    try:
        import foundry_local_sdk  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def _ensure_foundry_endpoint(config: dict | None = None) -> FoundryEndpoint:
    global _FOUNDRY_ENDPOINT, _FOUNDRY_MANAGER, _FOUNDRY_MODEL
    config = config or load_app_config()
    alias = _value(config, "local_foundry_model_alias") or "qwen2.5-0.5b"
    if _FOUNDRY_ENDPOINT and _FOUNDRY_ENDPOINT.model:
        return _FOUNDRY_ENDPOINT

    try:
        from foundry_local_sdk import Configuration, FoundryLocalManager  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Microsoft Foundry Local SDK bulunamadi. Windows icin once "
            "`pip install foundry-local-sdk-winml` kur veya local_provider=openai_compatible ile "
            "manuel local_base_url/local_model gir."
        ) from exc

    config_obj = Configuration(app_name="jarvis_desktop")
    if hasattr(FoundryLocalManager, "initialize"):
        FoundryLocalManager.initialize(config_obj)
        manager = FoundryLocalManager.instance
    elif hasattr(FoundryLocalManager, "create"):
        manager = FoundryLocalManager.create(config_obj)
    else:
        manager = FoundryLocalManager(config_obj)

    if hasattr(manager, "download_and_register_eps"):
        manager.download_and_register_eps()

    catalog = getattr(manager, "catalog", None)
    if callable(catalog):
        catalog = catalog()
    if catalog is None:
        raise RuntimeError("Foundry Local katalogu alinamadi.")

    model = catalog.get_model(alias)
    if model is None:
        raise RuntimeError(f"Foundry Local modeli bulunamadi: {alias}")
    if hasattr(model, "download"):
        model.download(lambda _progress: None)
    if hasattr(model, "load"):
        model.load()
    if hasattr(manager, "start_web_service"):
        manager.start_web_service()

    urls = getattr(manager, "urls", [])
    if callable(urls):
        urls = urls()
    if not urls:
        raise RuntimeError("Foundry Local web service endpoint donmedi.")

    model_id = str(getattr(model, "id", "") or alias)
    endpoint = FoundryEndpoint(base_url=_append_v1(str(urls[0])), model=model_id)
    _FOUNDRY_MANAGER = manager
    _FOUNDRY_MODEL = model
    _FOUNDRY_ENDPOINT = endpoint
    return endpoint


def internet_available(timeout_seconds: float = 1.8, cache_seconds: float = 20.0) -> bool:
    global _NET_CACHE
    now = time.time()
    stamp, value = _NET_CACHE
    if now - stamp < cache_seconds:
        return value
    try:
        import requests  # type: ignore

        for url in ("https://www.gstatic.com/generate_204", "https://www.microsoft.com"):
            try:
                response = requests.get(url, timeout=timeout_seconds)
                if response.status_code < 500:
                    _NET_CACHE = (now, True)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    _NET_CACHE = (now, False)
    return False


def _endpoint_health(config: OpenAICompatibleConfig) -> str:
    base_urls = config.base_urls()
    if not base_urls:
        return "eksik"
    parsed = urlparse(base_urls[0])
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return "local"
    return "remote"


def local_ai_status() -> str:
    config = load_app_config()
    mode = normalize_agent_mode(config.get("agent_mode", "hybrid"))
    cloud = cloud_agent_config(config)
    local = local_agent_config(config, start_foundry=False)
    cloud_ready = not cloud.missing_fields()
    local_ready = local_agent_config_ready(config)
    provider = normalize_local_provider(config.get("local_provider", "foundry_local"))
    lines = [
        "Yerel AI durumu:",
        f"- Mod: {mode}",
        f"- Cloud: {'hazir' if cloud_ready else 'eksik'} ({_endpoint_health(cloud)})",
        f"- Local provider: {provider}",
        f"- Local: {'hazir' if local_ready else 'eksik'} ({_endpoint_health(local)})",
        f"- Foundry SDK: {'var' if _foundry_sdk_available() else 'yok'}",
        f"- Internet: {'var' if internet_available() else 'yok/offline'}",
    ]
    if provider == "foundry_local":
        lines.append(f"- Foundry model alias: {_value(config, 'local_foundry_model_alias') or 'qwen2.5-0.5b'}")
        if not _foundry_sdk_available():
            lines.append("- Not: Foundry otomatik mod icin `foundry-local-sdk-winml` kurulumu gerekir.")
    return "\n".join(lines)


def test_local_ai(prompt: str = "Merhaba, tek cumle cevap ver.") -> str:
    config = load_app_config()
    provider = normalize_local_provider(config.get("local_provider", "foundry_local"))
    try:
        llm_config = local_agent_config(config, start_foundry=True)
        missing = llm_config.missing_fields()
        if missing:
            return "Local AI ayarlari eksik: " + ", ".join(missing)
        data = _post_chat_completion(
            llm_config,
            {
                "model": llm_config.model.strip(),
                "messages": [{"role": "user", "content": prompt or "Merhaba"}],
                "temperature": 0.1,
                "stream": False,
            },
        )
        choices = data.get("choices") or []
        message = (choices[0].get("message") if choices else {}) or {}
        text = _extract_message_text(message)
        return f"Local AI test basarili ({provider}): {text or 'yanit alindi'}"
    except Exception as exc:
        return f"Local AI testi basarisiz ({provider}): {type(exc).__name__}: {exc}"


def set_agent_mode(mode: str) -> str:
    normalized = normalize_agent_mode(mode)
    save_app_config({"agent_mode": normalized})
    return f"JARVIS model modu guncellendi: {normalized}"
