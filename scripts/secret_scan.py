"""Fail CI when tracked source files contain likely live credentials."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\btvly-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~-]{24,}", re.IGNORECASE),
)
SKIP_PREFIXES = ("tests/",)
SKIP_FILES = {"config/api_keys.example.json"}


def tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [item for item in output.decode("utf-8").split("\0") if item]


def main() -> int:
    findings: list[str] = []
    for relative in tracked_files():
        normalized = relative.replace("\\", "/")
        if normalized in SKIP_FILES or normalized.startswith(SKIP_PREFIXES):
            continue
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append(f"{normalized}:{line_number}")

    if findings:
        print("Potential live credentials found in tracked files:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
