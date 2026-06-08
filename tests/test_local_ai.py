from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_config  # noqa: E402
import actions.local_ai as lai  # noqa: E402
from actions.safety import classify_tool  # noqa: E402
from core.agent_runtime import AgentRuntime  # noqa: E402


class LocalAITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_config_dir = app_config.CONFIG_DIR
        self.old_config_path = app_config.CONFIG_PATH
        self.config_dir = Path(self.tmp.name) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        app_config.CONFIG_DIR = self.config_dir
        app_config.CONFIG_PATH = self.config_dir / "api_keys.json"

    def tearDown(self) -> None:
        app_config.CONFIG_DIR = self.old_config_dir
        app_config.CONFIG_PATH = self.old_config_path
        self.tmp.cleanup()

    def write_config(self, **values) -> None:
        app_config.CONFIG_PATH.write_text(json.dumps(values), encoding="utf-8")

    def test_legacy_ninerouter_config_maps_to_cloud_fields(self) -> None:
        self.write_config(
            ninerouter_base_url="http://localhost:20128/v1",
            ninerouter_model="codex",
            ninerouter_api_key="key",
        )

        cfg = app_config.load_app_config()

        self.assertEqual(cfg["cloud_base_url"], "http://localhost:20128/v1")
        self.assertEqual(cfg["cloud_model"], "codex")
        self.assertEqual(cfg["cloud_api_key"], "key")
        self.assertTrue(app_config.has_cloud_agent_config(cfg))

    def test_local_manual_config_does_not_require_api_key(self) -> None:
        self.write_config(
            agent_mode="local",
            local_provider="openai_compatible",
            local_base_url="http://127.0.0.1:11434/v1",
            local_model="local-model",
            local_api_key="",
        )

        cfg = app_config.load_app_config()
        local_config = lai.local_agent_config(cfg)

        self.assertEqual(local_config.provider_name, "Local/OpenAI-compatible")
        self.assertEqual(local_config.missing_fields(), [])
        self.assertEqual(local_config.clean_api_key(), "none")

    def test_manual_local_ai_test_uses_openai_compatible_endpoint(self) -> None:
        self.write_config(
            local_provider="openai_compatible",
            local_base_url="http://127.0.0.1:11434/v1",
            local_model="local-model",
        )
        calls = []

        def fake_post(config, payload):
            calls.append((config, payload))
            return {"choices": [{"message": {"content": "tamam"}}]}

        old_post = lai._post_chat_completion
        lai._post_chat_completion = fake_post
        try:
            result = lai.test_local_ai("test")
        finally:
            lai._post_chat_completion = old_post

        self.assertIn("Local AI test basarili", result)
        self.assertEqual(calls[0][0].model, "local-model")
        self.assertEqual(calls[0][0].clean_api_key(), "none")

    def test_foundry_missing_sdk_returns_clear_message(self) -> None:
        self.write_config(local_provider="foundry_local", local_foundry_model_alias="qwen2.5-0.5b")

        old_ensure = lai._ensure_foundry_endpoint
        lai._ensure_foundry_endpoint = lambda _cfg: (_ for _ in ()).throw(RuntimeError("Foundry Local SDK bulunamadi."))
        try:
            result = lai.test_local_ai("test")
        finally:
            lai._ensure_foundry_endpoint = old_ensure

        self.assertIn("Local AI testi basarisiz", result)
        self.assertIn("Foundry Local SDK", result)

    def test_hybrid_router_prefers_local_for_file_and_cloud_for_research(self) -> None:
        runtime = AgentRuntime([])

        local_route = runtime.choose_model_route(
            "bu dosyayi ozetle",
            "hybrid",
            cloud_ready=True,
            local_ready=True,
        )
        cloud_route = runtime.choose_model_route(
            "Vanspor haberlerini arastir",
            "hybrid",
            cloud_ready=True,
            local_ready=True,
        )

        self.assertEqual(local_route.primary, "local")
        self.assertEqual(local_route.fallback, "cloud")
        self.assertEqual(cloud_route.primary, "cloud")
        self.assertEqual(cloud_route.fallback, "local")

    def test_safety_registry_covers_local_ai_tools(self) -> None:
        self.assertEqual(classify_tool("local_ai_status", {}).risk_class, "read")
        self.assertEqual(classify_tool("test_local_ai", {}).risk_class, "external")
        set_mode = classify_tool("set_agent_mode", {"mode": "local"})
        self.assertEqual(set_mode.risk_class, "write")
        self.assertTrue(set_mode.audit_required)


if __name__ == "__main__":
    unittest.main()
