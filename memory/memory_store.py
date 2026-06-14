from __future__ import annotations

import datetime as dt
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "memory" / "memory.sqlite3"
VALID_KINDS = {
    "profile",
    "preference",
    "conversation_summary",
    "decision",
    "project_note",
    "file_note",
    "task_summary",
}
SENSITIVE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|parola|sifre|şifre|bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]{12,})"
)
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){10,}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
LONG_SECRET_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _iso(value: dt.datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def normalize_text(text: str) -> str:
    value = str(text or "").strip().casefold()
    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.split())


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 2]


def contains_sensitive_data(text: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    if SENSITIVE_RE.search(value) or EMAIL_RE.search(value) or PHONE_RE.search(value) or CARD_RE.search(value):
        return True
    long_hits = [hit for hit in LONG_SECRET_RE.findall(value) if not hit.casefold().startswith(("http", "www"))]
    return bool(long_hits)


def _shorten(text: str, limit: int = 900) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0] + "..."


def _row_to_dict(row: sqlite3.Row | dict | None) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def _tags_to_text(tags: str | list[str] | tuple[str, ...] | None) -> str:
    if isinstance(tags, str):
        return ",".join(token for token in [item.strip() for item in tags.split(",")] if token)
    if isinstance(tags, (list, tuple)):
        return ",".join(str(item).strip() for item in tags if str(item).strip())
    return ""


class MemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    source_id TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
                USING fts5(title, content, tags)
                """
            )
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
            columns = {
                "kind": "TEXT NOT NULL DEFAULT 'project_note'",
                "title": "TEXT NOT NULL DEFAULT ''",
                "content": "TEXT NOT NULL DEFAULT ''",
                "source": "TEXT DEFAULT ''",
                "source_id": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT ''",
                "confidence": "REAL DEFAULT 1.0",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
                "last_accessed_at": "TEXT DEFAULT ''",
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE memory_items ADD COLUMN {column} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory_items(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_items(source, source_id)")
            conn.commit()

    def _sync_fts(self, conn: sqlite3.Connection, item_id: int, title: str, content: str, tags: str) -> None:
        conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (item_id,))
        conn.execute(
            "INSERT INTO memory_items_fts(rowid, title, content, tags) VALUES (?, ?, ?, ?)",
            (item_id, normalize_text(title), normalize_text(content), normalize_text(tags)),
        )

    def upsert_item(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        source: str = "",
        source_id: str = "",
        tags: str | list[str] | tuple[str, ...] | None = "",
        confidence: float = 1.0,
    ) -> dict:
        kind = kind if kind in VALID_KINDS else "project_note"
        title = _shorten(title or kind.replace("_", " ").title(), 180)
        content = _shorten(content or title, 2400)
        source = str(source or "").strip()
        source_id = str(source_id or "").strip()
        tags_text = _tags_to_text(tags)
        now = _iso()
        with self._connection() as conn:
            existing = None
            if source and source_id:
                existing = conn.execute(
                    "SELECT * FROM memory_items WHERE source = ? AND source_id = ? ORDER BY id DESC LIMIT 1",
                    (source, source_id),
                ).fetchone()
            if existing:
                item_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE memory_items
                    SET kind = ?, title = ?, content = ?, source = ?, source_id = ?,
                        tags = ?, confidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (kind, title, content, source, source_id, tags_text, float(confidence), now, item_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO memory_items (
                        kind, title, content, source, source_id, tags, confidence, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (kind, title, content, source, source_id, tags_text, float(confidence), now, now),
                )
                item_id = int(cursor.lastrowid)
            self._sync_fts(conn, item_id, title, content, tags_text)
            conn.commit()
            return self.get_item(item_id)

    def get_item(self, item_id: int | str) -> dict:
        try:
            iid = int(item_id)
        except Exception:
            return {}
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (iid,)).fetchone()
            return _row_to_dict(row)

    def delete_item(self, item_id: int | str) -> bool:
        try:
            iid = int(item_id)
        except Exception:
            return False
        with self._connection() as conn:
            cur = conn.execute("DELETE FROM memory_items WHERE id = ?", (iid,))
            conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (iid,))
            conn.commit()
            return cur.rowcount > 0

    def delete_by_source(self, source: str, source_id: str) -> int:
        source = str(source or "").strip()
        source_id = str(source_id or "").strip()
        if not source or not source_id:
            return 0
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id FROM memory_items WHERE source = ? AND source_id = ?",
                (source, source_id),
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (int(row["id"]),))
            cur = conn.execute("DELETE FROM memory_items WHERE source = ? AND source_id = ?", (source, source_id))
            conn.commit()
            return int(cur.rowcount or 0)

    def delete_matches(self, query: str, kind: str = "") -> list[dict]:
        matches = self.search(query, kind=kind, limit=12)
        strong = [item for item in matches if float(item.get("score", 0) or 0) >= 3.0]
        candidates = strong or matches
        if len(candidates) == 1:
            item = candidates[0]
            if self.delete_item(item["id"]):
                return [item]
        return []

    def list_items(self, kind: str = "", limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), 100))
        kind = str(kind or "").strip()
        params: list[Any] = []
        where = ""
        if kind:
            where = "WHERE kind = ?"
            params.append(kind)
        with self._connection() as conn:
            if kind:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_items
                    WHERE kind = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (*params, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_items
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def search(self, query: str, kind: str = "", limit: int = 8) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        limit = max(1, min(int(limit or 8), 40))
        kind = str(kind or "").strip()
        match_query = " OR ".join(tokens[:12])
        params: list[Any] = [match_query]
        where = ""
        if kind:
            where = "AND m.kind = ?"
            params.append(kind)
        params.append(limit * 3)
        with self._connection() as conn:
            try:
                if kind:
                    rows = conn.execute(
                        """
                        SELECT m.*, bm25(memory_items_fts) AS rank
                        FROM memory_items_fts
                        JOIN memory_items m ON m.id = memory_items_fts.rowid
                        WHERE memory_items_fts MATCH ? AND m.kind = ?
                        ORDER BY rank ASC
                        LIMIT ?
                        """,
                        tuple(params),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT m.*, bm25(memory_items_fts) AS rank
                        FROM memory_items_fts
                        JOIN memory_items m ON m.id = memory_items_fts.rowid
                        WHERE memory_items_fts MATCH ?
                        ORDER BY rank ASC
                        LIMIT ?
                        """,
                        tuple(params),
                    ).fetchall()
            except sqlite3.Error:
                search_tokens = tokens[:6]
                like_params: list[Any] = []
                for token in [*search_tokens, *["__jarvis_no_match__"] * (6 - len(search_tokens))]:
                    like_params.extend([f"%{token}%", f"%{token}%", f"%{token}%"])
                if kind:
                    rows = conn.execute(
                        """
                        SELECT * FROM memory_items
                        WHERE (
                            (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                        ) AND kind = ?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (*like_params, kind, limit * 3),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM memory_items
                        WHERE (
                            (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                            OR (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                        )
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (*like_params, limit * 3),
                    ).fetchall()
            results = []
            for row in rows:
                item = _row_to_dict(row)
                haystack = normalize_text(" ".join(str(item.get(field) or "") for field in ("title", "content", "tags")))
                token_hits = sum(1 for token in tokens if token in haystack)
                tag_hits = sum(1 for token in tokens if token in normalize_text(str(item.get("tags") or "")))
                score = token_hits + (tag_hits * 1.5) + float(item.get("confidence") or 0)
                item["score"] = round(score, 3)
                results.append(item)
            results.sort(key=lambda item: (-float(item.get("score", 0) or 0), str(item.get("updated_at") or "")), reverse=False)
            selected = results[:limit]
            if selected:
                now = _iso()
                for item in selected:
                    conn.execute("UPDATE memory_items SET last_accessed_at = ? WHERE id = ?", (now, int(item["id"])))
                conn.commit()
            return selected

    def status(self) -> dict:
        with self._connection() as conn:
            counts = {
                row["kind"]: int(row["count"])
                for row in conn.execute("SELECT kind, COUNT(*) AS count FROM memory_items GROUP BY kind").fetchall()
            }
            total = int(conn.execute("SELECT COUNT(*) AS count FROM memory_items").fetchone()["count"])
            recent = [
                _row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM memory_items ORDER BY updated_at DESC, id DESC LIMIT 5"
                ).fetchall()
            ]
            return {"total": total, "counts": counts, "recent": recent}


_store: MemoryStore | None = None


def set_memory_store(store: MemoryStore | None) -> None:
    global _store
    _store = store


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def format_memory_item(item: dict) -> str:
    tags = f" tags={item.get('tags')}" if item.get("tags") else ""
    return (
        f"#{item.get('id')} [{item.get('kind')}] {item.get('title')} "
        f"({item.get('source') or 'manual'}:{item.get('source_id') or '-'}){tags}\n"
        f"  {_shorten(str(item.get('content') or ''), 260)}"
    )


def save_sqlite_memory(
    kind: str,
    title: str,
    content: str,
    source: str = "",
    source_id: str = "",
    tags: str | list[str] | tuple[str, ...] | None = "",
    confidence: float = 1.0,
) -> dict:
    if contains_sensitive_data(f"{title}\n{content}\n{tags}"):
        return {"blocked": True, "reason": "sensitive_data"}
    return get_memory_store().upsert_item(
        kind=kind,
        title=title,
        content=content,
        source=source,
        source_id=source_id,
        tags=tags,
        confidence=confidence,
    )


def search_memory(query: str, kind: str = "", limit: int = 8) -> str:
    items = get_memory_store().search(query, kind, limit)
    if not items:
        return "Hafizada eslesen kayit bulunamadi."
    return "Hafiza arama sonuclari:\n" + "\n".join(format_memory_item(item) for item in items)


def list_memory(kind: str = "", limit: int = 20) -> str:
    items = get_memory_store().list_items(kind, limit)
    if not items:
        return "Listelenecek hafiza kaydi yok."
    return "Hafiza kayitlari:\n" + "\n".join(format_memory_item(item) for item in items)


def memory_status(json_memory: dict | None = None) -> str:
    data = get_memory_store().status()
    json_memory = json_memory or {}
    json_counts = {}
    for key, value in json_memory.items():
        json_counts[key] = len(value) if isinstance(value, dict) else 1
    lines = [
        "Hafiza durumu:",
        f"- SQLite kayitlari: {data['total']}",
        "- Turler: " + (", ".join(f"{k}={v}" for k, v in sorted(data["counts"].items())) or "-"),
        "- JSON profil: " + (", ".join(f"{k}={v}" for k, v in sorted(json_counts.items())) or "-"),
    ]
    if data["recent"]:
        lines.append("Son kayitlar:")
        lines.extend(format_memory_item(item) for item in data["recent"])
    return "\n".join(lines)


def remember_file_note(path: str, summary: str = "", tags: str = "") -> str:
    path_value = str(path or "").strip()
    if not path_value:
        return "Dosya notu kaydedilemedi: path gerekli."
    summary_value = _shorten(summary or f"Dosya/proje notu: {path_value}", 1200)
    item = save_sqlite_memory(
        "file_note",
        title=Path(path_value).name or path_value,
        content=summary_value,
        source="file_note",
        source_id=path_value,
        tags=tags or "file,project",
        confidence=0.85,
    )
    if item.get("blocked"):
        return "Dosya notu kaydedilmedi: hassas bilgiye benziyor."
    return "Dosya notu hafizaya kaydedildi:\n" + format_memory_item(item)


def format_relevant_memories_for_prompt(query: str, limit: int = 6) -> str:
    items = get_memory_store().search(query, limit=limit)
    if not items:
        return ""
    lines = ["[ILGILI HAFIZA KAYITLARI]"]
    for item in items[:limit]:
        lines.append(f"- #{item.get('id')} [{item.get('kind')}] {item.get('title')}: {_shorten(str(item.get('content') or ''), 320)}")
    return "\n".join(lines)


def infer_memory_from_text(text: str, source_id: str = "") -> dict:
    raw = str(text or "").strip()
    folded = normalize_text(raw)
    if not raw or contains_sensitive_data(raw):
        return {"saved": False, "reason": "empty_or_sensitive"}

    preference_markers = (
        "bundan sonra",
        "tercihim",
        "tercih ederim",
        "ben genelde",
        "cevaplarini",
        "cevapların",
        "kisa cevap",
        "kısa cevap",
    )
    decision_markers = (
        "bu projede kararimiz",
        "bu projede kararımız",
        "kararimiz",
        "kararımız",
        "bundan boyle bu projede",
        "bu projede",
    )
    kind = ""
    tags = ""
    if any(normalize_text(marker) in folded for marker in decision_markers):
        kind = "decision"
        tags = "decision,project"
    elif any(normalize_text(marker) in folded for marker in preference_markers):
        kind = "preference"
        tags = "preference"
    else:
        return {"saved": False, "reason": "no_marker"}

    title = _shorten(raw, 90)
    item = save_sqlite_memory(
        kind,
        title=title,
        content=raw,
        source="auto_learn",
        source_id=source_id or f"auto:{hash(normalize_text(raw))}",
        tags=tags,
        confidence=0.78,
    )
    if item.get("blocked"):
        return {"saved": False, "reason": "sensitive"}
    return {"saved": True, "item": item}


def save_conversation_summary(user_text: str, assistant_text: str, run_id: str = "") -> dict:
    user_text = _shorten(user_text, 700)
    assistant_text = _shorten(assistant_text, 900)
    if not user_text or not assistant_text:
        return {"saved": False}
    content = f"Kullanici: {user_text}\nJARVIS: {assistant_text}"
    if contains_sensitive_data(content):
        return {"saved": False, "reason": "sensitive"}
    return save_sqlite_memory(
        "conversation_summary",
        title=_shorten(user_text, 90),
        content=content,
        source="trace",
        source_id=run_id or f"conversation:{hash(normalize_text(content))}",
        tags="conversation,summary",
        confidence=0.62,
    )


def save_task_summary(title: str, summary: str, source_id: str = "") -> dict:
    content = _shorten(summary, 1200)
    if not title or not content or contains_sensitive_data(content):
        return {"saved": False}
    return save_sqlite_memory(
        "task_summary",
        title=_shorten(title, 100),
        content=content,
        source="task",
        source_id=source_id,
        tags="task,followup",
        confidence=0.72,
    )


def delete_sqlite_memory(match_text: str = "", kind: str = "", item_id: int | str = "") -> str:
    store = get_memory_store()
    if item_id:
        item = store.get_item(item_id)
        if not item:
            return f"Hafiza kaydi bulunamadi: #{item_id}"
        if store.delete_item(item_id):
            return f"Hafiza kaydi silindi: #{item_id} {item.get('title')}"
        return f"Hafiza kaydi silinemedi: #{item_id}"
    matches = store.search(match_text, kind=kind, limit=12)
    strong = [item for item in matches if float(item.get("score", 0) or 0) >= 3.0]
    candidates = strong or matches
    if not candidates:
        return "Eslestigim bir SQLite hafiza kaydi bulamadim."
    if len(candidates) == 1:
        item = candidates[0]
        store.delete_item(item["id"])
        return f"Hafiza kaydi silindi: #{item.get('id')} {item.get('title')}"
    lines = ["Birden fazla hafiza kaydi eslesti. Silmek icin ID belirt:"]
    lines.extend(format_memory_item(item) for item in candidates[:8])
    return "\n".join(lines)
