from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "conversations.sqlite3"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_updated
                    ON conversations(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_message_conversation
                    ON conversation_messages(conversation_id, id);
                """
            )
            conn.commit()

    def create(self, title: str = "Yeni sohbet") -> dict:
        conversation_id = uuid.uuid4().hex
        now = _now()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title.strip() or "Yeni sohbet", now, now),
            )
            conn.commit()
        return self.get(conversation_id)

    def get(self, conversation_id: str) -> dict:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            return dict(row) if row else {}

    def list(self, limit: int = 50) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_message(self, conversation_id: str, role: str, content: str) -> dict:
        content = str(content or "").strip()
        if not content:
            return {}
        now = _now()
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO conversation_messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content[:12000], now),
            )
            first_user = conn.execute(
                "SELECT content FROM conversation_messages "
                "WHERE conversation_id = ? AND role = 'user' ORDER BY id LIMIT 1",
                (conversation_id,),
            ).fetchone()
            title = (first_user["content"][:52] if first_user else "Yeni sohbet").strip()
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title or "Yeni sohbet", now, conversation_id),
            )
            conn.commit()
            return {
                "id": int(cursor.lastrowid),
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": now,
            }

    def messages(self, conversation_id: str, limit: int = 40) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM conversation_messages
                    WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id
                """,
                (conversation_id, max(1, min(200, int(limit)))),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete(self, conversation_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()
            return cursor.rowcount > 0
