from __future__ import annotations

import time

from actions.platform_utils import copy_to_clipboard


def _read_clipboard_text() -> tuple[bool, str]:
    try:
        import pyperclip  # type: ignore

        return True, str(pyperclip.paste() or "")
    except Exception as exc:
        return False, f"Pano okunamadi: {exc}"


def _summarize_text(text: str, label: str = "Metin") -> str:
    clean = str(text or "").strip()
    if not clean:
        return f"{label} bos."
    words = clean.split()
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    preview = " ".join(words[:90])
    if len(words) > 90:
        preview += " ..."
    return (
        f"{label} ozeti: {len(words)} kelime, {len(lines)} dolu satir.\n"
        f"Onizleme: {preview}"
    )


def get_clipboard(max_chars: int = 12000) -> str:
    ok, text = _read_clipboard_text()
    if not ok:
        return text
    if not text:
        return "Pano bos."
    max_chars = max(200, min(40000, int(max_chars or 12000)))
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (pano kirpildi)"
    return f"Pano icerigi:\n{text}"


def set_clipboard(text: str) -> str:
    if text is None:
        return "Panoya yazilacak metin belirtilmedi."
    ok, detail = copy_to_clipboard(str(text))
    if not ok:
        return detail
    return "Metin panoya kopyalandi."


def summarize_clipboard(max_chars: int = 4000) -> str:
    raw = get_clipboard(max_chars=max_chars)
    if raw in {"Pano bos."} or raw.startswith("Pano okunamadi"):
        return raw
    text = raw.removeprefix("Pano icerigi:\n").strip()
    return _summarize_text(text, "Pano")


def get_selected_text(max_chars: int = 12000, restore_clipboard: bool = True) -> str:
    ok, previous = _read_clipboard_text()
    if not ok:
        return previous
    try:
        import pyautogui  # type: ignore
        import pyperclip  # type: ignore

        pyperclip.copy("")
        time.sleep(0.08)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.22)
        selected = str(pyperclip.paste() or "")
        if restore_clipboard:
            pyperclip.copy(previous)
    except Exception as exc:
        return f"Secili metin alinamadi: {type(exc).__name__}: {exc}"

    if not selected.strip():
        return "Secili metin alinamadi. Metni secip tekrar dene veya once Ctrl+C ile panoya kopyala."
    max_chars = max(200, min(40000, int(max_chars or 12000)))
    if len(selected) > max_chars:
        selected = selected[:max_chars] + "\n... (secili metin kirpildi)"
    restored = " Eski pano geri yuklendi." if restore_clipboard else " Secili metin panoda birakildi."
    return f"Secili metin:{restored}\n{selected}"


def summarize_selected_text(max_chars: int = 4000) -> str:
    raw = get_selected_text(max_chars=max_chars)
    if raw.startswith("Secili metin alinamadi") or raw.startswith("Pano okunamadi"):
        return raw
    text = raw.split("\n", 1)[1] if "\n" in raw else raw
    return _summarize_text(text, "Secili metin")
