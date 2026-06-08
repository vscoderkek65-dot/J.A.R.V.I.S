from __future__ import annotations

import datetime as dt
import hashlib
import os
import platform
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.trace import extract_research_details


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "memory" / "tasks.sqlite3"
TASK_STATUSES = {"pending", "running", "waiting_approval", "done", "failed", "cancelled"}
ACTIVE_STATUSES = {"pending", "running", "waiting_approval"}
TASK_TYPES = {"web_watch", "one_shot_check"}
SCHEDULE_KINDS = {"once", "interval"}
STARTUP_LINK_NAME = "JARVIS Takip Sistemi.lnk"
STARTUP_CMD_NAME = "JARVIS Takip Sistemi.cmd"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _iso(value: dt.datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _parse_datetime(value: str | dt.datetime | None) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = dt.datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def _row_to_dict(row: sqlite3.Row | dict | None) -> dict:
    if not row:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def _shorten(text: str, limit: int = 800) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0] + "..."


def _extract_short_answer(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.casefold().startswith("kisa cevap"):
            tail = line.split(":", 1)[1].strip() if ":" in line else ""
            if tail:
                return _shorten(tail, 700)
            if index + 1 < len(lines):
                return _shorten(lines[index + 1], 700)
    selected: list[str] = []
    for line in lines:
        folded = line.casefold()
        if folded.startswith(("kaynaklar:", "okunamayan kaynaklar:", "arama not")):
            break
        if folded.startswith(("arastirma:", "detaylar:")):
            continue
        selected.append(line)
        if len(" ".join(selected)) > 700:
            break
    return _shorten(" ".join(selected) or str(text or ""), 700)


def _result_hash(text: str) -> str:
    details = extract_research_details(text)
    sources = "|".join(details.get("sources") or [])
    short_answer = _extract_short_answer(text)
    payload = f"{sources}\n{short_answer}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_targets() -> tuple[Path, Path]:
    folder = _startup_folder()
    return folder / STARTUP_LINK_NAME, folder / STARTUP_CMD_NAME


@dataclass
class TaskRunResult:
    task_id: int
    title: str
    status: str
    summary: str
    notified: bool = False
    changed: bool = False
    error: str = ""

    def as_text(self) -> str:
        if self.error:
            return f"Gorev calistirilamadi ({self.task_id}): {self.error}"
        prefix = "Takip bildirimi uretildi" if self.notified else "Gorev calisti"
        return f"{prefix} ({self.task_id}) - {self.title}: {self.summary}"


class TaskStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
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
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    query TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    schedule_kind TEXT NOT NULL,
                    interval_minutes INTEGER DEFAULT 0,
                    run_at TEXT DEFAULT '',
                    next_run_at TEXT DEFAULT '',
                    last_result_hash TEXT DEFAULT '',
                    last_summary TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            columns = {
                "title": "TEXT NOT NULL DEFAULT ''",
                "task_type": "TEXT NOT NULL DEFAULT 'web_watch'",
                "query": "TEXT DEFAULT ''",
                "url": "TEXT DEFAULT ''",
                "schedule_kind": "TEXT NOT NULL DEFAULT 'interval'",
                "interval_minutes": "INTEGER DEFAULT 0",
                "run_at": "TEXT DEFAULT ''",
                "next_run_at": "TEXT DEFAULT ''",
                "last_result_hash": "TEXT DEFAULT ''",
                "last_summary": "TEXT DEFAULT ''",
                "status": "TEXT NOT NULL DEFAULT 'pending'",
                "error": "TEXT DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
            conn.commit()

    def create_task(
        self,
        *,
        title: str,
        task_type: str,
        query: str = "",
        url: str = "",
        schedule_kind: str,
        interval_minutes: int = 0,
        run_at: str = "",
        next_run_at: str = "",
        status: str = "pending",
    ) -> dict:
        if task_type not in TASK_TYPES:
            raise ValueError(f"Gecersiz gorev tipi: {task_type}")
        if schedule_kind not in SCHEDULE_KINDS:
            raise ValueError(f"Gecersiz zamanlama tipi: {schedule_kind}")
        if status not in TASK_STATUSES:
            raise ValueError(f"Gecersiz durum: {status}")
        now = _iso()
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    title, task_type, query, url, schedule_kind, interval_minutes,
                    run_at, next_run_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    task_type,
                    query,
                    url,
                    schedule_kind,
                    int(interval_minutes or 0),
                    run_at,
                    next_run_at,
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()
            return self.get_task(int(cursor.lastrowid))

    def get_task(self, task_id: int) -> dict:
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            return _row_to_dict(row)

    def list_tasks(self, status_filter: str = "active", limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), 100))
        status_filter = str(status_filter or "active").casefold()
        params: list[object] = []
        where = ""
        if status_filter == "active":
            marks = ",".join("?" for _ in ACTIVE_STATUSES)
            where = f"WHERE status IN ({marks})"
            params.extend(sorted(ACTIVE_STATUSES))
        elif status_filter in TASK_STATUSES:
            where = "WHERE status = ?"
            params.append(status_filter)
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY COALESCE(next_run_at, run_at, updated_at) ASC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def due_tasks(self, now: dt.datetime | None = None, limit: int = 10) -> list[dict]:
        cutoff = _iso(now or _now())
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pending'
                  AND next_run_at != ''
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (cutoff, max(1, int(limit or 10))),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def update_task(self, task_id: int, **fields: object) -> dict:
        allowed = {
            "title",
            "task_type",
            "query",
            "url",
            "schedule_kind",
            "interval_minutes",
            "run_at",
            "next_run_at",
            "last_result_hash",
            "last_summary",
            "status",
            "error",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        clean["updated_at"] = _iso()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        with self._lock, self._connection() as conn:
            conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                (*clean.values(), int(task_id)),
            )
            conn.commit()
        return self.get_task(task_id)

    def mark_running(self, task_id: int) -> dict:
        return self.update_task(task_id, status="running", error="")

    def finish_task(
        self,
        task: dict,
        *,
        summary: str,
        result_hash: str,
        status: str,
        error: str = "",
        next_run_at: str = "",
    ) -> dict:
        return self.update_task(
            int(task["id"]),
            status=status,
            last_summary=summary,
            last_result_hash=result_hash,
            error=error,
            next_run_at=next_run_at,
        )

    def cancel_task(self, task_id: int) -> dict:
        task = self.get_task(task_id)
        if not task:
            return {}
        return self.update_task(int(task_id), status="cancelled", error="")


_store: TaskStore | None = None


def set_task_store(store: TaskStore | None) -> None:
    global _store
    _store = store


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


def format_task(task: dict) -> str:
    target = task.get("query") or task.get("url") or "-"
    next_run = task.get("next_run_at") or task.get("run_at") or "-"
    interval = f", {task.get('interval_minutes')} dk" if task.get("schedule_kind") == "interval" else ""
    return f"#{task.get('id')} [{task.get('status')}] {task.get('title')} ({task.get('task_type')}{interval}) -> {target} | sonraki: {next_run}"


def _save_task_memory(title: str, summary: str, source_id: str) -> None:
    try:
        from memory.memory_store import save_task_summary

        save_task_summary(title, summary, source_id)
    except Exception:
        pass


def create_followup_task(
    title: str = "",
    task_type: str = "web_watch",
    query: str = "",
    url: str = "",
    schedule_kind: str = "interval",
    interval_minutes: int = 180,
    run_at: str = "",
    baseline_now: bool = True,
) -> str:
    query = str(query or "").strip()
    url = str(url or "").strip()
    title = str(title or "").strip() or query or url or "JARVIS takip gorevi"
    task_type = str(task_type or "web_watch").strip() or "web_watch"
    schedule_kind = str(schedule_kind or "interval").strip() or "interval"
    if not query and not url:
        return "Gorev olusturulamadi: takip edilecek konu veya URL yok."
    if task_type not in TASK_TYPES:
        return f"Gorev olusturulamadi: gecersiz gorev tipi '{task_type}'."
    if schedule_kind not in SCHEDULE_KINDS:
        return f"Gorev olusturulamadi: gecersiz zamanlama '{schedule_kind}'."

    if schedule_kind == "once":
        parsed = _parse_datetime(run_at)
        if not parsed:
            return "Gorev olusturulamadi: tek seferlik gorev icin ISO run_at gerekli."
        interval_minutes = 0
        run_at_value = _iso(parsed)
        next_run = run_at_value
    else:
        interval_minutes = max(15, min(int(interval_minutes or 180), 10080))
        run_at_value = ""
        first_time = _now() if baseline_now else _now() + dt.timedelta(minutes=interval_minutes)
        next_run = _iso(first_time)

    task = get_task_store().create_task(
        title=title,
        task_type=task_type,
        query=query,
        url=url,
        schedule_kind=schedule_kind,
        interval_minutes=interval_minutes,
        run_at=run_at_value,
        next_run_at=next_run,
    )
    _save_task_memory(str(task.get("title") or title), "Gorev olusturuldu: " + format_task(task), f"task:{task.get('id')}:created")
    if schedule_kind == "interval":
        return (
            f"Takip gorevi olusturuldu: {format_task(task)}\n"
            "Ilk calisma baseline kaydeder; sonraki farkta bildirim uretir."
        )
    return f"Tek seferlik kontrol gorevi olusturuldu: {format_task(task)}"


def list_tasks(status_filter: str = "active", limit: int = 20) -> str:
    tasks = get_task_store().list_tasks(status_filter, limit)
    if not tasks:
        return "Listelenecek takip/gorev yok."
    return "Takip ve gorevler:\n" + "\n".join(format_task(task) for task in tasks)


def cancel_task(task_id: int | str) -> str:
    try:
        tid = int(task_id)
    except Exception:
        return "Gorev iptal edilemedi: gecerli bir gorev ID ver."
    task = get_task_store().cancel_task(tid)
    if not task:
        return f"Gorev bulunamadi: #{tid}"
    result = f"Gorev iptal edildi: {format_task(task)}"
    _save_task_memory(str(task.get("title") or f"Gorev #{tid}"), result, f"task:{tid}:cancelled")
    return result


def _next_run_for(task: dict) -> str:
    if task.get("schedule_kind") != "interval":
        return ""
    minutes = max(15, int(task.get("interval_minutes") or 180))
    return _iso(_now() + dt.timedelta(minutes=minutes))


def _default_research_func(query: str, max_pages: int = 5, open_browser: bool = False) -> str:
    from actions.web_research import research_web

    return research_web(query, max_pages=max_pages, open_browser=open_browser)


def execute_task_once(
    task: dict,
    *,
    notifier: Callable[[str, str], None] | None = None,
    research_func: Callable[..., str] | None = None,
    store: TaskStore | None = None,
) -> TaskRunResult:
    store = store or get_task_store()
    task = _row_to_dict(task)
    task_id = int(task.get("id") or 0)
    title = str(task.get("title") or f"Gorev #{task_id}")
    query = str(task.get("query") or task.get("url") or "").strip()
    if not task_id or not query:
        return TaskRunResult(task_id, title, "failed", "", error="Gecersiz gorev kaydi.")

    try:
        func = research_func or _default_research_func
        output = func(query, max_pages=5, open_browser=False)
        summary = _extract_short_answer(output)
        new_hash = _result_hash(output)
        old_hash = str(task.get("last_result_hash") or "")
        is_once = task.get("schedule_kind") == "once"

        if not old_hash:
            status = "done" if is_once else "pending"
            store.finish_task(
                task,
                summary=summary,
                result_hash=new_hash,
                status=status,
                next_run_at="" if is_once else _next_run_for(task),
            )
            result = TaskRunResult(task_id, title, status, f"Baseline kaydedildi. {summary}", notified=False, changed=False)
            if is_once:
                _save_task_memory(title, result.as_text(), f"task:{task_id}:{_iso()}")
            return result

        changed = new_hash != old_hash
        notified = False
        if changed and notifier:
            notifier(title, summary)
            notified = True

        status = "done" if is_once else "pending"
        store.finish_task(
            task,
            summary=summary,
            result_hash=new_hash,
            status=status,
            next_run_at="" if is_once else _next_run_for(task),
        )
        if changed:
            result = TaskRunResult(task_id, title, status, summary, notified=notified, changed=True)
            if notified or is_once:
                _save_task_memory(title, result.as_text(), f"task:{task_id}:{_iso()}")
            return result
        return TaskRunResult(task_id, title, status, f"Degisiklik yok. {summary}", notified=False, changed=False)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        store.finish_task(task, summary=str(task.get("last_summary") or ""), result_hash=str(task.get("last_result_hash") or ""), status="failed", error=error)
        return TaskRunResult(task_id, title, "failed", "", error=error)


def run_task_now(task_id: int | str) -> str:
    try:
        tid = int(task_id)
    except Exception:
        return "Gorev calistirilamadi: gecerli bir gorev ID ver."
    store = get_task_store()
    task = store.get_task(tid)
    if not task:
        return f"Gorev bulunamadi: #{tid}"
    if task.get("status") == "cancelled":
        return f"Gorev iptal edilmis: #{tid}"
    store.mark_running(tid)
    result = execute_task_once(task, store=store)
    _save_task_memory(str(task.get("title") or f"Gorev #{tid}"), result.as_text(), f"task:{tid}:run_now")
    return result.as_text()


def notify_windows(title: str, body: str) -> str:
    if platform.system() != "Windows":
        return "Windows toast atlandi: Windows disi platform."
    try:
        from winotify import Notification

        toast = Notification(app_id="JARVIS", title=str(title or "JARVIS"), msg=_shorten(body, 420))
        toast.show()
        return "Windows toast gonderildi."
    except Exception as exc:
        return f"Windows toast gonderilemedi; UI/TTS fallback kullanildi: {type(exc).__name__}: {exc}"


class TaskScheduler:
    def __init__(
        self,
        *,
        store: TaskStore | None = None,
        notify_callback: Callable[[str, str], None] | None = None,
        interval_seconds: int = 60,
        research_func: Callable[..., str] | None = None,
    ):
        self.store = store or get_task_store()
        self.notify_callback = notify_callback
        self.interval_seconds = max(5, int(interval_seconds or 60))
        self.research_func = research_func
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="JarvisTaskScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_due_once()
            self._stop.wait(self.interval_seconds)

    def run_due_once(self) -> list[TaskRunResult]:
        results: list[TaskRunResult] = []
        for task in self.store.due_tasks():
            task_id = int(task.get("id") or 0)
            if not task_id:
                continue
            current = self.store.mark_running(task_id)
            result = execute_task_once(
                current,
                notifier=self.notify_callback,
                research_func=self.research_func,
                store=self.store,
            )
            results.append(result)
        return results


def startup_tracking_status() -> str:
    link, cmd = _startup_targets()
    enabled = link.exists() or cmd.exists()
    return (
        f"Windows baslangic takibi: {'acik' if enabled else 'kapali'}\n"
        f"Kisayol: {link if link.exists() else cmd if cmd.exists() else link}"
    )


def enable_startup_tracking() -> str:
    if platform.system() != "Windows":
        return "Windows baslangic takibi sadece Windows'ta desteklenir."
    link, cmd = _startup_targets()
    link.parent.mkdir(parents=True, exist_ok=True)
    run_script = BASE_DIR / "run_windows.ps1"
    if not run_script.exists():
        return f"Baslangic takibi acilamadi: {run_script} bulunamadi."
    try:
        import win32com.client  # type: ignore[import-not-found]

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(link))
        shortcut.Targetpath = "powershell.exe"
        shortcut.Arguments = f'-ExecutionPolicy Bypass -File "{run_script}"'
        shortcut.WorkingDirectory = str(BASE_DIR)
        shortcut.IconLocation = "powershell.exe,0"
        shortcut.save()
        if cmd.exists():
            cmd.unlink()
        return f"Windows baslangic takibi acildi: {link}"
    except Exception:
        cmd.write_text(
            f'@echo off\r\ncd /d "{BASE_DIR}"\r\npowershell.exe -ExecutionPolicy Bypass -File "{run_script}"\r\n',
            encoding="utf-8",
        )
        return f"Windows baslangic takibi acildi: {cmd}"


def disable_startup_tracking() -> str:
    link, cmd = _startup_targets()
    removed: list[str] = []
    for path in (link, cmd):
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except Exception as exc:
            return f"Baslangic takibi kapatilamadi: {type(exc).__name__}: {exc}"
    if not removed:
        return "Windows baslangic takibi zaten kapali."
    return "Windows baslangic takibi kapatildi: " + ", ".join(removed)
