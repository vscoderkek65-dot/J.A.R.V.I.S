from __future__ import annotations

import unittest

from actions.local_assistant import parse_local_tool_intent


class LocalAssistantIntentTests(unittest.TestCase):
    def test_routes_music_request_to_media_tool(self):
        intent = parse_local_tool_intent("bana Ahmet Kaya sarkilarindan birini ac")
        self.assertEqual(intent.tool_name, "play_media")
        self.assertIn("Ahmet Kaya", intent.args["query"])

    def test_routes_application_request_to_open_app(self):
        intent = parse_local_tool_intent("bana Antigravity uygulamasini acar misin")
        self.assertEqual(intent.tool_name, "open_app")
        self.assertEqual(intent.args["app_name"], "Antigravity")

    def test_routes_windows_folder_request_to_list_folder(self):
        intent = parse_local_tool_intent(r"D:\vscode\JARVIS klasorune bakabilir misin")
        self.assertEqual(intent.tool_name, "list_folder")
        self.assertEqual(intent.args["path"], r"D:\vscode\JARVIS")


if __name__ == "__main__":
    unittest.main()
