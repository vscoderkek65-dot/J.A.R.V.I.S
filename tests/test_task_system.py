from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions import task_system as ts  # noqa: E402


def research_result(answer: str, url: str = "https://example.com/news") -> str:
    return (
        "Kisa cevap:\n"
        f"{answer}\n\n"
        "Detaylar:\n"
        f"- {answer}\n\n"
        "Kaynaklar:\n"
        "[1] Test\n"
        f"Kaynak: {url}\n\n"
        "Arama notlari:\n"
        "- mock"
    )


class TaskSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ts.TaskStore(Path(self.tmp.name) / "tasks.sqlite3")
        ts.set_task_store(self.store)

    def tearDown(self) -> None:
        ts.set_task_store(None)
        self.tmp.cleanup()

    def test_db_schema_created_on_first_open(self) -> None:
        self.assertTrue((Path(self.tmp.name) / "tasks.sqlite3").exists())
        self.assertEqual(self.store.list_tasks("active"), [])

    def test_create_followup_task_sets_pending_and_next_run(self) -> None:
        result = ts.create_followup_task(
            title="Vanspor haber takibi",
            task_type="web_watch",
            query="Vanspor haberleri son dakika",
            schedule_kind="interval",
            interval_minutes=30,
        )

        self.assertIn("Takip gorevi olusturuldu", result)
        task = self.store.list_tasks("active")[0]
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["interval_minutes"], 30)
        self.assertTrue(task["next_run_at"])

    def test_due_periodic_task_baselines_then_notifies_on_change(self) -> None:
        ts.create_followup_task("Ergene haber takibi", "web_watch", "Ergene haberleri", schedule_kind="interval", interval_minutes=15)
        task = self.store.list_tasks("active")[0]
        notifications: list[tuple[str, str]] = []
        answers = [research_result("Ilk durum"), research_result("Yeni haber geldi", "https://example.com/new")]

        scheduler = ts.TaskScheduler(
            store=self.store,
            notify_callback=lambda title, body: notifications.append((title, body)),
            interval_seconds=60,
            research_func=lambda *_args, **_kwargs: answers.pop(0),
        )

        first = scheduler.run_due_once()
        self.assertEqual(len(first), 1)
        self.assertFalse(first[0].notified)
        self.assertEqual(notifications, [])

        current = self.store.get_task(task["id"])
        self.assertEqual(current["status"], "pending")
        self.assertTrue(current["last_result_hash"])
        self.store.update_task(task["id"], next_run_at=(dt.datetime.now().astimezone() - dt.timedelta(minutes=1)).isoformat(timespec="seconds"))

        second = scheduler.run_due_once()
        self.assertEqual(len(second), 1)
        self.assertTrue(second[0].notified)
        self.assertEqual(len(notifications), 1)
        self.assertIn("Yeni haber", notifications[0][1])

    def test_periodic_task_suppresses_duplicate_hash(self) -> None:
        ts.create_followup_task("Sabit haber takibi", "web_watch", "Sabit haberler", schedule_kind="interval", interval_minutes=15)
        task = self.store.list_tasks("active")[0]
        notifications: list[tuple[str, str]] = []
        value = research_result("Ayni sonuc")
        scheduler = ts.TaskScheduler(
            store=self.store,
            notify_callback=lambda title, body: notifications.append((title, body)),
            research_func=lambda *_args, **_kwargs: value,
        )

        scheduler.run_due_once()
        self.store.update_task(task["id"], next_run_at=(dt.datetime.now().astimezone() - dt.timedelta(minutes=1)).isoformat(timespec="seconds"))
        second = scheduler.run_due_once()

        self.assertFalse(second[0].notified)
        self.assertEqual(notifications, [])

    def test_one_shot_task_becomes_done(self) -> None:
        run_at = (dt.datetime.now().astimezone() - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
        ts.create_followup_task("Yarin kontrol", "one_shot_check", "test konu", schedule_kind="once", run_at=run_at)
        scheduler = ts.TaskScheduler(store=self.store, research_func=lambda *_args, **_kwargs: research_result("Kontrol sonucu"))

        scheduler.run_due_once()

        task = self.store.list_tasks("done", 10)[0]
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["next_run_at"], "")

    def test_cancel_task_marks_cancelled(self) -> None:
        ts.create_followup_task("Iptal testi", "web_watch", "test", schedule_kind="interval")
        task_id = self.store.list_tasks("active")[0]["id"]

        result = ts.cancel_task(task_id)

        self.assertIn("Gorev iptal edildi", result)
        self.assertEqual(self.store.get_task(task_id)["status"], "cancelled")

    def test_startup_status_reports_without_mutating(self) -> None:
        status = ts.startup_tracking_status()

        self.assertIn("Windows baslangic takibi", status)

    def test_main_dispatch_keeps_startup_changes_pending(self) -> None:
        main_text = (ROOT / "main.py").read_text(encoding="utf-8")
        enable_block = main_text.split('elif name == "enable_startup_tracking":', 1)[1].split(
            'elif name == "disable_startup_tracking":', 1
        )[0]
        disable_block = main_text.split('elif name == "disable_startup_tracking":', 1)[1].split(
            'elif name == "open_app":', 1
        )[0]

        self.assertIn('elif name == "enable_startup_tracking"', main_text)
        self.assertIn('elif name == "disable_startup_tracking"', main_text)
        self.assertIn("self._guarded_tool_action(", enable_block)
        self.assertIn("enable_startup_tracking", enable_block)
        self.assertIn("self._guarded_tool_action(", disable_block)
        self.assertIn("disable_startup_tracking", disable_block)


if __name__ == "__main__":
    unittest.main()
