from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions.audit import AuditLogger  # noqa: E402
from actions.plugin_system import PluginRegistry, set_plugin_registry, validate_manifest  # noqa: E402
from actions.safety import PendingActionManager, classify_tool, guard_tool_call  # noqa: E402


def write_manifest(root: Path, plugin_id: str = "mock", transport: str = "stdio", risk: str = "execute") -> Path:
    plugin_dir = root / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    path = plugin_dir / "plugin.json"
    data = {
        "id": plugin_id,
        "name": f"{plugin_id} plugin",
        "description": "test plugin",
        "version": "1.0.0",
        "permissions": ["read", "write", "external", "execute"],
        "risk_level": risk,
        "config_schema": {
            "type": "object",
            "properties": {
                "transport": {"type": "string"},
                "command": {"type": "string"},
                "url": {"type": "string"},
                "api_key": {"type": "string", "secret": True},
            },
        },
        "mcp": {"transport": transport},
        "tools": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class PluginSystemTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_plugin_registry(None)

    def make_registry(self, tmp: str, plugin_id: str = "mock", transport: str = "stdio") -> PluginRegistry:
        base = Path(tmp)
        write_manifest(base, plugin_id=plugin_id, transport=transport)
        return PluginRegistry(
            plugin_dirs=[base / "plugins"],
            builtin_dir=base / "builtin",
            state_path=base / "state" / "plugin_state.json",
        )

    def test_manifest_validation_rejects_websocket_transport(self) -> None:
        bad = {
            "id": "bad",
            "name": "Bad",
            "description": "bad",
            "version": "1.0",
            "permissions": ["read"],
            "risk_level": "read",
            "mcp": {"transport": "websocket"},
        }

        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_default_state_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp)
            state = registry.load_state()

        self.assertFalse(state["plugins"]["mock"]["enabled"])

    def test_secret_config_is_masked_in_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp)
            registry.set_config("mock", {"transport": "stdio", "command": "python", "api_key": "sk-secret1234567890"})
            status = registry.plugin_status("mock")

        self.assertIn("***REDACTED***", status)
        self.assertNotIn("sk-secret1234567890", status)

    def test_stdio_discover_and_call_use_mcp_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp, transport="stdio")
            registry.enable_plugin("mock")
            registry.set_config("mock", {"command": "python", "args": ["server.py"]})
            set_plugin_registry(registry)
            with patch("actions.plugin_system.mcp_list_tools") as list_mock, patch("actions.plugin_system.mcp_call_tool") as call_mock:
                list_mock.return_value = [{"name": "echo", "description": "Echo", "input_schema": {}, "risk_class": "read"}]
                call_mock.return_value = {"text": "pong", "raw": {"content": [{"type": "text", "text": "pong"}]}}

                discovered = registry.discover_tools("mock")
                result = registry.call_plugin_tool("mock", "echo", {"text": "hi"})

        self.assertIn("echo", discovered)
        self.assertIn("pong", result)
        self.assertIn("Untrusted MCP content", result)

    def test_streamable_http_discovery_uses_config_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp, plugin_id="remote", transport="streamable_http")
            registry.enable_plugin("remote")
            registry.set_config("remote", {"url": "http://127.0.0.1:9999/mcp", "headers": {"authorization": "Bearer secret"}})
            with patch("actions.plugin_system.mcp_list_tools") as list_mock:
                list_mock.return_value = [{"name": "search", "description": "Search", "input_schema": {}}]
                result = registry.discover_tools("remote")
                config = list_mock.call_args.args[0]

        self.assertIn("search", result)
        self.assertEqual(config.transport, "streamable_http")
        self.assertEqual(config.url, "http://127.0.0.1:9999/mcp")

    def test_risky_plugin_tool_requires_pending_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp)
            registry.enable_plugin("mock")
            registry.set_config("mock", {"command": "python"})
            state = registry.load_state()
            state["plugins"]["mock"]["discovered_tools"] = [
                {"name": "danger", "description": "danger", "risk_class": "write"}
            ]
            registry.save_state(state)
            set_plugin_registry(registry)

            policy = classify_tool("call_plugin_tool", {"plugin_id": "mock", "tool_name": "danger"})

        self.assertEqual(policy.risk_class, "write")
        self.assertTrue(policy.requires_approval)

    def test_risky_plugin_tool_cannot_disable_required_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp)
            registry.enable_plugin("mock")
            registry.set_config("mock", {"command": "python"})
            state = registry.load_state()
            state["plugins"]["mock"]["discovered_tools"] = [
                {"name": "danger", "description": "danger", "risk_class": "execute", "requires_approval": False}
            ]
            registry.save_state(state)
            set_plugin_registry(registry)

            policy = classify_tool("call_plugin_tool", {"plugin_id": "mock", "tool_name": "danger"})

        self.assertEqual(policy.risk_class, "execute")
        self.assertTrue(policy.requires_approval)

    def test_unknown_plugin_tool_is_blocked_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self.make_registry(tmp)
            registry.enable_plugin("mock")
            set_plugin_registry(registry)
            pending = PendingActionManager()
            logger = AuditLogger(Path(tmp) / "audit")
            ran = False

            def runner() -> str:
                nonlocal ran
                ran = True
                return "bad"

            result = guard_tool_call(
                "call_plugin_tool",
                {"plugin_id": "mock", "tool_name": "missing"},
                runner,
                pending,
                logger,
            )
            events = logger.read_recent(5)

        self.assertFalse(ran)
        self.assertIn("Registry disi", result)
        self.assertEqual(events[0]["event_type"], "blocked")


if __name__ == "__main__":
    unittest.main()
