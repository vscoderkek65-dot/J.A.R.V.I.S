from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AcceptanceGateTests(unittest.TestCase):
    def test_acceptance_script_contains_required_quality_gate_commands(self) -> None:
        script = (ROOT / "test_acceptance.ps1").read_text(encoding="utf-8")

        self.assertIn("-m compileall -q .", script)
        self.assertIn("-m unittest discover -s tests -v", script)
        self.assertIn("PASSED", script)  # "Acceptance gate PASSED"

    def test_acceptance_script_lists_manual_windows_smoke_items(self) -> None:
        script = (ROOT / "test_acceptance.ps1").read_text(encoding="utf-8").casefold()

        for expected in (
            "run_windows.ps1",
            "smoke",
            "live",
        ):
            self.assertIn(expected, script)

    def test_windows_run_entrypoint_uses_venv_and_main_py(self) -> None:
        script = (ROOT / "run_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("venv\\Scripts\\python.exe", script)
        self.assertIn("main.py", script)
        self.assertIn("setup_windows.ps1", script)

    def test_windows_run_entrypoint_supports_smoke_flags(self) -> None:
        script = (ROOT / "run_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Smoke", script)
        self.assertIn("--smoke", script)
        self.assertIn("--smoke-timeout", script)
        self.assertIn("--smoke-app", script)

    def test_acceptance_script_can_optionally_run_windows_smoke(self) -> None:
        script = (ROOT / "test_acceptance.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Smoke", script)
        self.assertIn("run_windows.ps1", script)
        self.assertIn("-SmokeTimeoutSeconds", script)

    def test_live_exposes_smoke_cli_arguments(self) -> None:
        text = (ROOT / "core" / "jarvis_live.py").read_text(encoding="utf-8")

        self.assertIn("--smoke", text)
        self.assertIn("--smoke-timeout", text)
        self.assertIn("--smoke-app", text)


if __name__ == "__main__":
    unittest.main()
