from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import actions.clipboard as clipboard  # noqa: E402
import actions.desktop as desktop  # noqa: E402
from actions.files import summarize_text_file  # noqa: E402


class DesktopClipboardFilesTests(unittest.TestCase):
    def test_send_hotkey_safe_normalizes_aliases_and_blocks_unknown(self) -> None:
        calls: list[tuple[str, tuple[str, ...] | str]] = []
        old_pyautogui = sys.modules.get("pyautogui")
        sys.modules["pyautogui"] = types.SimpleNamespace(
            hotkey=lambda *parts: calls.append(("hotkey", tuple(parts))),
            press=lambda key: calls.append(("press", key)),
        )
        try:
            result = desktop.send_hotkey_safe("Control + S", delay_seconds=0)
            blocked = desktop.send_hotkey_safe("ctrl+alt+delete", delay_seconds=0)
        finally:
            if old_pyautogui is None:
                sys.modules.pop("pyautogui", None)
            else:
                sys.modules["pyautogui"] = old_pyautogui

        self.assertIn("Kisayol gonderildi: ctrl+s", result)
        self.assertEqual(calls, [("hotkey", ("ctrl", "s"))])
        self.assertIn("guvenli listede degil", blocked)

    def test_summarize_text_file_reports_preview_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text(
                "# Baslik\n\n"
                "def hello():\n"
                "    return 'merhaba'\n\n"
                "class Worker:\n"
                "    pass\n",
                encoding="utf-8",
            )

            result = summarize_text_file(str(path))

        self.assertIn("Dosya ozeti:", result)
        self.assertIn("Baslik/yapi ipuclari", result)
        self.assertIn("def hello", result)
        self.assertIn("class Worker", result)

    def test_summarize_clipboard_uses_clipboard_text(self) -> None:
        old_reader = clipboard._read_clipboard_text
        clipboard._read_clipboard_text = lambda: (True, "Bir iki uc\nDort bes alti")
        try:
            result = clipboard.summarize_clipboard()
        finally:
            clipboard._read_clipboard_text = old_reader

        self.assertIn("Pano ozeti", result)
        self.assertIn("6 kelime", result)

    def test_get_selected_text_restores_previous_clipboard(self) -> None:
        class FakeClipboard:
            value = "onceki pano"

            @classmethod
            def paste(cls):
                return cls.value

            @classmethod
            def copy(cls, value):
                cls.value = value

        def hotkey(*parts):
            if parts == ("ctrl", "c"):
                FakeClipboard.value = "secili metin"

        old_pyperclip = sys.modules.get("pyperclip")
        old_pyautogui = sys.modules.get("pyautogui")
        sys.modules["pyperclip"] = types.SimpleNamespace(paste=FakeClipboard.paste, copy=FakeClipboard.copy)
        sys.modules["pyautogui"] = types.SimpleNamespace(hotkey=hotkey)
        try:
            result = clipboard.get_selected_text(restore_clipboard=True)
        finally:
            if old_pyperclip is None:
                sys.modules.pop("pyperclip", None)
            else:
                sys.modules["pyperclip"] = old_pyperclip
            if old_pyautogui is None:
                sys.modules.pop("pyautogui", None)
            else:
                sys.modules["pyautogui"] = old_pyautogui

        self.assertIn("secili metin", result)
        self.assertEqual(FakeClipboard.value, "onceki pano")


if __name__ == "__main__":
    unittest.main()
