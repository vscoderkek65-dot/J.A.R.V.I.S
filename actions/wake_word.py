from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from app_config import load_app_config


@dataclass
class WakeWordConfig:
    enabled: bool = False
    engine: str = "porcupine"
    wake_word: str = "jarvis"
    porcupine_access_key: str = ""
    vosk_model_path: str = ""
    capture_seconds: int = 8


def load_wake_word_config(config: dict | None = None) -> WakeWordConfig:
    cfg = config or load_app_config()
    engine = str(cfg.get("wake_engine", "porcupine") or "porcupine").strip().casefold()
    if engine not in {"porcupine", "vosk"}:
        engine = "porcupine"
    try:
        capture_seconds = int(cfg.get("wake_capture_seconds", 8) or 8)
    except Exception:
        capture_seconds = 8
    return WakeWordConfig(
        enabled=bool(cfg.get("wake_word_enabled", False)),
        engine=engine,
        wake_word=str(cfg.get("wake_word", "jarvis") or "jarvis").strip().casefold() or "jarvis",
        porcupine_access_key=str(cfg.get("porcupine_access_key", "") or "").strip(),
        vosk_model_path=str(cfg.get("vosk_model_path", "") or "").strip(),
        capture_seconds=max(2, min(30, capture_seconds)),
    )


class WakeWordDetector:
    """Optional Porcupine/Vosk wake-word wrapper.

    The class is deliberately lazy: missing SDKs, missing keys or bad models
    become status messages instead of import/runtime crashes.
    """

    def __init__(self, config: WakeWordConfig | None = None) -> None:
        self.config = config or load_wake_word_config()
        self.ready = False
        self.last_error = ""
        self._engine = ""
        self._porcupine = None
        self._porcupine_buffer: list[int] = []
        self._vosk_recognizer = None
        self._init()

    def _init(self) -> None:
        if not self.config.enabled:
            self.last_error = "Wake word kapali; PTT hazir."
            return
        if self.config.engine == "vosk":
            self._init_vosk()
            return
        self._init_porcupine()
        if not self.ready and self.config.vosk_model_path:
            self._init_vosk()

    def _init_porcupine(self) -> None:
        if not self.config.porcupine_access_key:
            self.last_error = "Porcupine AccessKey yok; wake word kapali, PTT calisir."
            return
        try:
            import pvporcupine  # type: ignore
        except Exception as exc:
            self.last_error = f"pvporcupine yuklu degil: {type(exc).__name__}: {exc}"
            return
        try:
            keyword = self.config.wake_word or "jarvis"
            self._porcupine = pvporcupine.create(
                access_key=self.config.porcupine_access_key,
                keywords=[keyword],
            )
            self._engine = "porcupine"
            self.ready = True
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"Porcupine baslatilamadi: {type(exc).__name__}: {exc}"

    def _init_vosk(self) -> None:
        model_path = Path(self.config.vosk_model_path or "")
        if not model_path.exists():
            self.last_error = "Vosk model yolu yok veya bulunamadi; wake word kapali, PTT calisir."
            return
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore
        except Exception as exc:
            self.last_error = f"vosk yuklu degil: {type(exc).__name__}: {exc}"
            return
        try:
            model = Model(str(model_path))
            grammar = json.dumps([self.config.wake_word, f"hey {self.config.wake_word}"])
            self._vosk_recognizer = KaldiRecognizer(model, 16000, grammar)
            self._engine = "vosk"
            self.ready = True
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"Vosk baslatilamadi: {type(exc).__name__}: {exc}"

    @property
    def engine(self) -> str:
        return self._engine or self.config.engine

    def status(self) -> str:
        if self.ready:
            return f"Wake word hazir: {self.engine} / {self.config.wake_word}"
        return self.last_error or "Wake word hazir degil."

    def process_pcm(self, frame: bytes) -> bool:
        if not self.ready or not frame:
            return False
        if self._engine == "porcupine":
            return self._process_porcupine(frame)
        if self._engine == "vosk":
            return self._process_vosk(frame)
        return False

    def _process_porcupine(self, frame: bytes) -> bool:
        detector = self._porcupine
        if not detector:
            return False
        try:
            samples = list(struct.unpack_from("<" + "h" * (len(frame) // 2), frame))
            self._porcupine_buffer.extend(samples)
            frame_length = int(getattr(detector, "frame_length", 512) or 512)
            while len(self._porcupine_buffer) >= frame_length:
                chunk = self._porcupine_buffer[:frame_length]
                del self._porcupine_buffer[:frame_length]
                if detector.process(chunk) >= 0:
                    return True
        except Exception as exc:
            self.ready = False
            self.last_error = f"Porcupine isleme hatasi: {type(exc).__name__}: {exc}"
        return False

    def _process_vosk(self, frame: bytes) -> bool:
        recognizer = self._vosk_recognizer
        if not recognizer:
            return False
        try:
            recognizer.AcceptWaveform(frame)
            text = ""
            for getter in (recognizer.Result, recognizer.PartialResult):
                try:
                    data = json.loads(getter() or "{}")
                    text += " " + str(data.get("text") or data.get("partial") or "")
                except Exception:
                    pass
            return self.config.wake_word in text.casefold()
        except Exception as exc:
            self.ready = False
            self.last_error = f"Vosk isleme hatasi: {type(exc).__name__}: {exc}"
            return False

    def close(self) -> None:
        try:
            if self._porcupine:
                self._porcupine.delete()
        except Exception:
            pass
        self._porcupine = None
        self._vosk_recognizer = None
        self.ready = False
