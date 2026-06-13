"""
Version information for J.A.R.V.I.S.

Usage:
    from core.version import __version__, get_version
    print(__version__)
"""

import os
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def get_version() -> str:
    """Read the current version from the VERSION file."""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return "0.0.0"


def get_version_tuple() -> tuple:
    """Return version as a tuple of ints, e.g. (1, 0, 0)."""
    parts = get_version().split(".")
    try:
        return tuple(int(p) for p in parts[:3])
    except ValueError:
        return (0, 0, 0)


__version__ = get_version()
__version_info__ = get_version_tuple()
