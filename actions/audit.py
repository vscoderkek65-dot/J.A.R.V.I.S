from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_DIR = BASE_DIR / "memory" / "audit"
SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|bearer|parola|sifre|şifre)", re.IGNORECASE)
SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]{8,}|xox[baprs]-[a-z0-9-]+|ghp_[a-zA-Z0-9_]+|gho_[a-zA-Z0-9_]+|[a-f0-9]{64})"
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _shorten(value: str, limit: int = 1200) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ...[truncated]"


def sanitize(value: Any, text_limit: int = 1200) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            clean[key_str] = "***REDACTED***" if SENSITIVE_KEY_RE.search(key_str) else sanitize(item, text_limit)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize(item, text_limit) for item in value[:40]]
    if isinstance(value, str):
        redacted = SENSITIVE_VALUE_RE.sub("***REDACTED***", value)
        return _shorten(redacted, text_limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _shorten(str(value), text_limit)


class AuditLogger:
    def __init__(self, log_dir: str | Path = DEFAULT_AUDIT_DIR):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _path(self) -> Path:
        stamp = dt.datetime.now().strftime("%Y-%m")
        return self.log_dir / f"security-audit-{stamp}.jsonl"

    def log(
        self,
        event_type: str,
        *,
        run_id: str = "",
        action_id: str = "",
        tool_name: str = "",
        risk_class: str = "",
        args: dict | None = None,
        summary: str = "",
        result: str = "",
        status: str = "",
    ) -> dict:
        event = {
            "timestamp": _now_iso(),
            "event_type": str(event_type or ""),
            "run_id": str(run_id or ""),
            "action_id": str(action_id or ""),
            "tool_name": str(tool_name or ""),
            "risk_class": str(risk_class or ""),
            "args": sanitize(args or {}, text_limit=1600),
            "summary": sanitize(summary or "", text_limit=900),
            "result_preview": sanitize(result or "", text_limit=900),
            "status": str(status or event_type or ""),
        }
        with self._path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def read_recent(self, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit or 10), 100))
        files = sorted(self.log_dir.glob("security-audit-*.jsonl"), reverse=True)
        events: list[dict] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
                if len(events) >= limit:
                    return events
        return events


_logger: AuditLogger | None = None


def set_audit_logger(logger: AuditLogger | None) -> None:
    global _logger
    _logger = logger


def get_audit_logger() -> AuditLogger:
    global _logger
    if _logger is None:
        _logger = AuditLogger()
    return _logger


def audit_status(limit: int = 10, logger: AuditLogger | None = None) -> str:
    logger = logger or get_audit_logger()
    events = logger.read_recent(limit)
    if not events:
        return "Audit kaydi yok."
    lines = ["Son audit olaylari:"]
    for event in events:
        lines.append(
            f"- {event.get('timestamp', '-')} [{event.get('event_type', '-')}] "
            f"{event.get('risk_class', '-')}/{event.get('tool_name', '-')} "
            f"{event.get('action_id') or '-'}: {event.get('summary') or event.get('status') or '-'}"
        )
    return "\n".join(lines)
