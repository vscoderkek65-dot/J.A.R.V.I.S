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
from actions.local_memory import handle_local_memory_command  # noqa: E402
import memory.memory_manager as mm  # noqa: E402
from memory import memory_store as ms  # noqa: E402


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_memory_file = mm.MEMORY_FILE
        self.old_task_store = ts.get_task_store() if ts._store is not None else None
        self.store = ms.MemoryStore(self.tmp_path / "memory.sqlite3")
        ms.set_memory_store(self.store)
        mm.MEMORY_FILE = self.tmp_path / "memory.json"

    def tearDown(self) -> None:
        ms.set_memory_store(None)
        ts.set_task_store(self.old_task_store)
        mm.MEMORY_FILE = self.old_memory_file
        self.tmp.cleanup()

    def test_schema_and_fts_created_on_first_open(self) -> None:
        status = self.store.status()

        self.assertEqual(status["total"], 0)
        self.assertTrue((self.tmp_path / "memory.sqlite3").exists())

    def test_update_memory_preserves_json_and_indexes_sqlite(self) -> None:
        mm.update_memory({"preferences": {"reply_style": {"value": "Kisa cevap ver"}}})

        self.assertEqual(mm.load_memory()["preferences"]["reply_style"]["value"], "Kisa cevap ver")
        result = mm.search_memory("kısa cevap", "", 5)
        self.assertIn("reply_style", result)

    def test_delete_memory_removes_json_and_sqlite_index(self) -> None:
        mm.update_memory({"preferences": {"reply_style": {"value": "Kisa cevap ver"}}})

        result = mm.delete_memory("preferences", "reply_style")

        self.assertIn("preferences/reply_style", result)
        self.assertEqual(mm.load_memory(), {})
        self.assertIn("bulunamadi", mm.search_memory("kisa cevap", "", 5).casefold())

    def test_search_memory_matches_turkish_diacritics(self) -> None:
        ms.save_sqlite_memory("decision", "Hafıza kararı", "Bu projede SQLite hafıza kullanılacak.", tags="karar,sqlite")

        result = mm.search_memory("hafiza sqlite", "", 5)

        self.assertIn("Hafıza kararı", result)

    def test_delete_memory_returns_candidates_for_multiple_matches(self) -> None:
        ms.save_sqlite_memory("decision", "SQLite karari", "SQLite kullanilacak.", source="test", source_id="1")
        ms.save_sqlite_memory("project_note", "SQLite notu", "SQLite notu tutulacak.", source="test", source_id="2")

        result = mm.delete_memory(match_text="sqlite")

        self.assertIn("Birden fazla hafiza kaydi eslesti", result)
        self.assertIn("#1", result)
        self.assertIn("#2", result)

    def test_auto_learning_saves_safe_preference_and_blocks_secrets(self) -> None:
        learned = ms.infer_memory_from_text("Bundan sonra kısa cevap ver", source_id="run-1")
        secret = ms.infer_memory_from_text("Bundan sonra api key sk-1234567890abcdef kullan", source_id="run-2")
        phone = ms.infer_memory_from_text("Bundan sonra telefonum +905551112233", source_id="run-3")

        self.assertTrue(learned["saved"])
        self.assertFalse(secret["saved"])
        self.assertFalse(phone["saved"])
        self.assertIn("kısa cevap", mm.search_memory("kisa cevap", "preference", 5).casefold())

    def test_auto_learning_saves_project_decision(self) -> None:
        learned = ms.infer_memory_from_text("Bu projede kararımız SQLite kullanmak", source_id="run-4")

        self.assertTrue(learned["saved"])
        self.assertIn("SQLite", mm.search_memory("karar sqlite", "decision", 5))

    def test_conversation_summary_is_searchable(self) -> None:
        saved = ms.save_conversation_summary("Faz 7 nedir?", "Gercek hafiza sistemi eklenecek.", "run-5")

        self.assertIn("id", saved)
        self.assertIn("Gercek hafiza", mm.search_memory("faz 7 hafiza", "conversation_summary", 5))

    def test_task_system_writes_task_summary_memory(self) -> None:
        task_store = ts.TaskStore(self.tmp_path / "tasks.sqlite3")
        ts.set_task_store(task_store)
        run_at = (dt.datetime.now().astimezone() - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
        ts.create_followup_task("Yarin kontrol", "one_shot_check", "test konu", schedule_kind="once", run_at=run_at)

        result = mm.search_memory("Yarin kontrol", "task_summary", 5)

        self.assertIn("Gorev olusturuldu", result)

    def test_local_memory_forget_this_deletes_single_last_result(self) -> None:
        ms.save_sqlite_memory("decision", "Silinecek karar", "Bu karar silinecek.", source="test", source_id="forget")

        found = handle_local_memory_command("hafizada ara silinecek karar")
        deleted = handle_local_memory_command("bunu unut")

        self.assertIn("Silinecek karar", found or "")
        self.assertIn("silindi", deleted or "")
        self.assertIn("bulunamadi", mm.search_memory("silinecek karar", "", 5).casefold())


if __name__ == "__main__":
    unittest.main()
