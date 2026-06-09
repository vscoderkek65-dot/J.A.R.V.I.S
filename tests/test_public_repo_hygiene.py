from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicRepoHygieneTests(unittest.TestCase):
    def test_public_repo_docs_exist(self) -> None:
        for relative in (
            "README.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "docs/ROADMAP.md",
            "docs/ARCHITECTURE.md",
            "docs/RELEASE.md",
            ".github/workflows/ci.yml",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).exists(), relative)

    def test_readme_documents_required_user_paths(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for expected in (
            "setup_windows.ps1",
            "run_windows.ps1",
            "test_acceptance.ps1",
            "requirements-voice.txt",
            "https://api.openai.com/v1",
            "ChatGPT Plus/Business",
        ):
            self.assertIn(expected, text)

    def test_runtime_secret_files_are_not_tracked(self) -> None:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = set(result.stdout.splitlines())
        forbidden = {
            "config/api_keys.json",
            "memory/memory.sqlite3",
            "memory/tasks.sqlite3",
            "memory/plugins/plugin_state.json",
        }
        self.assertTrue(forbidden.isdisjoint(tracked))

    def test_acceptance_gate_has_secret_scan(self) -> None:
        script = (ROOT / "test_acceptance.ps1").read_text(encoding="utf-8")
        self.assertIn("Secret scan", script)
        self.assertIn("openai_like_key", script)
        self.assertIn("tavily_key", script)

    def test_pyaudio_is_optional(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        voice_requirements = (ROOT / "requirements-voice.txt").read_text(encoding="utf-8")
        setup = (ROOT / "setup_windows.ps1").read_text(encoding="utf-8")

        self.assertNotIn("pyaudio", [line.strip().casefold() for line in requirements])
        self.assertIn("pyaudio", voice_requirements.casefold())
        self.assertIn("requirements-voice.txt", setup)
        self.assertIn("bloklayici degil", setup)


if __name__ == "__main__":
    unittest.main()
