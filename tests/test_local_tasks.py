from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions import task_system as ts  # noqa: E402
from actions.local_tasks import handle_local_task_command  # noqa: E402


class FakeTrace:
    last_research = {
        "query": "Tekirdag Ergene haberleri son dakika",
        "summary": "Kisa cevap: mock",
    }


class LocalTaskParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ts.TaskStore(Path(self.tmp.name) / "tasks.sqlite3")
        ts.set_task_store(self.store)

    def tearDown(self) -> None:
        ts.set_task_store(None)
        self.tmp.cleanup()

    def test_news_watch_command_creates_web_watch_task(self) -> None:
        result = handle_local_task_command("Vanspor haber çıkarsa bildir")

        self.assertIsNotNone(result)
        self.assertIn("Takip gorevi olusturuldu", result or "")
        task = self.store.list_tasks("active")[0]
        self.assertEqual(task["task_type"], "web_watch")
        self.assertIn("Vanspor", task["query"])
        self.assertIn("haberleri son dakika", task["query"])

    def test_follow_this_uses_last_research_query(self) -> None:
        result = handle_local_task_command("bunu takip et", FakeTrace())

        self.assertIsNotNone(result)
        task = self.store.list_tasks("active")[0]
        self.assertEqual(task["query"], "Tekirdag Ergene haberleri son dakika")

    def test_tomorrow_check_creates_one_shot_task(self) -> None:
        result = handle_local_task_command("yarın bunu kontrol et", FakeTrace())

        self.assertIsNotNone(result)
        task = self.store.list_tasks("active")[0]
        self.assertEqual(task["task_type"], "one_shot_check")
        self.assertEqual(task["schedule_kind"], "once")
        self.assertTrue(task["run_at"])

    def test_list_and_cancel_commands(self) -> None:
        handle_local_task_command("Vanspor haber çıkarsa bildir")
        task_id = self.store.list_tasks("active")[0]["id"]

        listed = handle_local_task_command("takipleri listele")
        cancelled = handle_local_task_command(f"takibi iptal et {task_id}")

        self.assertIn(f"#{task_id}", listed or "")
        self.assertIn("Gorev iptal edildi", cancelled or "")
        self.assertEqual(self.store.get_task(task_id)["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
