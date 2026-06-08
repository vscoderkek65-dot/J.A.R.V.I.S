"""
Cross-platform application launcher for JARVIS.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from actions.platform_utils import IS_MACOS, IS_WINDOWS, open_uri


MAC_APP_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "finder": "Finder",
    "spotify": "Spotify",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "xcode": "Xcode",
    "notion": "Notion",
    "slack": "Slack",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "zoom": "zoom.us",
    "mail": "Mail",
    "calendar": "Calendar",
    "takvim": "Calendar",
    "notes": "Notes",
    "notlar": "Notes",
    "music": "Music",
    "muzik": "Music",
    "photos": "Photos",
    "fotograflar": "Photos",
    "maps": "Maps",
    "haritalar": "Maps",
    "calculator": "Calculator",
    "hesap makinesi": "Calculator",
    "system preferences": "System Preferences",
    "system settings": "System Settings",
    "ayarlar": "System Settings",
    "activity monitor": "Activity Monitor",
    "aktivite monitoru": "Activity Monitor",
    "preview": "Preview",
    "onizleme": "Preview",
    "textedit": "TextEdit",
    "numbers": "Numbers",
    "pages": "Pages",
    "keynote": "Keynote",
    "figma": "Figma",
    "postman": "Postman",
    "docker": "Docker",
    "tableplus": "TablePlus",
}


WINDOWS_APP_ALIASES = {
    "chrome": ["chrome"],
    "google chrome": ["chrome"],
    "edge": ["msedge"],
    "microsoft edge": ["msedge"],
    "firefox": ["firefox"],
    "terminal": ["wt", "powershell"],
    "windows terminal": ["wt"],
    "cmd": ["cmd"],
    "komut istemi": ["cmd"],
    "powershell": ["powershell"],
    "explorer": ["explorer"],
    "finder": ["explorer"],
    "dosyalar": ["explorer"],
    "files": ["explorer"],
    "notepad": ["notepad"],
    "not defteri": ["notepad"],
    "calculator": ["calc"],
    "hesap makinesi": ["calc"],
    "paint": ["mspaint"],
    "settings": ["ms-settings:"],
    "ayarlar": ["ms-settings:"],
    "spotify": ["spotify:"],
    "vscode": ["code"],
    "vs code": ["code"],
    "code": ["code"],
    "visual studio code": ["code"],
    "visual studio": ["devenv"],
    "notion": ["notion"],
    "slack": ["slack"],
    "discord": ["discord"],
    "whatsapp": ["whatsapp:"],
    "telegram": ["telegram"],
    "zoom": ["zoom"],
    "teams": ["ms-teams:"],
    "mail": ["outlookmail:"],
    "calendar": ["outlookcal:"],
    "takvim": ["outlookcal:"],
    "outlook": ["outlook"],
    "word": ["winword"],
    "excel": ["excel"],
    "powerpoint": ["powerpnt"],
    "figma": ["figma"],
    "postman": ["postman"],
    "docker": ["docker desktop", "docker"],
}


def _open_macos(app_name: str, resolved: str) -> str:
    try:
        result = subprocess.run(
            ["open", "-a", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"{resolved} acildi."

        result2 = subprocess.run(
            ["open", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.returncode == 0:
            return f"{app_name} acildi."
        return f"'{app_name}' bulunamadi veya acilamadi."
    except subprocess.TimeoutExpired:
        return f"'{app_name}' acilirken zaman asimi."
    except Exception as exc:
        return f"Hata: {exc}"


def _try_windows_candidate(candidate: str) -> tuple[bool, str]:
    value = candidate.strip()
    if not value:
        return False, "bos aday"

    if value.endswith(":") or "://" in value:
        try:
            open_uri(value)
            return True, value
        except Exception as exc:
            return False, str(exc)

    expanded = os.path.expandvars(value)
    if Path(expanded).exists():
        try:
            os.startfile(expanded)  # type: ignore[attr-defined]
            return True, expanded
        except Exception as exc:
            return False, str(exc)

    try:
        subprocess.Popen([value], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, value
    except FileNotFoundError:
        return False, "bulunamadi"
    except Exception as exc:
        return False, str(exc)


def _open_windows(app_name: str, candidates: list[str]) -> str:
    errors: list[str] = []
    for candidate in candidates:
        ok, detail = _try_windows_candidate(candidate)
        if ok:
            return f"{app_name} acildi."
        errors.append(f"{candidate}: {detail}")
    detail = "; ".join(errors[:3])
    return f"'{app_name}' bulunamadi veya acilamadi." + (f" ({detail})" if detail else "")


def open_app(app_name: str) -> str:
    """Uygulamayi acar, basari/hata mesaji dondurur."""
    if not app_name:
        return "Uygulama adi belirtilmedi."

    normalized = app_name.lower().strip()

    if IS_WINDOWS:
        candidates = WINDOWS_APP_ALIASES.get(normalized, [app_name])
        return _open_windows(app_name, candidates)

    if IS_MACOS:
        resolved = MAC_APP_ALIASES.get(normalized, app_name)
        return _open_macos(app_name, resolved)

    try:
        subprocess.Popen([app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"{app_name} acildi."
    except Exception as exc:
        return f"'{app_name}' acilamadi: {exc}"
