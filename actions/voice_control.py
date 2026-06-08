from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass

from app_config import load_app_config, normalize_voice_mode, save_app_config


VOICE_MODE_VALUES = {"ptt_wake", "ptt_only", "wake_only", "live_always"}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return folded.casefold().replace("ı", "i").replace("İ", "i")


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", _fold(text)).strip(" .,!?:;\t\r\n")


@dataclass(frozen=True)
class VoiceControlResult:
    action: str
    matched: bool
    text: str = ""


CONTROL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stop", ("dur", "sus", "stop", "sesi kes", "konusma", "konuşma", "kes sesini", "sessiz")),
    ("resume", ("devam et", "devam", "konusmaya devam et", "konuşmaya devam et")),
    ("repeat", ("tekrar oku", "yeniden oku", "bir daha oku", "son cevabi oku", "son cevabı oku")),
    ("shorten", ("kisalt", "kısalt", "daha kisa", "daha kısa", "ozetle", "özetle")),
)


def parse_voice_control(text: str) -> VoiceControlResult:
    value = _compact(text)
    if not value:
        return VoiceControlResult("", False, text)
    for action, phrases in CONTROL_PATTERNS:
        for phrase in phrases:
            folded_phrase = _compact(phrase)
            if value == folded_phrase or value.startswith(folded_phrase + " "):
                return VoiceControlResult(action, True, text)
    return VoiceControlResult("", False, text)


def _split_sentences(text: str) -> list[str]:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", raw)
    return [part.strip() for part in parts if part.strip()]


class SpeechMemory:
    """Keeps the last speakable response for repeat/shorten/resume controls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._sentences: list[str] = []
        self._index = 0
        self._stopped = False

    def set(self, text: str) -> None:
        value = str(text or "").strip()
        with self._lock:
            self._text = value
            self._sentences = _split_sentences(value)
            self._index = 0
            self._stopped = False

    def mark_stopped(self) -> None:
        with self._lock:
            self._stopped = True

    def advance_by_text(self, spoken_text: str) -> None:
        spoken = _compact(spoken_text)
        if not spoken:
            return
        with self._lock:
            for idx, sentence in enumerate(self._sentences):
                if _compact(sentence) and _compact(sentence) in spoken:
                    self._index = min(len(self._sentences), idx + 1)

    def repeat(self) -> str:
        with self._lock:
            self._stopped = False
            self._index = 0
            return self._text

    def resume(self) -> str:
        with self._lock:
            if not self._sentences:
                return self._text
            self._stopped = False
            idx = min(max(self._index, 0), len(self._sentences) - 1)
            return " ".join(self._sentences[idx:]).strip()

    def shorten(self, max_chars: int = 420) -> str:
        with self._lock:
            source = self._sentences or _split_sentences(self._text)
            if not source:
                return ""
            selected: list[str] = []
            for sentence in source:
                selected.append(sentence)
                if len(" ".join(selected)) >= max_chars or len(selected) >= 3:
                    break
            text = " ".join(selected).strip()
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0].strip() + "..."
            return text

    def has_text(self) -> bool:
        with self._lock:
            return bool(self._text)


@dataclass
class VoiceGate:
    mode: str = "ptt_wake"
    ptt_active: bool = False
    wake_active_until: float = 0.0
    muted: bool = False
    paused: bool = False

    def set_mode(self, mode: str) -> None:
        self.mode = normalize_voice_mode(mode)

    def start_ptt(self) -> None:
        self.ptt_active = True

    def stop_ptt(self) -> None:
        self.ptt_active = False

    def arm_wake(self, capture_seconds: float) -> None:
        self.wake_active_until = time.monotonic() + max(0.5, float(capture_seconds or 0))

    def wake_active(self) -> bool:
        return time.monotonic() < self.wake_active_until

    def is_open(self) -> bool:
        if self.muted or self.paused:
            return False
        mode = normalize_voice_mode(self.mode)
        if mode == "live_always":
            return True
        if mode == "ptt_only":
            return self.ptt_active
        if mode == "wake_only":
            return self.wake_active()
        return self.ptt_active or self.wake_active()


def set_voice_mode(mode: str) -> str:
    normalized = normalize_voice_mode(mode)
    save_app_config({"voice_input_mode": normalized})
    labels = {
        "ptt_wake": "PTT + Wake",
        "ptt_only": "Sadece PTT",
        "wake_only": "Sadece wake word",
        "live_always": "Sürekli canlı dinleme",
    }
    return f"Ses modu ayarlandi: {labels.get(normalized, normalized)}"


def voice_experience_status(
    *,
    config: dict | None = None,
    audio_input_available: bool = True,
    audio_output_available: bool = True,
    text_mode: bool = False,
    ptt_active: bool = False,
    wake_ready: bool = False,
    wake_error: str = "",
) -> str:
    cfg = config or load_app_config()
    mode = normalize_voice_mode(cfg.get("voice_input_mode", "ptt_wake"))
    wake_enabled = bool(cfg.get("wake_word_enabled", False))
    lines = [
        "Ses deneyimi durumu:",
        f"- Mod: {mode}",
        f"- Mikrofon: {'hazir' if audio_input_available else 'kapali/text mode'}",
        f"- Cikis sesi: {'hazir' if audio_output_available else 'kapali'}",
        f"- Text mode: {'aktif' if text_mode else 'pasif'}",
        f"- PTT: {'aktif' if ptt_active else 'beklemede'} ({cfg.get('push_to_talk_hotkey', 'ctrl+space')})",
        f"- Wake word: {'acik' if wake_enabled else 'kapali'} / {'hazir' if wake_ready else 'hazir degil'}",
        f"- Wake engine: {cfg.get('wake_engine', 'porcupine')} / kelime: {cfg.get('wake_word', 'jarvis')}",
    ]
    if wake_error:
        lines.append(f"- Wake notu: {wake_error}")
    return "\n".join(lines)
