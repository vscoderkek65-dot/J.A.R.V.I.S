from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions.logging_utils import safe_log_preview  # noqa: E402


class RuntimeLoggingTests(unittest.TestCase):
    def test_safe_log_preview_masks_secrets_and_redacts_content_fields(self) -> None:
        preview = safe_log_preview(
            {
                "api_key": "fake-secret-value-for-test",
                "message": "Bu mesaj terminal loguna ham dusmemeli.",
                "nested": {"value": "hafiza degeri", "normal": "kalabilir"},
            },
            limit=800,
            redact_content_keys=True,
        )

        self.assertIn("***REDACTED***", preview)
        self.assertIn("***REDACTED_CONTENT", preview)
        self.assertIn("kalabilir", preview)
        self.assertNotIn("fake-secret-value-for-test", preview)
        self.assertNotIn("terminal loguna ham", preview)
        self.assertNotIn("hafiza degeri", preview)

    def test_runtime_logging_no_longer_prints_raw_values_or_tracebacks(self) -> None:
        # Check in the actions module where safe_log_preview actually lives
        text = (ROOT / "actions" / "logging_utils.py").read_text(encoding="utf-8")
        main_text = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("= {val}", main_text)
        self.assertNotIn("traceback.print_exc()", main_text)
        self.assertIn("safe_log_preview", text)


if __name__ == "__main__":
    unittest.main()
