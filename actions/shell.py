"""
Safe terminal helper.

This tool is intentionally narrow. The approval layer decides whether a shell
request may be attempted; this module adds a second guard and only runs a small
set of read-only commands without using subprocess shell execution.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent.parent
MAX_OUTPUT = 1200

READ_ONLY_EXECUTABLES = {
    "git",
    "where",
    "where.exe",
    "whoami",
    "hostname",
    "ipconfig",
    "ping",
    "nslookup",
    "tasklist",
    "systeminfo",
    "python",
    "python.exe",
    "py",
}

READ_ONLY_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "remote",
    "rev-parse",
    "show",
    "status",
}

BLOCKED_TOKENS = {
    "&&",
    "||",
    ";",
    "|",
    ">",
    ">>",
    "<",
    "`",
    "$(",
}


def _workspace_path(value: str = ".") -> Path:
    raw = str(value or ".").strip().strip('"')
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    resolved = path.resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ValueError("Path workspace disinda.")
    return resolved


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"Komut ayrıştırılamadı: {exc}") from exc


def _has_blocked_token(command: str, parts: Iterable[str]) -> bool:
    folded = command.casefold()
    if any(token in folded for token in BLOCKED_TOKENS):
        return True
    mutating = (
        "rm",
        "mv",
        "cp",
        "chmod",
        "chown",
        "sudo",
        "del",
        "erase",
        "rmdir",
        "rd",
        "move",
        "copy",
        "remove-item",
        "set-content",
        "add-content",
        "new-item",
        "invoke-expression",
        "iex",
        "format",
        "shutdown",
        "restart-computer",
    )
    return any(str(part).casefold() in mutating for part in parts)


def _shorten(output: str) -> str:
    value = str(output or "").strip()
    if not value:
        return "Komut başarıyla çalıştı (çıktı yok)."
    if len(value) > MAX_OUTPUT:
        return value[:MAX_OUTPUT].rsplit(" ", 1)[0] + "\n... (çıktı kısaltıldı)"
    return value


def _list_directory(parts: list[str]) -> str:
    path = _workspace_path(parts[1] if len(parts) > 1 else ".")
    if not path.exists():
        return f"Bulunamadı: {path}"
    if path.is_file():
        return f"{path.name}\t{path.stat().st_size} bytes"
    rows = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))[:120]:
        kind = "<DIR>" if item.is_dir() else "     "
        size = "" if item.is_dir() else str(item.stat().st_size)
        rows.append(f"{kind}\t{size}\t{item.name}")
    return "\n".join(rows) or "Klasör boş."


def _read_file(parts: list[str]) -> str:
    if len(parts) < 2:
        return "Okunacak dosya belirtilmedi."
    path = _workspace_path(parts[1])
    if not path.exists() or not path.is_file():
        return f"Dosya bulunamadı: {path}"
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return "Binary dosya shell_run ile okunmaz; read_text_file aracını kullan."
    text = data.decode("utf-8", errors="replace")
    return _shorten(text)


def _echo(parts: list[str]) -> str:
    return " ".join(parts[1:]).strip()


def _where(parts: list[str]) -> str:
    if len(parts) < 2:
        return "Aranacak executable belirtilmedi."
    found = shutil.which(parts[1])
    return found or f"Bulunamadı: {parts[1]}"


def _run_read_only_executable(parts: list[str], timeout: int) -> str:
    executable = parts[0].casefold()
    args = parts[:]
    if executable == "where":
        args[0] = "where.exe"
    if executable == "hostname" and len(args) == 1:
        return socket.gethostname()
    if executable == "git":
        if len(args) < 2 or args[1].casefold() not in READ_ONLY_GIT_SUBCOMMANDS:
            return "Güvenlik: shell_run git için yalnızca read-only alt komutlara izin verir."
    if executable in {"python", "python.exe", "py"}:
        allowed = len(args) == 2 and args[1] in {"--version", "-V"}
        if not allowed:
            return "Güvenlik: shell_run Python için yalnızca sürüm sorgusuna izin verir."

    result = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=max(1, min(int(timeout or 30), 60)),
        shell=False,
    )
    return _shorten((result.stdout or "") + (result.stderr or ""))


def shell_run(command: str, timeout: int = 30) -> str:
    if not command or not str(command).strip():
        return "Komut belirtilmedi."

    try:
        parts = _split_command(str(command).strip())
    except ValueError as exc:
        return f"Güvenlik: {exc}"
    if not parts:
        return "Komut belirtilmedi."
    if _has_blocked_token(str(command), parts):
        return "Güvenlik: shell_run sadece salt-okuma allowlist komutlarını çalıştırır."

    name = parts[0].casefold()
    try:
        if name in {"dir", "ls"}:
            return _list_directory(parts)
        if name in {"type", "cat"}:
            return _read_file(parts)
        if name == "echo":
            return _echo(parts)
        if name in {"where", "where.exe"}:
            return _where(parts)
        if name in READ_ONLY_EXECUTABLES:
            return _run_read_only_executable(parts, timeout)
        return (
            "Güvenlik: shell_run bu komutu çalıştırmaz. "
            "Dosya işlemleri için özel dosya araçlarını, sistem bilgisi için sys_info aracını kullan."
        )
    except subprocess.TimeoutExpired:
        return f"Komut zaman aşımına uğradı ({timeout}s)."
    except Exception as exc:
        return f"Hata: {type(exc).__name__}: {exc}"
