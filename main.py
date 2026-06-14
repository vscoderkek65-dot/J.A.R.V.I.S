#!/usr/bin/env python3
"""
JARVIS desktop — minimalist entry point.

All core logic lives in core/jarvis_live.py.
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.jarvis_live import JarvisLive, main as run_application


def main() -> int:
    try:
        return run_application()
    except KeyboardInterrupt:
        print("\n[main] Interrupted")
        return 0
    except Exception as exc:
        import logging

        logging.getLogger("main").error("Fatal error", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
