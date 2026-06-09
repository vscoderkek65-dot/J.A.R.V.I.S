from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions.smoke import build_timeout_report, run_smoke_sequence  # noqa: E402


class FakeRoot:
    def __init__(self) -> None:
        self.destroyed = False

    def after(self, _delay: int, callback, *args):
        callback(*args)

    def winfo_exists(self) -> bool:
        return not self.destroyed


class FakeUI:
    def __init__(self) -> None:
        self.root = FakeRoot()
        self.logs: list[str] = []

    def write_log(self, message: str) -> None:
        self.logs.append(message)


class FakeJarvis:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def _on_text_command(self, text: str) -> None:
        self.commands.append(text)


class WindowsSmokeTests(unittest.TestCase):
    def test_smoke_sequence_passes_with_mock_helpers_and_writes_report(self) -> None:
        ui = FakeUI()
        jarvis = FakeJarvis()
        with tempfile.TemporaryDirectory() as tmp:
            report = run_smoke_sequence(
                ui=ui,
                jarvis=jarvis,
                smoke_app="explorer",
                report_dir=tmp,
                helpers={
                    "web_research": lambda query, max_pages=2, open_browser=False: "Kisa cevap:\nOk.\n\nKaynaklar:\nKaynak: https://example.com",
                    "read_text_file": lambda path, max_chars=2000: f"{path} icerigi:\nhello",
                    "open_app": lambda app: f"{app} acildi.",
                    "analyze_screen": lambda query: "[Aktif pencere]\nEkran analizi tamam.",
                    "speak_text": lambda text, blocking=True: None,
                    "get_available_voices": lambda: ["Turkish"],
                },
            )
            files = list(Path(tmp).glob("windows-smoke-*.json"))
            saved = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "pass")
        self.assertEqual(saved["status"], "pass")
        self.assertTrue(all("reason_code" in step for step in report["steps"]))
        self.assertTrue(any("SMOKE PASS" in line for line in ui.logs))
        self.assertEqual(jarvis.commands, ["hafiza durumu"])

    def test_screen_key_missing_and_tts_missing_are_degraded_not_failed(self) -> None:
        ui = FakeUI()
        with tempfile.TemporaryDirectory() as tmp:
            report = run_smoke_sequence(
                ui=ui,
                jarvis=FakeJarvis(),
                report_dir=tmp,
                helpers={
                    "web_research": lambda **_kwargs: "Kisa cevap:\nOk.\n\nKaynaklar:\nKaynak: https://example.com",
                    "read_text_file": lambda **_kwargs: "test_acceptance.ps1 icerigi:\nok",
                    "open_app": lambda _app: "explorer acildi.",
                    "analyze_screen": lambda _query: "Gemini API anahtari eksik oldugu icin ekran analizi yapilamadi.",
                    "speak_text": lambda *_args, **_kwargs: None,
                    "get_available_voices": lambda: [],
                },
            )

        self.assertEqual(report["status"], "degraded")
        statuses = {step["name"]: step["status"] for step in report["steps"]}
        reasons = {step["name"]: step["reason_code"] for step in report["steps"]}
        self.assertEqual(statuses["screen_analysis"], "degraded")
        self.assertEqual(statuses["tts_text_mode"], "degraded")
        self.assertEqual(reasons["screen_analysis"], "screen_analysis_limited")
        self.assertEqual(reasons["tts_text_mode"], "tts_voice_missing")

    def test_web_research_with_source_is_not_degraded_by_warning_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_smoke_sequence(
                ui=FakeUI(),
                jarvis=FakeJarvis(),
                report_dir=tmp,
                helpers={
                    "web_research": lambda **_kwargs: "Kisa cevap:\nOk.\n\nKaynaklar:\nKaynak: https://example.com\nArama notlari: hata kelimesi kaynak notunda gecebilir",
                    "read_text_file": lambda **_kwargs: "test_acceptance.ps1 icerigi:\nok",
                    "open_app": lambda _app: "explorer acildi.",
                    "analyze_screen": lambda _query: "[Aktif pencere]\nok",
                    "speak_text": lambda *_args, **_kwargs: None,
                    "get_available_voices": lambda: ["Turkish"],
                },
            )

        statuses = {step["name"]: step["status"] for step in report["steps"]}
        reasons = {step["name"]: step["reason_code"] for step in report["steps"]}
        self.assertEqual(statuses["web_research"], "pass")
        self.assertEqual(reasons["web_research"], "web_research_ok")

    def test_smoke_report_sanitizes_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_smoke_sequence(
                ui=FakeUI(),
                jarvis=FakeJarvis(),
                report_dir=tmp,
                helpers={
                    "web_research": lambda **_kwargs: "Kisa cevap: sk-secret1234567890\nKaynaklar:\nKaynak: https://example.com",
                    "read_text_file": lambda **_kwargs: "test_acceptance.ps1 icerigi:\nok",
                    "open_app": lambda _app: "explorer acildi.",
                    "analyze_screen": lambda _query: "[Aktif pencere]\nok",
                    "speak_text": lambda *_args, **_kwargs: None,
                    "get_available_voices": lambda: ["Turkish"],
                },
            )
            raw = Path(report["report_path"]).read_text(encoding="utf-8")

        self.assertNotIn("sk-secret1234567890", raw)
        self.assertIn("***REDACTED***", raw)

    def test_timeout_report_is_failed_and_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_timeout_report(12, tmp)
            report_exists = Path(report["report_path"]).exists()

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["reason"], "timeout")
        self.assertEqual(report["steps"][0]["reason_code"], "smoke_timeout")
        self.assertTrue(report_exists)


if __name__ == "__main__":
    unittest.main()
