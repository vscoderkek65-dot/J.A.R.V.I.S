"""
Cross-platform, interruptible text-to-speech helper.
"""

from __future__ import annotations

import re
import subprocess
import threading

from actions.platform_utils import IS_MACOS, IS_WINDOWS


VOICE = "Yelda"


def _chunks(text: str, max_len: int = 450) -> list[str]:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", raw) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [raw]:
        if current and len(current) + len(sentence) + 1 > max_len:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    if not chunks and len(raw) > max_len:
        chunks = [raw[i : i + max_len] for i in range(0, len(raw), max_len)]
    return chunks


class SpeechController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._engine = None
        self._process: subprocess.Popen | None = None
        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._is_speaking

    def speak(self, text: str, on_done=None, blocking: bool = False):
        value = str(text or "").strip()
        if not value:
            if on_done:
                on_done()
            return None

        def _run():
            self._run_speech(value, on_done)

        self.stop()
        self._stop_event.clear()
        if blocking:
            _run()
            return None
        thread = threading.Thread(target=_run, daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            engine = self._engine
            process = self._process
            self._is_speaking = False
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

    def _run_speech(self, text: str, on_done=None) -> None:
        with self._lock:
            self._is_speaking = True
        try:
            if IS_WINDOWS:
                self._speak_windows(text)
            elif IS_MACOS:
                self._speak_macos(text)
        except Exception:
            pass
        finally:
            with self._lock:
                self._engine = None
                self._process = None
                self._is_speaking = False
            if on_done:
                on_done()

    def _speak_windows(self, text: str) -> None:
        import pyttsx3  # type: ignore

        engine = pyttsx3.init()
        with self._lock:
            self._engine = engine
        try:
            for voice in engine.getProperty("voices") or []:
                name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                if "turkish" in name or "tr_" in name or "tr-" in name:
                    engine.setProperty("voice", voice.id)
                    break
            for chunk in _chunks(text):
                if self._stop_event.is_set():
                    break
                engine.say(chunk)
                engine.runAndWait()
        finally:
            try:
                engine.stop()
            except Exception:
                pass

    def _speak_macos(self, text: str) -> None:
        for chunk in _chunks(text):
            if self._stop_event.is_set():
                break
            process = subprocess.Popen(["say", "-v", VOICE, chunk])
            with self._lock:
                self._process = process
            process.wait()


_CONTROLLER = SpeechController()


def get_speech_controller() -> SpeechController:
    return _CONTROLLER


def speak_text(text: str, on_done=None, blocking: bool = False):
    """Metni sesli olarak okur. Eski public API korunur."""
    return _CONTROLLER.speak(text, on_done=on_done, blocking=blocking)


def stop_speech() -> None:
    _CONTROLLER.stop()


def get_available_voices() -> list[str]:
    if IS_WINDOWS:
        try:
            import pyttsx3  # type: ignore

            engine = pyttsx3.init()
            voices = [str(getattr(voice, "name", "") or getattr(voice, "id", "")) for voice in engine.getProperty("voices") or []]
            engine.stop()
            return [voice for voice in voices if voice]
        except Exception:
            return []

    if IS_MACOS:
        try:
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
            voices = []
            for line in result.stdout.splitlines():
                if line.strip():
                    voices.append(line.split()[0])
            return voices
        except Exception:
            return []

    return []
