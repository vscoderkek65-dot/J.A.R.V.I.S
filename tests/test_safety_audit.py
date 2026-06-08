from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions.audit import AuditLogger, audit_status  # noqa: E402
from actions.plugin_safety import check_plugin_permission  # noqa: E402
from actions.safety import (  # noqa: E402
    EXTERNAL,
    SEND,
    PendingActionManager,
    classify_tool,
    guard_tool_call,
    tool_risk_status,
)


def declared_tool_names() -> list[str]:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS" for target in node.targets):
            continue
        names: list[str] = []
        for item in getattr(node.value, "elts", []):
            if not isinstance(item, ast.Dict):
                continue
            for key, value in zip(item.keys, item.values):
                if isinstance(key, ast.Constant) and key.value == "name" and isinstance(value, ast.Constant):
                    names.append(str(value.value))
        return names
    return []


class SafetyAuditTests(unittest.TestCase):
    def test_all_declared_tools_have_explicit_risk_policy(self) -> None:
        missing = [name for name in declared_tool_names() if classify_tool(name, {}).unknown]

        self.assertEqual(missing, [])

    def test_whatsapp_send_now_changes_risk_policy(self) -> None:
        draft = classify_tool("send_whatsapp_message", {"send_now": False})
        send = classify_tool("send_whatsapp_message", {"send_now": True})

        self.assertEqual(draft.risk_class, EXTERNAL)
        self.assertFalse(draft.requires_approval)
        self.assertEqual(send.risk_class, SEND)
        self.assertTrue(send.requires_approval)

    def test_unknown_tool_is_blocked_and_audited_without_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            pending = PendingActionManager()
            ran = False

            def runner() -> str:
                nonlocal ran
                ran = True
                return "should not run"

            result = guard_tool_call(
                "mystery_tool",
                {"api_key": "fake-secret-value-for-test"},
                runner,
                pending,
                logger,
                run_id="run-unknown",
            )
            events = logger.read_recent(10)

        self.assertIn("Registry disi arac engellendi", result)
        self.assertFalse(ran)
        self.assertFalse(pending.has_pending())
        self.assertEqual(events[0]["event_type"], "blocked")
        self.assertEqual(events[0]["args"]["api_key"], "***REDACTED***")

    def test_read_tool_runs_without_pending_approval(self) -> None:
        pending = PendingActionManager()
        result = guard_tool_call("sys_info", {"query": "time"}, lambda: "ok", pending)

        self.assertEqual(result, "ok")
        self.assertFalse(pending.has_pending())

    def test_risky_tool_requests_approval_then_logs_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            pending = PendingActionManager()
            calls: list[str] = []

            result = guard_tool_call(
                "write_text_file",
                {"path": "notes.txt", "content": "hello"},
                lambda: calls.append("ran") or "written",
                pending,
                logger,
                run_id="run-write",
            )
            approved = pending.approve()
            events = logger.read_recent(10)

        event_types = {event["event_type"] for event in events}
        self.assertIn("Onay gerekiyor", result)
        self.assertIn("[write/write_text_file]", result)
        self.assertEqual(approved, "written")
        self.assertEqual(calls, ["ran"])
        self.assertTrue({"requested", "approved", "executed"}.issubset(event_types))

    def test_high_risk_tools_wait_for_approval_without_running(self) -> None:
        risky_cases = [
            ("delete_file", {"path": "old.txt"}),
            ("move_file", {"source_path": "a.txt", "destination_path": "b.txt"}),
            ("shell_run", {"command": "dir"}),
            ("send_hotkey_safe", {"hotkey": "ctrl+c"}),
            ("browser_submit", {"selector_or_text": "Gonder"}),
            ("send_whatsapp_message", {"recipient_name": "Test", "message": "Merhaba", "send_now": True}),
        ]

        for tool_name, args in risky_cases:
            with self.subTest(tool_name=tool_name):
                pending = PendingActionManager()
                ran = False

                def runner() -> str:
                    nonlocal ran
                    ran = True
                    return "ran"

                result = guard_tool_call(tool_name, args, runner, pending)

                self.assertIn("Onay gerekiyor", result)
                self.assertTrue(pending.has_pending())
                self.assertFalse(ran)

    def test_cancelled_pending_action_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            pending = PendingActionManager()
            guard_tool_call("delete_file", {"path": "old.txt"}, lambda: "deleted", pending, logger)

            result = pending.cancel()
            events = logger.read_recent(10)

        self.assertIn("Iptal edildi", result)
        self.assertIn("cancelled", {event["event_type"] for event in events})

    def test_failed_approved_action_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            pending = PendingActionManager()

            def runner() -> str:
                raise RuntimeError("boom")

            guard_tool_call("shell_run", {"command": "dir"}, runner, pending, logger)
            result = pending.approve()
            events = logger.read_recent(10)

        self.assertIn("Onayli islem calistirilamadi", result)
        self.assertIn("failed", {event["event_type"] for event in events})

    def test_audit_sanitizes_sensitive_values_and_status_summarizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            logger.log(
                "requested",
                tool_name="research_web",
                risk_class="external",
                args={"ninerouter_api_key": "sk-abcdef1234567890"},
                summary="secret sk-abcdef1234567890",
                result="bearer fake",
            )
            raw = next(Path(tmp).glob("security-audit-*.jsonl")).read_text(encoding="utf-8")
            event = json.loads(raw.splitlines()[0])
            status = audit_status(1, logger)

        self.assertNotIn("sk-abcdef1234567890", raw)
        self.assertNotIn("bearer fake", raw.casefold())
        self.assertEqual(event["args"]["ninerouter_api_key"], "***REDACTED***")
        self.assertIn("Son audit olaylari", status)

    def test_tool_risk_status_and_plugin_allowlist_blocks(self) -> None:
        self.assertIn("shell_run: risk=execute", tool_risk_status("shell_run"))
        with tempfile.TemporaryDirectory() as tmp:
            logger = AuditLogger(tmp)
            permission = check_plugin_permission("unknown_skill", kind="skill", audit_logger=logger)
            events = logger.read_recent(10)

        self.assertFalse(permission.allowed)
        self.assertEqual(events[0]["event_type"], "blocked")
        self.assertIn("allowlist", permission.reason)


if __name__ == "__main__":
    unittest.main()
