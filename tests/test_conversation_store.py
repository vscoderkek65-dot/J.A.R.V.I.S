from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from actions.local_assistant import parse_local_tool_intent
from memory.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_conversation_messages_persist_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conversations.sqlite3"
            store = ConversationStore(path)
            conversation = store.create()
            store.add_message(conversation["id"], "user", "Ahmet Kaya sarkilarindan birini ac")
            store.add_message(conversation["id"], "assistant", "YouTube aramasi acildi.")

            messages = ConversationStore(path).messages(conversation["id"])
            self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
            self.assertIn("Ahmet Kaya", ConversationStore(path).list()[0]["title"])

    def test_reference_command_uses_previous_media_request(self):
        context = [
            {"role": "user", "content": "Ahmet Kaya sarkilarindan birini ac"},
            {"role": "assistant", "content": "Spotify acilamadi."},
        ]
        intent = parse_local_tool_intent("youtube dan ac", context)
        self.assertEqual(intent.tool_name, "play_media")
        self.assertEqual(intent.args["provider"], "youtube")
        self.assertIn("Ahmet Kaya", intent.args["query"])


if __name__ == "__main__":
    unittest.main()
