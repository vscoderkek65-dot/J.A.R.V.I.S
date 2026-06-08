import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app_config
from actions.voice_control import (
    SpeechMemory,
    VoiceGate,
    parse_voice_control,
    set_voice_mode,
    voice_experience_status,
)
from actions.wake_word import WakeWordConfig, WakeWordDetector
from actions.tts import SpeechController


class VoiceControlTests(unittest.TestCase):
    def test_control_parser_handles_turkish_commands(self):
        self.assertEqual(parse_voice_control("sus").action, "stop")
        self.assertEqual(parse_voice_control("Dur artık").action, "stop")
        self.assertEqual(parse_voice_control("tekrar oku").action, "repeat")
        self.assertEqual(parse_voice_control("kısalt").action, "shorten")
        self.assertFalse(parse_voice_control("Vanspor haberlerini oku").matched)

    def test_speech_memory_repeat_resume_and_shorten(self):
        memory = SpeechMemory()
        memory.set("Birinci cumle. Ikinci cumle. Ucuncu cumle. Dorduncu cumle.")
        self.assertEqual(memory.repeat(), "Birinci cumle. Ikinci cumle. Ucuncu cumle. Dorduncu cumle.")
        memory.advance_by_text("Birinci cumle.")
        self.assertTrue(memory.resume().startswith("Ikinci cumle."))
        self.assertIn("Birinci cumle.", memory.shorten(max_chars=80))

    def test_voice_gate_modes(self):
        gate = VoiceGate(mode="ptt_only")
        self.assertFalse(gate.is_open())
        gate.start_ptt()
        self.assertTrue(gate.is_open())
        gate.stop_ptt()
        self.assertFalse(gate.is_open())
        gate.set_mode("wake_only")
        gate.arm_wake(0.6)
        self.assertTrue(gate.is_open())
        time.sleep(0.7)
        self.assertFalse(gate.is_open())
        gate.set_mode("live_always")
        self.assertTrue(gate.is_open())
        gate.muted = True
        self.assertFalse(gate.is_open())

    def test_set_voice_mode_writes_normalized_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = app_config.CONFIG_PATH
            app_config.CONFIG_PATH = Path(tmp) / "api_keys.json"
            try:
                result = set_voice_mode("ptt")
                self.assertIn("ptt", result.casefold())
                self.assertEqual(app_config.load_app_config()["voice_input_mode"], "ptt_only")
            finally:
                app_config.CONFIG_PATH = original

    def test_voice_status_reports_text_mode(self):
        status = voice_experience_status(
            config={"voice_input_mode": "ptt_wake", "wake_word_enabled": False},
            audio_input_available=False,
            audio_output_available=True,
            text_mode=True,
            ptt_active=False,
            wake_ready=False,
            wake_error="Porcupine AccessKey yok",
        )
        self.assertIn("Text mode: aktif", status)
        self.assertIn("Porcupine AccessKey yok", status)


class WakeWordTests(unittest.TestCase):
    def test_disabled_wake_detector_is_safe(self):
        detector = WakeWordDetector(WakeWordConfig(enabled=False))
        self.assertFalse(detector.ready)
        self.assertIn("PTT", detector.status())
        self.assertFalse(detector.process_pcm(b"\0" * 64))

    def test_porcupine_without_key_returns_clear_error(self):
        detector = WakeWordDetector(WakeWordConfig(enabled=True, engine="porcupine", porcupine_access_key=""))
        self.assertFalse(detector.ready)
        self.assertIn("AccessKey", detector.status())

    def test_vosk_missing_model_returns_clear_error(self):
        detector = WakeWordDetector(WakeWordConfig(enabled=True, engine="vosk", vosk_model_path="Z:/missing-model"))
        self.assertFalse(detector.ready)
        self.assertIn("Vosk model", detector.status())

    def test_porcupine_mock_detects_wake(self):
        class FakePorcupine:
            frame_length = 4

            def process(self, frame):
                return 0

            def delete(self):
                pass

        fake_module = mock.Mock()
        fake_module.create.return_value = FakePorcupine()
        with mock.patch.dict("sys.modules", {"pvporcupine": fake_module}):
            detector = WakeWordDetector(
                WakeWordConfig(enabled=True, engine="porcupine", porcupine_access_key="key")
            )
            self.assertTrue(detector.ready)
            self.assertTrue(detector.process_pcm(b"\1\0" * 4))


class SpeechControllerTests(unittest.TestCase):
    def test_stop_calls_windows_engine_stop(self):
        calls = []

        class FakeEngine:
            def getProperty(self, name):
                return []

            def say(self, text):
                calls.append(("say", text))

            def runAndWait(self):
                calls.append(("run", "wait"))

            def stop(self):
                calls.append(("stop", "engine"))

        fake_pyttsx3 = mock.Mock()
        fake_pyttsx3.init.return_value = FakeEngine()
        with mock.patch.dict(sys.modules, {"pyttsx3": fake_pyttsx3}):
            with mock.patch("actions.tts.IS_WINDOWS", True), mock.patch("actions.tts.IS_MACOS", False):
                controller = SpeechController()
                controller.speak("Merhaba.", blocking=True)
                controller.stop()
        self.assertIn(("stop", "engine"), calls)


if __name__ == "__main__":
    unittest.main()
