from __future__ import annotations

import re
import unicodedata

from memory.memory_manager import delete_memory, list_memory, memory_status, search_memory
from memory.memory_store import delete_sqlite_memory


_last_memory_results: list[int] = []


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
    return folded.replace("ı", "i")


def _remember_results(result: str) -> None:
    global _last_memory_results
    ids = [int(value) for value in re.findall(r"#(\d+)", result or "")]
    _last_memory_results = ids[:12]


def _extract_search_query(raw: str) -> str:
    value = raw.strip()
    patterns = [
        r"hafizad[ae]\s+ara",
        r"hafızad[ae]\s+ara",
        r"hafizamda\s+ara",
        r"hafızamda\s+ara",
        r"hafizada\s+ne\s+var",
        r"hafızada\s+ne\s+var",
        r"gecen\s+konusmada",
        r"geçen\s+konuşmada",
        r"gecmiste",
        r"geçmişte",
    ]
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" ?:;,.")


def _extract_forget_query(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"#?\s*(\d+)\s*(numarali|numaralı)?\s*(hafiza|hafıza)?\s*(kaydini|kaydını)?\s*(sil|unut)", " ", value, flags=re.IGNORECASE)
    patterns = [
        r"bunu\s+unut",
        r"sun[uı]\s+unut",
        r"şun[uı]\s+unut",
        r"hafizandan\s+sil",
        r"hafızandan\s+sil",
        r"hafizadan\s+sil",
        r"hafızadan\s+sil",
        r"unut",
        r"sil",
    ]
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" ?:;,.")


def handle_local_memory_command(text: str) -> str | None:
    raw = str(text or "").strip()
    folded = _fold(raw)
    if not raw:
        return None

    if any(marker in folded for marker in ("hafiza durumu", "hafiza status", "memory status")):
        result = memory_status()
        _remember_results(result)
        return result

    if any(marker in folded for marker in ("hafiza kayitlarini listele", "hafizayi listele", "hafiza listele", "ne hatirliyorsun", "neleri hatirliyorsun")):
        result = list_memory("", 20)
        _remember_results(result)
        return result

    if any(marker in folded for marker in ("hafizada ara", "hafizamda ara", "gecen konusmada", "gecmiste")):
        query = _extract_search_query(raw)
        if not query:
            return "Hafizada aramak icin bir konu yaz."
        result = search_memory(query, "", 8)
        _remember_results(result)
        return result

    if "unut" in folded or "hafizandan sil" in folded or "hafizadan sil" in folded:
        id_match = re.search(r"#?\s*(\d+)", folded)
        if id_match:
            result = delete_sqlite_memory(item_id=id_match.group(1))
            _remember_results("")
            return result
        if any(marker in folded for marker in ("bunu unut", "sunu unut", "şunu unut")):
            if len(_last_memory_results) == 1:
                result = delete_sqlite_memory(item_id=_last_memory_results[0])
                _remember_results("")
                return result
            if len(_last_memory_results) > 1:
                return "Birden fazla son hafiza kaydi var. Silmek icin ID soyle: " + ", ".join(f"#{item_id}" for item_id in _last_memory_results[:8])
            return "Unutulacak son hafiza kaydi yok. Once hafizada ara veya silinecek konuyu soyle."
        query = _extract_forget_query(raw)
        if not query:
            return "Neyi unutacagimi net soyle veya hafiza kaydi ID'si ver."
        result = delete_memory(match_text=query)
        _remember_results(result)
        return result

    return None
