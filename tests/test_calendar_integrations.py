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
from actions import calendar, reminders, whatsapp  # noqa: E402
import actions.calendar_integrations as ci  # noqa: E402
from actions.safety import classify_tool, guard_tool_call, PendingActionManager  # noqa: E402


class FakeCall:
    def __init__(self, payload=None, callback=None):
        self.payload = payload if payload is not None else {}
        self.callback = callback

    def execute(self):
        if self.callback:
            self.callback()
        return self.payload


class FakeGoogleCalendarService:
    def __init__(self):
        self.deleted: list[tuple[str, str]] = []

    def calendarList(self):
        return self

    def events(self):
        return self

    def list(self, **kwargs):
        if "calendarId" in kwargs:
            return FakeCall(
                {
                    "items": [
                        {
                            "id": "g-event-1",
                            "summary": "Google Toplanti",
                            "start": {"dateTime": "2026-06-08T09:00:00+03:00"},
                            "end": {"dateTime": "2026-06-08T10:00:00+03:00"},
                            "location": "Ofis",
                        }
                    ]
                }
            )
        return FakeCall({"items": [{"id": "primary", "summary": "Primary"}]})

    def insert(self, **_kwargs):
        return FakeCall(
            {
                "id": "g-event-new",
                "summary": "Yeni Google",
                "start": {"dateTime": "2026-06-08T11:00:00+03:00"},
                "end": {"dateTime": "2026-06-08T12:00:00+03:00"},
            }
        )

    def delete(self, calendarId, eventId):
        return FakeCall({}, lambda: self.deleted.append((calendarId, eventId)))


class FakeGoogleTasksService:
    def __init__(self):
        self.patched: list[tuple[str, str, dict]] = []

    def tasklists(self):
        return self

    def tasks(self):
        return self

    def list(self, **kwargs):
        if "tasklist" in kwargs:
            return FakeCall(
                {
                    "items": [
                        {
                            "id": "g-task-1",
                            "title": "Google Hatirlat",
                            "due": "2026-06-08T12:00:00Z",
                            "status": "needsAction",
                        }
                    ]
                }
            )
        return FakeCall({"items": [{"id": "tasks-primary", "title": "My Tasks"}]})

    def insert(self, **_kwargs):
        return FakeCall({"id": "g-task-new", "title": "Yeni Gorev", "due": "2026-06-08T12:00:00Z"})

    def patch(self, tasklist, task, body):
        return FakeCall({}, lambda: self.patched.append((tasklist, task, body)))

    def delete(self, **_kwargs):
        return FakeCall({})


class CalendarIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_config_path = app_config.CONFIG_PATH
        self.old_config_dir = app_config.CONFIG_DIR
        self.old_oauth_dir = ci.OAUTH_DIR
        self.old_outlook_cache = ci.OUTLOOK_CACHE_PATH
        self.old_outlook_flow = ci.OUTLOOK_FLOW_PATH
        self.old_google_token = ci.GOOGLE_TOKEN_PATH
        self.old_calendar_windows = calendar.IS_WINDOWS
        self.old_reminder_windows = reminders.IS_WINDOWS

        app_config.CONFIG_DIR = self.tmp_path / "config"
        app_config.CONFIG_PATH = app_config.CONFIG_DIR / "api_keys.json"
        app_config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        app_config.CONFIG_PATH.write_text(json.dumps({}), encoding="utf-8")
        ci.OAUTH_DIR = self.tmp_path / "oauth"
        ci.OUTLOOK_CACHE_PATH = ci.OAUTH_DIR / "outlook_msal_cache.json"
        ci.OUTLOOK_FLOW_PATH = ci.OAUTH_DIR / "outlook_device_flow.json"
        ci.GOOGLE_TOKEN_PATH = ci.OAUTH_DIR / "google_calendar_token.json"
        calendar.IS_WINDOWS = True
        reminders.IS_WINDOWS = True

    def tearDown(self) -> None:
        app_config.CONFIG_PATH = self.old_config_path
        app_config.CONFIG_DIR = self.old_config_dir
        ci.OAUTH_DIR = self.old_oauth_dir
        ci.OUTLOOK_CACHE_PATH = self.old_outlook_cache
        ci.OUTLOOK_FLOW_PATH = self.old_outlook_flow
        ci.GOOGLE_TOKEN_PATH = self.old_google_token
        calendar.IS_WINDOWS = self.old_calendar_windows
        reminders.IS_WINDOWS = self.old_reminder_windows
        self.tmp.cleanup()

    def write_config(self, **updates) -> None:
        data = dict(app_config.DEFAULT_CONFIG)
        data.update(updates)
        app_config.CONFIG_PATH.write_text(json.dumps(data), encoding="utf-8")

    def test_old_config_defaults_to_outlook_and_auth_missing_is_clear(self) -> None:
        self.write_config()

        self.assertEqual(ci.selected_calendar_provider(), "outlook")
        self.assertIn("Outlook OAuth client ID eksik", calendar.get_calendar_events("today"))
        self.assertIn("Outlook", ci.calendar_auth_status())

    def test_outlook_calendar_and_todo_flow_with_mock_graph(self) -> None:
        self.write_config(calendar_provider="outlook", outlook_client_id="client")
        old_token = ci._outlook_get_token
        old_graph = ci._graph_request
        deleted: list[str] = []
        patched: list[dict] = []

        def fake_graph(method, path, _token, *, params=None, json_body=None):
            if path == "/me/calendarView":
                return {
                    "value": [
                        {
                            "id": "e1",
                            "subject": "Outlook Toplanti",
                            "start": {"dateTime": "2026-06-08T09:00:00"},
                            "end": {"dateTime": "2026-06-08T10:00:00"},
                            "isAllDay": False,
                        }
                    ]
                }
            if method == "POST" and path == "/me/events":
                return {
                    "id": "e2",
                    "subject": json_body["subject"],
                    "start": {"dateTime": json_body["start"]["dateTime"]},
                    "end": {"dateTime": json_body["end"]["dateTime"]},
                    "isAllDay": False,
                }
            if method == "DELETE" and path == "/me/events/e1":
                deleted.append(path)
                return {}
            if path == "/me/todo/lists":
                return {"value": [{"id": "list1", "displayName": "Tasks"}]}
            if path == "/me/todo/lists/list1/tasks" and method == "GET":
                return {
                    "value": [
                        {
                            "id": "t1",
                            "title": "Sut al",
                            "dueDateTime": {"dateTime": "2026-06-08T12:00:00"},
                            "status": "notStarted",
                        }
                    ]
                }
            if path == "/me/todo/lists/list1/tasks" and method == "POST":
                return {"id": "t2", "title": json_body["title"], "dueDateTime": json_body.get("dueDateTime", {})}
            if method == "PATCH":
                patched.append(json_body)
                return {}
            return {"value": []}

        ci._outlook_get_token = lambda: "token"
        ci._graph_request = fake_graph
        try:
            self.assertIn("Outlook Toplanti", ci.get_calendar_events_windows("today", 3))
            self.assertIn("Takvime eklendi", ci.add_calendar_event_windows("Yeni", "2026-06-08T11:00"))
            self.assertIn("Takvimden silindi", ci.delete_calendar_event_windows("Outlook Toplanti"))
            self.assertEqual(deleted, ["/me/events/e1"])
            self.assertIn("Sut al", ci.get_reminders_windows("all", 5))
            self.assertIn("Animsatici eklendi", ci.add_reminder_windows("Yeni Gorev", "2026-06-08T12:00"))
            self.assertIn("Animsatici tamamlandi", ci.complete_reminder(title="Sut al"))
            self.assertEqual(patched, [{"status": "completed"}])
        finally:
            ci._outlook_get_token = old_token
            ci._graph_request = old_graph

    def test_google_calendar_and_tasks_flow_with_mock_services(self) -> None:
        self.write_config(calendar_provider="google", google_oauth_client_id="gid", google_oauth_client_secret="secret")
        calendar_service = FakeGoogleCalendarService()
        tasks_service = FakeGoogleTasksService()
        old_service = ci._google_get_service

        def fake_service(name, _version):
            return calendar_service if name == "calendar" else tasks_service

        ci._google_get_service = fake_service
        try:
            self.assertIn("Google Toplanti", ci.get_calendar_events_windows("today", 3))
            self.assertIn("Takvime eklendi", ci.add_calendar_event_windows("Yeni Google", "2026-06-08T11:00"))
            self.assertIn("Takvimden silindi", ci.delete_calendar_event_windows("Google Toplanti"))
            self.assertEqual(calendar_service.deleted, [("primary", "g-event-1")])
            self.assertIn("Google Hatirlat", ci.get_reminders_windows("all", 5))
            self.assertIn("Animsatici eklendi", ci.add_reminder_windows("Yeni Gorev", "2026-06-08T12:00"))
            self.assertIn("Animsatici tamamlandi", ci.complete_reminder(title="Google Hatirlat"))
            self.assertEqual(tasks_service.patched, [("tasks-primary", "g-task-1", {"status": "completed"})])
        finally:
            ci._google_get_service = old_service

    def test_new_risky_tools_are_guarded_by_safety(self) -> None:
        for tool in ("complete_reminder", "delete_reminder", "import_phone_book_from_vcf", "disconnect_calendar_provider"):
            policy = classify_tool(tool, {})
            self.assertTrue(policy.requires_approval, tool)
            result = guard_tool_call(tool, {}, lambda: "done", PendingActionManager())
            self.assertIn("Onay gerekiyor", result)


class WhatsAppContactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_phonebook = whatsapp.PHONEBOOK_FILE
        whatsapp.PHONEBOOK_FILE = Path(self.tmp.name) / "phone_book.json"

    def tearDown(self) -> None:
        whatsapp.PHONEBOOK_FILE = self.old_phonebook
        self.tmp.cleanup()

    def test_find_list_and_import_vcf_contacts(self) -> None:
        whatsapp.PHONEBOOK_FILE.write_text(
            json.dumps(
                {
                    "ali_test": {
                        "display_name": "Ali Test",
                        "value": "+905551112233",
                        "aliases": ["alis"],
                        "source": "test",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertIn("Ali Test", whatsapp.find_whatsapp_contact("alis"))
        self.assertIn("Ali Test", whatsapp.list_whatsapp_contacts())

        vcf = Path(self.tmp.name) / "contacts.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Veli Test\nTEL:+905559998877\nEND:VCARD\n", encoding="utf-8")
        result = whatsapp.import_phone_book_from_vcf(str(vcf))

        self.assertIn("1 rehber", result)
        self.assertIn("Veli Test", whatsapp.find_whatsapp_contact("Veli"))


if __name__ == "__main__":
    unittest.main()
