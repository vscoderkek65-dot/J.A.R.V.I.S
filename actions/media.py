"""
Cross-platform media launcher for YouTube, Spotify, and best-effort music apps.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.parse

from actions.browser import browser_control
from actions.platform_utils import IS_MACOS, IS_WINDOWS, copy_to_clipboard, open_uri, open_url


SPOTIFY_MAC_APP = "/Applications/Spotify.app"
MUSIC_MAC_APP = "/System/Applications/Music.app"


def _run_osascript(script: str, timeout: int = 16) -> tuple[bool, str]:
    if not IS_MACOS:
        return False, "AppleScript bu platformda desteklenmiyor."
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"AppleScript calistirilamadi: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "Bilinmeyen AppleScript hatasi"
        return False, detail

    return True, (result.stdout or "").strip()


def _app_exists(path: str) -> bool:
    return os.path.exists(path)


def _play_youtube(query: str) -> str:
    return browser_control("play_youtube", query=query)


def _windows_autoplay_hint() -> tuple[bool, str]:
    try:
        import pyautogui  # type: ignore

        time.sleep(2.0)
        pyautogui.press("enter")
        time.sleep(0.25)
        pyautogui.press("space")
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _play_spotify_windows(query: str, autoplay: bool = True) -> str:
    encoded_query = urllib.parse.quote(query.strip())
    search_url = f"spotify:search:{encoded_query}"
    try:
        open_uri(search_url)
    except Exception as exc:
        return f"Spotify acilamadi: {exc}"

    if not autoplay:
        return f"Spotify icinde '{query}' aramasi acildi."

    ok, detail = _windows_autoplay_hint()
    if ok:
        return f"Spotify'da oynatma denendi: {query}"
    return (
        f"Spotify aramasi acildi ama otomatik oynatma tamamlanamadi: {detail}. "
        "Spotify penceresinden ilk sonucu elle baslatabilirsin."
    )


def _play_spotify_macos(query: str, autoplay: bool = True) -> str:
    if not _app_exists(SPOTIFY_MAC_APP):
        return "Spotify yuklu gorunmuyor."

    encoded_query = urllib.parse.quote(query.strip())
    search_url = f"spotify:search:{encoded_query}"

    try:
        subprocess.run(["open", search_url], check=True, timeout=10)
    except Exception as exc:
        return f"Spotify acilamadi: {exc}"

    if not autoplay:
        return f"Spotify icinde '{query}' aramasi acildi."

    script = (
        'tell application "Spotify" to activate\n'
        "delay 1.8\n"
        'tell application "System Events"\n'
        "    key code 48\n"
        "    delay 0.2\n"
        "    key code 125\n"
        "    delay 0.2\n"
        "    key code 36\n"
        "    delay 0.5\n"
        "    key code 49\n"
        "end tell\n"
    )
    ok, detail = _run_osascript(script, timeout=14)
    if ok:
        return f"Spotify'da oynatiliyor: {query}"

    return (
        f"Spotify aramasi acildi ama otomatik oynatma tamamlanamadi: {detail}. "
        "Erisilebilirlik izni gerekebilir."
    )


def _play_spotify(query: str, autoplay: bool = True) -> str:
    if IS_WINDOWS:
        return _play_spotify_windows(query, autoplay=autoplay)
    if IS_MACOS:
        return _play_spotify_macos(query, autoplay=autoplay)
    return _play_youtube(query)


def _play_music_app(query: str, autoplay: bool = True) -> str:
    if IS_WINDOWS:
        encoded = urllib.parse.quote_plus(query.strip())
        open_url(f"https://music.apple.com/search?term={encoded}")
        return f"Apple Music web aramasi acildi: {query}"

    if not IS_MACOS:
        return _play_youtube(query)

    if not _app_exists(MUSIC_MAC_APP):
        return "Apple Music / Music uygulamasi bulunamadi."

    if autoplay:
        escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'set queryText to "{escaped_query}"\n'
            'tell application "Music"\n'
            "    activate\n"
            "    try\n"
            "        set foundTracks to (search library playlist 1 for queryText only songs)\n"
            "        if (count of foundTracks) > 0 then\n"
            "            set targetTrack to item 1 of foundTracks\n"
            "            play targetTrack\n"
            "            return \"PLAYED\"\n"
            "        end if\n"
            "    end try\n"
            "end tell\n"
            "return \"NOT_FOUND\"\n"
        )
        ok, detail = _run_osascript(script, timeout=18)
        if ok and "PLAYED" in detail:
            return f"Music uygulamasinda oynatiliyor: {query}"

    ok_clip, detail_clip = copy_to_clipboard(query.strip())
    if not ok_clip:
        return detail_clip

    script = (
        'tell application "Music" to activate\n'
        "delay 1.0\n"
        'tell application "System Events"\n'
        '    keystroke "f" using {command down}\n'
        "    delay 0.3\n"
        '    keystroke "a" using {command down}\n'
        "    delay 0.1\n"
        '    keystroke "v" using {command down}\n'
        "    delay 1.1\n"
        "    key code 36\n"
        "    delay 0.7\n"
        "    key code 125\n"
        "    delay 0.2\n"
        "    key code 36\n"
        "end tell\n"
    )
    ok, detail = _run_osascript(script, timeout=16)
    if ok:
        if autoplay:
            return f"Music uygulamasinda '{query}' icin arama yapildi ve ilk sonuc acildi."
        return f"Music uygulamasinda '{query}' aramasi acildi."

    search_url = f"music://music.apple.com/search?term={urllib.parse.quote(query.strip())}"
    try:
        subprocess.run(["open", search_url], check=False, timeout=10)
    except Exception:
        pass
    return (
        f"Music uygulamasinda dogrudan oynatma tamamlanamadi: {detail}. "
        f"Arama acildi: {query}"
    )


def play_media(query: str, provider: str = "auto", autoplay: bool = True) -> str:
    if not query or not query.strip():
        return "Calinacak icerik belirtilmedi."

    normalized_provider = (provider or "auto").strip().lower()
    if normalized_provider in {"yt", "youtube music"}:
        normalized_provider = "youtube"
    elif normalized_provider in {"apple music", "music", "apple_music"}:
        normalized_provider = "apple_music"

    if normalized_provider == "spotify":
        return _play_spotify(query, autoplay=autoplay)
    if normalized_provider == "apple_music":
        return _play_music_app(query, autoplay=autoplay)
    if normalized_provider == "youtube":
        return _play_youtube(query)

    if IS_WINDOWS:
        spotify_result = _play_spotify_windows(query, autoplay=autoplay)
        if "acilamadi" not in spotify_result.lower():
            return spotify_result
        return _play_youtube(query)

    if IS_MACOS and _app_exists(SPOTIFY_MAC_APP):
        result = _play_spotify_macos(query, autoplay=autoplay)
        if "yuklu gorunmuyor" not in result and "acilamadi" not in result:
            return result

    result = _play_music_app(query, autoplay=autoplay)
    if "bulunamadi" not in result:
        return result
    return _play_youtube(query)
