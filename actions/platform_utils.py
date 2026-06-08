from __future__ import annotations

import os
import platform
import subprocess
import time
import webbrowser
from pathlib import Path


SYSTEM = platform.system()
IS_WINDOWS = SYSTEM == "Windows"
IS_MACOS = SYSTEM == "Darwin"


def open_url(url: str) -> bool:
    target = str(url or "").strip()
    if not target:
        return False
    if IS_MACOS:
        subprocess.run(["open", target], check=False)
        return True
    if IS_WINDOWS:
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except Exception:
            return bool(webbrowser.open(target))
    return bool(webbrowser.open(target))


def open_uri(uri: str) -> bool:
    return open_url(uri)


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    value = str(text or "")
    if IS_MACOS:
        try:
            subprocess.run(["pbcopy"], input=value, text=True, check=True, timeout=5)
            return True, "ok"
        except Exception as exc:
            return False, f"Panoya kopyalanamadi: {exc}"

    if IS_WINDOWS:
        try:
            import pyperclip  # type: ignore

            pyperclip.copy(value)
            return True, "ok"
        except Exception:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
                    input=value,
                    text=True,
                    check=True,
                    timeout=5,
                )
                return True, "ok"
            except Exception as exc:
                return False, f"Panoya kopyalanamadi: {exc}"

    try:
        return bool(webbrowser.open("data:text/plain," + value)), "ok"
    except Exception as exc:
        return False, f"Panoya kopyalanamadi: {exc}"


def press_enter_after_delay(delay_seconds: float = 1.0) -> tuple[bool, str]:
    try:
        import pyautogui  # type: ignore

        time.sleep(max(0.0, float(delay_seconds)))
        pyautogui.press("enter")
        return True, "ok"
    except Exception as exc:
        return False, f"Enter tusu gonderilemedi: {exc}"


def paste_text_with_optional_enter(text: str, send_enter: bool = False, delay_seconds: float = 0.2) -> tuple[bool, str]:
    ok, detail = copy_to_clipboard(text)
    if not ok:
        return False, detail
    try:
        import pyautogui  # type: ignore

        time.sleep(max(0.0, float(delay_seconds)))
        pyautogui.hotkey("ctrl", "v")
        if send_enter:
            time.sleep(0.2)
            pyautogui.press("enter")
        return True, "ok"
    except Exception as exc:
        return False, f"Metin yapistirilamadi: {exc}"


def path_exists_any(paths: list[str | Path]) -> bool:
    return any(Path(path).exists() for path in paths if str(path or "").strip())
