from __future__ import annotations

import unittest

from core.transcript_guard import merge_streaming_text, sanitize_streaming_transcript


class TranscriptGuardTests(unittest.TestCase):
    def test_merges_cumulative_streaming_chunks(self):
        text = merge_streaming_text("", "Merhaba")
        text = merge_streaming_text(text, "Merhaba, size")
        text = merge_streaming_text(text, "size nasil yardimci olabilirim?")
        self.assertEqual(text, "Merhaba, size nasil yardimci olabilirim?")

    def test_drops_pathological_repetition(self):
        clean, reason = sanitize_streaming_transcript("ret" * 120)
        self.assertEqual(clean, "")
        self.assertTrue(reason)

    def test_keeps_normal_turkish_response(self):
        clean, reason = sanitize_streaming_transcript(
            "Merhaba. Uygulamayi acabilirim ancak riskli islemler icin onay istemem gerekir."
        )
        self.assertTrue(clean.startswith("Merhaba"))
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
