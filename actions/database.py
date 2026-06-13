"""
Database query tools for JARVIS.

Provides safe SQLite query capabilities with read-only restrictions.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Allowlist of directories where database queries are permitted
ALLOWED_PATHS = [
    str(Path.home()),
    str(Path.cwd()),
]

# Commands blocked for safety
BLOCKED_KEYWORDS = [
    "DROP",
    "DELETE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "REINDEX",
    "VACUUM",
]


def _is_path_allowed(db_path: str) -> bool:
    """Check if the database path is in an allowed directory."""
    resolved = os.path.realpath(os.path.expanduser(db_path))
    for allowed in ALLOWED_PATHS:
        if resolved.startswith(os.path.realpath(allowed)):
            return True
    return False


def _is_read_only_query(sql: str) -> bool:
    """Check if the SQL query is read-only (no modifications)."""
    upper = sql.strip().upper()
    for kw in BLOCKED_KEYWORDS:
        if upper.startswith(kw):
            return False
    return True


def query_database(db_path: str, sql: str, params: tuple | None = None, limit: int = 100) -> dict:
    """
    Execute a read-only SQL query on a SQLite database.

    Args:
        db_path: Path to the SQLite database file.
        sql: SQL query string (SELECT only).
        params: Optional query parameters.
        limit: Maximum number of rows to return.

    Returns:
        Dict with keys: success, columns (list), rows (list), row_count, error.
    """
    if not _is_path_allowed(db_path):
        return {
            "success": False,
            "error": f"Database path not allowed: {db_path}. "
                     f"Allowed directories: {', '.join(ALLOWED_PATHS)}",
        }

    if not _is_read_only_query(sql):
        return {
            "success": False,
            "error": f"Only SELECT queries are allowed. Blocked keyword detected.",
        }

    if not os.path.isfile(db_path):
        return {
            "success": False,
            "error": f"Database file not found: {db_path}",
        }

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        rows = cursor.fetchmany(limit)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        result = {
            "success": True,
            "columns": columns,
            "rows": [dict(row) for row in rows],
            "row_count": len(rows),
        }
        conn.close()
        return result
    except sqlite3.Error as e:
        return {"success": False, "error": f"SQLite error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Query error: {str(e)}"}


def list_tables(db_path: str) -> dict:
    """List all tables in a SQLite database."""
    return query_database(
        db_path,
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
    )


def database_status() -> dict:
    """Check database tool availability."""
    return {
        "available": True,
        "engine": "sqlite3",
        "allowed_paths": ALLOWED_PATHS,
    }
