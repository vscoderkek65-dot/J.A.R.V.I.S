from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from memory.memory_manager import format_memory_for_prompt
from ui.settings import SettingsMixin


ROOT = Path(__file__).resolve().parents[1]


class SettingsDialogTests(unittest.TestCase):
    def test_memory_prompt_formatter_accepts_loaded_memory_mapping(self) -> None:
        result = format_memory_for_prompt({"preferences": {"style": "short"}})
        self.assertIn("preferences/style", result)

    def test_settings_dialog_has_scrollable_body_and_fixed_save_footer(self) -> None:
        source = inspect.getsource(SettingsMixin._show_setup_ui)
        self.assertIn("tk.Scrollbar", source)
        self.assertIn("self.setup_dialog", source)
        self.assertIn("AYARLARI KAYDET", source)
        self.assertIn('footer.pack(fill="x"', source)

    def test_settings_rejects_url_in_api_key_field_and_tests_cloud(self) -> None:
        save_source = inspect.getsource(SettingsMixin._save_api_key)
        test_source = inspect.getsource(SettingsMixin._test_local_ai_from_setup)
        self.assertIn('startswith(("http://", "https://"))', save_source)
        self.assertIn("cloud_agent_config", test_source)
        self.assertIn("_post_chat_completion", test_source)

    def test_live_config_builder_uses_current_memory_formatter_signatures(self) -> None:
        source = (ROOT / "core" / "jarvis_live.py").read_text(encoding="utf-8")
        self.assertNotIn("max_chars=", source)
        self.assertIn("format_memory_for_prompt(load_memory())", source)
        self.assertIn('getattr(types, "ContextWindowCompression", None)', source)
        self.assertIn('getattr(types, "SessionResumptionConfig", None)', source)
        self.assertIn('response_modalities=["AUDIO"]', source)

    def test_live_model_is_current_supported_preview(self) -> None:
        source = (ROOT / "core" / "jarvis_live.py").read_text(encoding="utf-8")
        self.assertIn('LIVE_MODEL = "gemini-3.1-flash-live-preview"', source)


if __name__ == "__main__":
    unittest.main()
