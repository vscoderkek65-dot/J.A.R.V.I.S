from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Awaitable, Callable


ToolExecutor = Callable[[str, dict], Awaitable[str]]


@dataclass
class OpenAICompatibleConfig:
    base_url: str
    model: str
    api_key: str
    provider_name: str = "Ninerouter/OpenAI-compatible"
    field_prefix: str = "ninerouter"
    require_api_key: bool = True
    api_key_fallback: str = "none"

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.base_urls():
            missing.append(f"{self.field_prefix}_base_url")
        if not self.model.strip():
            missing.append(f"{self.field_prefix}_model")
        if self.require_api_key and not self.api_key.strip():
            missing.append(f"{self.field_prefix}_api_key")
        return missing

    def base_urls(self) -> list[str]:
        raw = str(self.base_url or "").strip()
        if not raw:
            return []
        urls = []
        for item in re.split(r"[\s,;]+", raw):
            value = item.strip()
            if value:
                urls.append(value.rstrip("/"))
        return urls

    def chat_url(self) -> str:
        urls = self.base_urls()
        base = urls[0] if urls else ""
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def chat_urls(self) -> list[str]:
        urls = []
        for base in self.base_urls():
            if base.endswith("/chat/completions"):
                urls.append(base)
            else:
                urls.append(base + "/chat/completions")
        return urls

    def clean_api_key(self) -> str:
        key = self.api_key.strip()
        if key.casefold().startswith("bearer "):
            key = key[7:].strip()
        return key or str(self.api_key_fallback or "none")


def _normalize_schema(value):
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key == "type" and isinstance(item, str):
                normalized[key] = item.lower()
            else:
                normalized[key] = _normalize_schema(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    return value


def convert_gemini_tools_to_openai(tool_declarations: list[dict]) -> list[dict]:
    tools = []
    for declaration in tool_declarations:
        name = declaration.get("name")
        if not name:
            continue
        parameters = declaration.get("parameters") or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": declaration.get("description", ""),
                    "parameters": _normalize_schema(parameters),
                },
            }
        )
    return tools


def _extract_message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _strip_html(value: str) -> str:
    from actions.html_safety import strip_html as _safe_strip

    return _safe_strip(value)


def _summarize_http_error(config: OpenAICompatibleConfig, base_url: str, status_code: int, body: str) -> str:
    from actions.html_safety import extract_title as _safe_extract_title
    title = _safe_extract_title(body or "")
    clean_body = _strip_html(body)[:360]
    host = urlparse(base_url.strip()).netloc or base_url.strip()
    provider_name = str(config.provider_name or "OpenAI-compatible")
    is_9router = "9router" in provider_name.casefold() or "9router" in host.casefold()

    if is_9router and (status_code == 530 or "Origin DNS error" in body):
        return (
            f"HTTP 530: endpoint origin'e ulasamiyor ({host}). "
            "Bu genelde 9Router/Cloudflare tunnel kapali, suresi dolmus veya URL yanlis demek. "
            "Birden fazla endpoint yazabilirsin: https://.../v1, http://localhost:20128/v1. "
            "9Router yerel calisiyorsa base URL olarak genelde http://localhost:20128/v1 kullanilir. "
            "9Router dashboard/servisini acip yeni URL'yi kontrol et."
        )
    if status_code == 530 or "Origin DNS error" in body:
        return (
            f"HTTP 530: {provider_name} endpoint origin'e ulasamiyor ({host}). "
            "Endpoint servisini baslat, URL'yi kontrol et veya farkli local/cloud endpoint dene."
        )
    if status_code in {401, 403}:
        folded_body = (body or "").casefold()
        if is_9router and ("authentication token has been invalidated" in folded_body or "try signing in again" in folded_body):
            return (
                f"HTTP {status_code}: 9Router istegi aldi ama upstream provider oturumu gecersiz. "
                "Logdaki '[codex/...]' kismi hatanin Codex baglantisindan geldigini gosteriyor. "
                "9Router dashboard'da Codex provider/account icin tekrar sign in yap veya tokeni yenile. "
                "JARVIS tarafindaki inbound key dogru olabilir."
            )
        if re.search(r"\[[a-z0-9_-]+/", body or "", re.IGNORECASE):
            detail = _strip_html(body)[:260]
            return (
                f"HTTP {status_code}: 9Router upstream provider hata verdi. "
                "9Router JARVIS istegini kabul etmis, fakat secilen model/provider kimlik dogrulamasi reddedilmis. "
                f"Sunucu detayi: {detail or 'detay yok'}"
            )
        detail = _strip_html(body)[:220]
        return (
            f"HTTP {status_code}: API key yetkisiz veya reddedildi. "
            f"{provider_name} icin endpoint key/token ayarini kontrol et. "
            f"Sunucu detayi: {detail or 'detay yok'}"
        )
    if status_code == 404:
        return (
            f"HTTP 404: endpoint bulunamadi. {provider_name} base URL /v1 ile bitmeli; JARVIS otomatik /chat/completions ekliyor. "
            f"Kullanilan host: {host}"
        )
    if status_code in {429, 500, 502, 503, 504}:
        return f"HTTP {status_code}: router veya upstream model gecici hata verdi. Kisa sure sonra tekrar dene veya modeli degistir."
    detail = title or clean_body
    return f"HTTP {status_code}: {detail or 'Bilinmeyen HTTP hatasi'}"


def _post_chat_completion_once(config: OpenAICompatibleConfig, chat_url: str, payload: dict) -> dict:
    import requests  # type: ignore
    key = config.clean_api_key()

    response = requests.post(
        chat_url,
        headers={
            "Authorization": f"Bearer {key}",
            "x-api-key": key,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://jarvis.local",
            "X-Title": "JARVIS Desktop",
        },
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(_summarize_http_error(config, chat_url, response.status_code, response.text))
    return response.json()


def _post_chat_completion(config: OpenAICompatibleConfig, payload: dict) -> dict:
    errors = []
    for chat_url in config.chat_urls():
        try:
            return _post_chat_completion_once(config, chat_url, payload)
        except Exception as exc:
            errors.append(f"{chat_url}: {exc}")
    raise RuntimeError("Tum endpointler basarisiz: " + " | ".join(errors))


async def chat_with_tools(
    config: OpenAICompatibleConfig,
    system_prompt: str,
    user_text: str,
    tool_declarations: list[dict],
    execute_tool: ToolExecutor,
    max_rounds: int = 6,
) -> str:
    missing = config.missing_fields()
    if missing:
        return f"{config.provider_name} ayarlari eksik: " + ", ".join(missing)

    tools = convert_gemini_tools_to_openai(tool_declarations)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    last_text = ""
    for _ in range(max(1, min(10, int(max_rounds or 6)))):
        payload = {
            "model": config.model.strip(),
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "stream": False,
        }
        try:
            data = await asyncio.to_thread(_post_chat_completion, config, payload)
        except Exception as exc:
            return f"{config.provider_name} baglantisi basarisiz: {type(exc).__name__}: {exc}"

        choices = data.get("choices") or []
        if not choices:
            return "Model yaniti bos geldi."
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        text = _extract_message_text(message)
        if text:
            last_text = text

        if not tool_calls:
            return text or last_text or "Model yaniti bos geldi."

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name = function.get("name", "")
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception:
                args = {}
            result = await execute_tool(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", name),
                    "name": name,
                    "content": str(result),
                }
            )

    return last_text or "Model araci kullandi ama son yanit uretemedi."
