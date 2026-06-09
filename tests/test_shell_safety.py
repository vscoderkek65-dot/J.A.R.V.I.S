from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions.shell import shell_run  # noqa: E402


class ShellSafetyTests(unittest.TestCase):
    def test_shell_run_allows_simple_read_only_commands(self) -> None:
        self.assertIn("hello", shell_run("echo hello"))
        self.assertIn("tests", shell_run("dir .").casefold())
        self.assertIn("required packages", shell_run("type requirements.txt").casefold())

    def test_shell_run_blocks_mutation_and_shell_operators(self) -> None:
        blocked = [
            "del requirements.txt",
            "Remove-Item requirements.txt",
            "dir . && del requirements.txt",
            "git commit -m test",
            "python -c \"print(1)\"",
        ]
        for command in blocked:
            with self.subTest(command=command):
                self.assertIn("Güvenlik", shell_run(command))

    def test_shell_run_rejects_paths_outside_workspace(self) -> None:
        result = shell_run("type ..\\outside.txt")
        self.assertIn("workspace", result.casefold())

    def test_shell_module_does_not_use_subprocess_shell_true(self) -> None:
        source = (ROOT / "actions" / "shell.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)


if __name__ == "__main__":
    unittest.main()
