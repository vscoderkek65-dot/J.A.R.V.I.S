"""
Kalıcı bellek — JSON dosyasına kaydedilir.
"""

import json
import re
import unicodedata
from pathlib import Path

from memory.memory_store import (
    delete_sqlite_memory,
    get_memory_store,
    list_memory as _list_sqlite_memory,
    memory_status as _sqlite_memory_status,
    remember_file_note as _remember_file_note,
    save_sqlite_memory,
    search_memory as _search_sqlite_memory,
)

BASE_DIR    = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "memory" / "memory.json"


def load_memory() -> dict:
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _json_kind_for_category(category: str) -> str:
    category = (category or "").strip()
    if category == "identity":
        return "profile"
    if category == "preferences":
        return "preference"
    if category == "projects":
        return "project_note"
    if category == "notes":
        return "project_note"
    return "profile"


def _index_json_update(data: dict):
    if not isinstance(data, dict):
        return
    for category, bucket in data.items():
        kind = _json_kind_for_category(str(category))
        if isinstance(bucket, dict):
            for key, value in bucket.items():
                content = _entry_value_text(value)
                title = f"{category}/{key}"
                save_sqlite_memory(
                    kind=kind,
                    title=title,
                    content=content,
                    source="json_memory",
                    source_id=f"{category}/{key}",
                    tags=f"json,{category}",
                    confidence=0.92,
                )
        else:
            save_sqlite_memory(
                kind=kind,
                title=str(category),
                content=str(bucket),
                source="json_memory",
                source_id=str(category),
                tags=f"json,{category}",
                confidence=0.92,
            )


def update_memory(data: dict):
    mem = load_memory()
    _deep_merge(mem, data)
    _write_memory(mem)
    _index_json_update(data)


def _write_memory(mem: dict):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, update: dict):
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _normalize_text(text: str) -> str:
    text = (text or "").strip().casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ı", "i")
    return " ".join(text.split())


def _entry_value_text(value) -> str:
    if isinstance(value, dict):
        base = value.get("value")
        if base is not None:
            return str(base)
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _tokenize_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [token for token in re.split(r"[^a-z0-9]+", normalized) if token]


def _entry_matches(needle: str, category: str, item_key: str, item_value) -> bool:
    haystacks = [
        _normalize_text(category),
        _normalize_text(item_key),
        _normalize_text(_entry_value_text(item_value)),
    ]
    if any(needle in hay for hay in haystacks):
        return True

    tokens = [tok for tok in _tokenize_text(needle) if len(tok) >= 3]
    if not tokens:
        return False

    entry_tokens: list[str] = []
    for hay in haystacks:
        entry_tokens.extend(_tokenize_text(hay))

    matched = 0
    for token in tokens:
        if any(token in entry_token or entry_token in token for entry_token in entry_tokens):
            matched += 1

    if len(tokens) == 1:
        return matched == 1
    return matched >= min(2, len(tokens))


def delete_memory(category: str = "", key: str = "", match_text: str = "") -> str:
    mem = load_memory()
    if not mem:
        sqlite_result = delete_sqlite_memory(match_text=match_text or key)
        if "bulamadim" not in sqlite_result.casefold():
            return sqlite_result
        return "Hafizada silinecek bir kayit yok."

    category = (category or "").strip()
    key = (key or "").strip()
    match_text = (match_text or "").strip()
    id_match = re.fullmatch(r"#?\s*(\d+)", match_text or key)
    if id_match:
        return delete_sqlite_memory(item_id=id_match.group(1))

    if category and key:
        bucket = mem.get(category)
        if isinstance(bucket, dict) and key in bucket:
            del bucket[key]
            if not bucket:
                mem.pop(category, None)
            _write_memory(mem)
            get_memory_store().delete_by_source("json_memory", f"{category}/{key}")
            return f"{category}/{key} hafizadan kaldirildi."
        return "Bu hafiza kaydini bulamadim."

    needle = _normalize_text(match_text or key)
    if not needle:
        return "Silmek icin category/key veya match_text gerekli."

    for cat, bucket in list(mem.items()):
        if not isinstance(bucket, dict):
            if _entry_matches(needle, cat, cat, bucket):
                del mem[cat]
                _write_memory(mem)
                get_memory_store().delete_by_source("json_memory", cat)
                return f"{cat} hafizadan kaldirildi."
            continue

        for item_key, item_value in list(bucket.items()):
            if _entry_matches(needle, cat, item_key, item_value):
                del bucket[item_key]
                if not bucket:
                    mem.pop(cat, None)
                _write_memory(mem)
                get_memory_store().delete_by_source("json_memory", f"{cat}/{item_key}")
                return f"{cat}/{item_key} hafizadan kaldirildi."

    sqlite_result = delete_sqlite_memory(match_text=match_text or key)
    if "bulamadim" not in sqlite_result.casefold():
        return sqlite_result
    return "Eslestigim bir hafiza kaydi bulamadim."


def format_memory_for_prompt(memory: dict) -> str:
    if not memory:
        return ""
    lines = ["[KULLANICI HAKKINDA BİLGİLER]"]
    for category, items in memory.items():
        if isinstance(items, dict):
            for key, val in items.items():
                if category == "whatsapp_contacts" and isinstance(val, dict):
                    display_name = val.get("display_name", key)
                    value = val.get("value", "")
                    aliases = val.get("aliases", [])
                    alias_str = ""
                    if isinstance(aliases, list) and aliases:
                        alias_str = f" aliases={', '.join(str(a) for a in aliases)}"
                    lines.append(f"  {category}/{display_name}: {value}{alias_str}")
                else:
                    value = val.get("value", val) if isinstance(val, dict) else val
                    lines.append(f"  {category}/{key}: {value}")
        else:
            lines.append(f"  {category}: {items}")
    return "\n".join(lines)


def search_memory(query: str, kind: str = "", limit: int = 8) -> str:
    return _search_sqlite_memory(query, kind, limit)


def list_memory(kind: str = "", limit: int = 20) -> str:
    return _list_sqlite_memory(kind, limit)


def memory_status() -> str:
    return _sqlite_memory_status(load_memory())


def remember_file_note(path: str, summary: str = "", tags: str = "") -> str:
    return _remember_file_note(path, summary, tags)
