from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import datetime as _dt
import json
from pathlib import Path
import re
import time
import uuid
from typing import Any, Callable


DebugSink = Callable[[str, str], None]


_SENSITIVE_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|bearer)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _shorten(value: str, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ...[truncated]"


def _sanitize(value: Any, text_limit: int = 1200) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            clean[key_str] = "***REDACTED***" if _SENSITIVE_RE.search(key_str) else _sanitize(item, text_limit)
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, text_limit) for item in value[:40]]
    if isinstance(value, str):
        return _shorten(value, text_limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _shorten(str(value), text_limit)


def extract_research_details(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    sources: list[str] = []
    notes: list[str] = []
    rejected: list[str] = []
    unreadable: list[str] = []
    current_section = ""

    for line in lines:
        folded = line.casefold()
        if folded.startswith("kaynaklar:"):
            current_section = "sources"
            continue
        if folded.startswith("okunamayan kaynaklar:"):
            current_section = "unreadable"
            continue
        if folded.startswith("arama not"):
            current_section = "notes"
            continue
        if folded.startswith(("kisa cevap:", "detaylar:", "arastirma:")):
            current_section = ""
            continue

        if "reddedilen" in folded or "reddedildi" in folded:
            rejected.append(line)
        if current_section == "unreadable":
            unreadable.append(line)
        if current_section == "notes" or "denenen saglayicilar" in folded or "arama kaynagi:" in folded:
            notes.append(line)

        urls = _URL_RE.findall(line)
        if urls:
            sources.extend(url.rstrip(".,;") for url in urls)

    seen: set[str] = set()
    clean_sources = []
    for url in sources:
        if url not in seen:
            seen.add(url)
            clean_sources.append(url)

    return {
        "sources": clean_sources[:12],
        "notes": notes[:12],
        "rejected": rejected[:12],
        "unreadable": unreadable[:12],
    }


@dataclass
class TraceManager:
    log_dir: Path | str
    debug_sink: DebugSink | None = None
    max_recent: int = 60
    current_run_id: str = ""
    last_error: dict[str, Any] | None = None
    last_research: dict[str, Any] | None = None
    recent_events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=60))

    def __post_init__(self) -> None:
        self.log_dir = Path(self.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.recent_events = deque(maxlen=max(10, int(self.max_recent or 60)))

    def set_debug_sink(self, debug_sink: DebugSink | None) -> None:
        self.debug_sink = debug_sink

    def _path(self) -> Path:
        stamp = _dt.datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{stamp}.jsonl"

    def _emit_debug(self, message: str, level: str = "INFO") -> None:
        if not self.debug_sink:
            return
        try:
            self.debug_sink(message, level)
        except Exception:
            pass

    def _write(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("timestamp", _now_iso())
        event = _sanitize(event, text_limit=5000)
        self.recent_events.append(event)
        with self._path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def start_run(self, user_text: str, source: str = "text") -> str:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"run-{stamp}-{uuid.uuid4().hex[:6]}"
        self.current_run_id = run_id
        self._write(
            {
                "event": "run_start",
                "run_id": run_id,
                "source": source,
                "input": _shorten(user_text, 1800),
            }
        )
        self._emit_debug(f"{run_id} basladi ({source}): {_shorten(user_text, 120)}", "INFO")
        return run_id

    def ensure_run(self, user_text: str = "", source: str = "runtime") -> str:
        if self.current_run_id:
            return self.current_run_id
        return self.start_run(user_text or "runtime tool call", source=source)

    def set_current_run(self, run_id: str) -> None:
        self.current_run_id = str(run_id or "")

    def log_event(self, run_id: str, event: str, data: dict[str, Any] | None = None, level: str = "INFO") -> None:
        payload = {
            "event": event,
            "run_id": run_id or self.current_run_id,
            "data": data or {},
        }
        self._write(payload)
        if event in {"error", "tool_call"}:
            self._emit_debug(f"{payload['run_id']} {event}: {_shorten(str(data or {}), 160)}", level)

    def log_error(self, run_id: str, where: str, error: str, data: dict[str, Any] | None = None) -> None:
        self.last_error = {
            "run_id": run_id or self.current_run_id,
            "where": where,
            "error": _shorten(error, 1800),
            "data": _sanitize(data or {}),
            "timestamp": _now_iso(),
        }
        self._write({"event": "error", **self.last_error})
        self._emit_debug(f"{where}: {_shorten(error, 180)}", "ERROR")

    def log_tool(
        self,
        run_id: str,
        tool_name: str,
        specialist: str,
        args: dict[str, Any] | None,
        output: str,
        status: str,
        evaluation: str,
        elapsed_ms: int,
        error: str = "",
    ) -> None:
        details = extract_research_details(output)
        event = {
            "event": "tool_call",
            "run_id": run_id or self.ensure_run(f"tool: {tool_name}", source="runtime"),
            "tool_name": tool_name,
            "specialist": specialist,
            "input": args or {},
            "output": _shorten(output, 4200),
            "status": status,
            "evaluation": evaluation,
            "duration_ms": elapsed_ms,
            "error": _shorten(error, 1800) if error else "",
            "source_urls": details["sources"],
            "provider_notes": details["notes"],
            "rejected_sources": details["rejected"],
            "unreadable_sources": details["unreadable"],
        }
        self._write(event)
        if error or status in {"failed", "needs_followup"}:
            self.last_error = {
                "run_id": event["run_id"],
                "where": tool_name,
                "error": error or evaluation,
                "timestamp": _now_iso(),
            }
        if tool_name in {"research_web", "answer_research_question", "tavily_search", "browser_research", "browser_read_url", "local_command"}:
            self.record_research_from_output(event["run_id"], str((args or {}).get("query") or (args or {}).get("text") or ""), output)
        level = "ERROR" if status == "failed" else "WARN" if status in {"needs_followup", "waiting_approval"} else "INFO"
        self._emit_debug(
            f"{event['run_id']} {specialist}.{tool_name} -> {status} ({elapsed_ms} ms)",
            level,
        )

    def record_research_from_output(self, run_id: str, query: str, output: str) -> None:
        if not output or not any(marker in output.casefold() for marker in ("kaynaklar:", "arama not", "okunamayan kaynak", "kisa cevap:")):
            return
        details = extract_research_details(output)
        summary = _shorten(output, 1800)
        self.last_research = {
            "run_id": run_id or self.current_run_id,
            "query": _shorten(query, 500),
            "summary": summary,
            "sources": details["sources"],
            "provider_notes": details["notes"],
            "rejected_sources": details["rejected"],
            "unreadable_sources": details["unreadable"],
            "timestamp": _now_iso(),
        }
        self._write({"event": "research_summary", **self.last_research})
        note_count = len(details["notes"])
        rejected_count = len(details["rejected"])
        source_count = len(details["sources"])
        self._emit_debug(
            f"{self.last_research['run_id']} research: {source_count} kaynak, {rejected_count} red, {note_count} not",
            "INFO" if source_count else "WARN",
        )
        if details["notes"]:
            self._emit_debug(f"Saglayicilar: {_shorten(details['notes'][0], 180)}", "INFO")
        if details["rejected"]:
            self._emit_debug(f"Reddedilen: {_shorten(details['rejected'][0], 180)}", "WARN")

    def explain_last_research(self) -> str:
        if not self.last_research:
            return "Son arastirma kaydi yok. Once bir konuda arastirma yapmami iste."
        item = self.last_research
        lines = [
            "Son arastirma aciklamasi:",
            f"- Run ID: {item.get('run_id', '-')}",
            f"- Sorgu: {item.get('query') or 'kaydedilmedi'}",
        ]
        sources = item.get("sources") or []
        if sources:
            lines.append(f"- Kabul edilen kaynak sayisi: {len(sources)}")
            for index, url in enumerate(sources[:5], start=1):
                lines.append(f"  [{index}] {url}")
        else:
            lines.append("- Kabul edilen kaynak yok; bulunan sonuc metinleri alakasiz veya okunamaz gorundu.")
        rejected = item.get("rejected_sources") or []
        if rejected:
            lines.append("- Reddedilen/alakasiz kaynak nedenleri:")
            lines.extend(f"  - {_shorten(reason, 220)}" for reason in rejected[:5])
        unreadable = item.get("unreadable_sources") or []
        if unreadable:
            lines.append("- Okunamayan kaynaklar:")
            lines.extend(f"  - {_shorten(reason, 220)}" for reason in unreadable[:5])
        notes = item.get("provider_notes") or []
        if notes:
            lines.append("- Saglayici notlari:")
            lines.extend(f"  - {_shorten(note, 220)}" for note in notes[:5])
        if self.last_error:
            lines.append(f"- Son hata: {self.last_error.get('where')}: {self.last_error.get('error')}")
        return "\n".join(lines)

    def debug_snapshot(self) -> str:
        lines = ["Trace durumu:"]
        lines.append(f"- Aktif run: {self.current_run_id or 'yok'}")
        if self.last_error:
            lines.append(f"- Son hata: {self.last_error.get('where')}: {self.last_error.get('error')}")
        if self.last_research:
            lines.append(
                "- Son arastirma: "
                f"{self.last_research.get('query') or '-'} | "
                f"{len(self.last_research.get('sources') or [])} kaynak | "
                f"{len(self.last_research.get('rejected_sources') or [])} red"
            )
            notes = self.last_research.get("provider_notes") or []
            if notes:
                lines.append(f"- Son saglayici notu: {_shorten(notes[0], 240)}")
            rejected = self.last_research.get("rejected_sources") or []
            if rejected:
                lines.append(f"- Son red nedeni: {_shorten(rejected[0], 240)}")
        recent = list(self.recent_events)[-8:]
        if recent:
            lines.append("- Son islemler:")
            for event in recent:
                lines.append(
                    f"  - {event.get('event')} "
                    f"{event.get('tool_name') or event.get('where') or ''} "
                    f"{event.get('status') or ''}".strip()
                )
        return "\n".join(lines)

    def artifact_path(self, run_id: str, kind: str, suffix: str) -> Path:
        clean_kind = re.sub(r"[^a-z0-9_-]+", "_", (kind or "artifact").casefold()).strip("_") or "artifact"
        clean_suffix = suffix if suffix.startswith(".") else "." + suffix
        folder = self.log_dir / "artifacts" / (run_id or self.current_run_id or "manual")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{clean_kind}-{int(time.time() * 1000)}{clean_suffix}"
