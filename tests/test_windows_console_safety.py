from __future__ import annotations

from pathlib import Path
import unittest


class WindowsConsoleSafetyTests(unittest.TestCase):
    def test_live_runtime_print_calls_do_not_contain_non_bmp_emoji(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "core" / "jarvis_live.py").read_text(
            encoding="utf-8"
        )
        print_lines = [line for line in source.splitlines() if "print(" in line]
        for line in print_lines:
            self.assertFalse(any(ord(char) > 0xFFFF for char in line), line)


if __name__ == "__main__":
    unittest.main()
