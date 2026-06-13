"""JARVIS structured logger — replaces bare print() and except: pass patterns."""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOG: logging.Logger | None = None
_LOG_DIR: Path | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_log_dir() -> Path:
    global _LOG_DIR
    if _LOG_DIR is None:
        _LOG_DIR = Path.home() / ".jarvis" / "logs"
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def get_logger(name: str = "jarvis") -> logging.Logger:
    """Return a module-level logger with console + file handlers."""
    global _LOG
    if _LOG is not None:
        return _LOG

    log_dir = get_log_dir()
    log_path = log_dir / f"jarvis-{datetime.now().strftime('%Y%m')}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # File handler (rotated monthly)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Console handler (WARN+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(ch)

    _LOG = logger
    return logger


def log_exception(logger: logging.Logger, context: str = "", exc_info: bool = True) -> None:
    """Log an exception with context and return structured error dict."""
    exc = sys.exc_info()[1]
    tb = "".join(traceback.format_exception(*sys.exc_info())) if exc_info else ""
    logger.error("EXCEPTION | %s | %s: %s\n%s", context, type(exc).__name__, exc, tb)


def safe_call(logger: logging.Logger, fn: Any, default: Any = None, context: str = "") -> Any:
    """Call a function safely, logging any exception and returning default on failure."""
    try:
        return fn()
    except Exception:
        log_exception(logger, context or fn.__name__)
        return default


class LogContext:
    """Context manager that logs entry/exit of a block."""

    def __init__(self, logger: logging.Logger, label: str, level: int = logging.DEBUG):
        self.logger = logger
        self.label = label
        self.level = level

    def __enter__(self):
        self.logger.log(self.level, "[ENTRY] %s", self.label)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.logger.error("[EXIT (ERROR)] %s | %s: %s", self.label, exc_type.__name__, exc_val)
        else:
            self.logger.log(self.level, "[EXIT] %s", self.label)
        return False