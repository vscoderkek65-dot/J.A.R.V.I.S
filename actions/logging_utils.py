from __future__ import annotations

import json
import re
from typing import Any

from actions.audit import sanitize


CONTENT_KEY_RE = re.compile(
    r"(text|content|value|message|body|file_content|prompt|clipboard)",
    re.IGNORECASE,
)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ...[truncated]"


def _redact_content_fields(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if CONTENT_KEY_RE.search(key_str):
                text = str(item or "")
                clean[key_str] = f"***REDACTED_CONTENT len={len(text)}***"
            else:
                clean[key_str] = _redact_content_fields(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_redact_content_fields(item) for item in value[:40]]
    return value


def safe_log_preview(value: Any, *, limit: int = 300, redact_content_keys: bool = False) -> str:
    safe_value = _redact_content_fields(value) if redact_content_keys else value
    safe_value = sanitize(safe_value, text_limit=limit)
    try:
        preview = json.dumps(safe_value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        preview = str(safe_value)
    return _shorten(preview, limit)
