from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any

from actions.task_system import cancel_task, create_followup_task, list_tasks


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
    return folded.replace("ı", "i").replace("İ", "i")


def _cleanup_topic(text: str) -> str:
    value = str(text or "").strip()
    patterns = [
        r"\bhaber(leri)?\s+cikarsa\s+bildir\b",
        r"\bhaber(leri)?\s+çıkarsa\s+bildir\b",
        r"\bcikarsa\s+bildir\b",
        r"\bçıkarsa\s+bildir\b",
        r"\bbunu\s+takip\s+et\b",
        r"\btakip\s+et\b",
        r"\byarin\s+(bunu\s+)?kontrol\s+et\b",
        r"\byarın\s+(bunu\s+)?kontrol\s+et\b",
        r"\bkontrol\s+et\b",
        r"\bbana\b",
        r"\blutfen\b",
        r"\blütfen\b",
    ]
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" .,:;-")


def _last_research_query(trace_manager: Any | None) -> str:
    item = getattr(trace_manager, "last_research", None) or {}
    query = str(item.get("query") or "").strip()
    if query:
        return query
    summary = str(item.get("summary") or "").strip()
    return summary[:160].strip()


def _tomorrow_morning_iso() -> str:
    now = dt.datetime.now().astimezone()
    target = (now + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return target.isoformat(timespec="seconds")


def _interval_minutes(text: str) -> int:
    folded = _fold(text)
    match = re.search(r"(\d+)\s*(dakika|dk|saat|gun|gün)", folded)
    if not match:
        return 180
    value = int(match.group(1))
    unit = match.group(2)
    if unit in {"saat"}:
        return value * 60
    if unit in {"gun", "gün"}:
        return value * 1440
    return value


def handle_local_task_command(text: str, trace_manager: Any | None = None) -> str | None:
    raw = str(text or "").strip()
    folded = _fold(raw)
    if not raw:
        return None

    if any(marker in folded for marker in ("takipleri listele", "gorevleri listele", "görevleri listele", "aktif takipler")):
        return list_tasks("active", 30)

    cancel_match = re.search(r"(?:takibi|gorevi|görevi)\s+iptal\s+et\s*#?\s*(\d+)", folded)
    if cancel_match:
        return cancel_task(cancel_match.group(1))

    if "haber cikarsa bildir" in folded or "haberleri cikarsa bildir" in folded or "haber çıkarsa bildir" in raw.casefold() or "çıkarsa bildir" in raw.casefold():
        topic = _cleanup_topic(raw)
        if not topic:
            topic = _last_research_query(trace_manager)
        if not topic:
            return "Takip baslatilamadi: hangi haber/konu takip edilecek? Once bir konu soyle veya arastirma yaptir."
        if "haber" not in _fold(topic):
            query = f"{topic} haberleri son dakika"
        else:
            query = topic
        return create_followup_task(
            title=f"{topic} haber takibi",
            task_type="web_watch",
            query=query,
            schedule_kind="interval",
            interval_minutes=_interval_minutes(raw),
            baseline_now=True,
        )

    if "bunu takip et" in folded or (folded.endswith("takip et") and "takipleri" not in folded):
        topic = _cleanup_topic(raw)
        if not topic or topic.casefold() in {"bunu"}:
            topic = _last_research_query(trace_manager)
        if not topic:
            return "Takip baslatilamadi: takip edilecek acik konu yok ve son arastirma bulunamadi."
        return create_followup_task(
            title=f"{topic} takibi",
            task_type="web_watch",
            query=topic,
            schedule_kind="interval",
            interval_minutes=_interval_minutes(raw),
            baseline_now=True,
        )

    if "yarin" in folded and "kontrol et" in folded:
        topic = _cleanup_topic(raw)
        if not topic:
            topic = _last_research_query(trace_manager)
        if not topic:
            return "Tek seferlik kontrol olusturulamadi: neyi kontrol edecegimi soyle veya once arastirma yaptir."
        return create_followup_task(
            title=f"Yarin kontrol: {topic}",
            task_type="one_shot_check",
            query=topic,
            schedule_kind="once",
            run_at=_tomorrow_morning_iso(),
        )

    return None
