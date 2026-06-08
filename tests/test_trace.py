from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.agent_runtime import AgentRuntime  # noqa: E402
from core.trace import TraceManager, extract_research_details  # noqa: E402


RESEARCH_OUTPUT = """Kisa cevap:
Iki kaynak okundu.

Kaynaklar:
[1] Test Haber
Kaynak: https://example.com/news

Okunamayan kaynaklar:
- 1. Kapali site: https://blocked.example (HTTP 403)

Arama notlari:
- Denenen saglayicilar: Tavily ilgili sonuc bulamadi | Bing sonuc verdi
- Reddedilen alakasiz kaynaklar: Web reddedildi: ilgisiz haber (zorunlu terimler eksik; eslesen=-)
"""


class TraceTests(unittest.TestCase):
    def test_extract_research_details_collects_sources_notes_and_rejections(self) -> None:
        details = extract_research_details(RESEARCH_OUTPUT)

        self.assertIn("https://example.com/news", details["sources"])
        self.assertTrue(any("Denenen saglayicilar" in note for note in details["notes"]))
        self.assertTrue(any("Reddedilen" in item or "reddedildi" in item.casefold() for item in details["rejected"]))
        self.assertTrue(any("Kapali site" in item for item in details["unreadable"]))

    def test_trace_manager_writes_jsonl_and_explains_last_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceManager(tmp)
            run_id = trace.start_run("Vanspor haberlerini oku")
            trace.log_tool(
                run_id=run_id,
                tool_name="research_web",
                specialist="ResearchAgent",
                args={"query": "Vanspor haberleri"},
                output=RESEARCH_OUTPUT,
                status="completed",
                evaluation="Kaynakli arastirma tamamlandi.",
                elapsed_ms=42,
            )

            files = list(Path(tmp).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(row["event"] == "tool_call" for row in rows))
            self.assertTrue(any(row["event"] == "research_summary" for row in rows))

            explanation = trace.explain_last_research()
            self.assertIn(run_id, explanation)
            self.assertIn("https://example.com/news", explanation)
            self.assertIn("Reddedilen", explanation)

    def test_agent_runtime_logs_tool_call_to_trace(self) -> None:
        async def executor(name: str, args: dict) -> str:
            return RESEARCH_OUTPUT

        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceManager(tmp)
            runtime = AgentRuntime([], trace_manager=trace)
            run_id = runtime.start_run("test arastir")

            result = asyncio.run(runtime.execute_tool("research_web", {"query": "test"}, executor))

            self.assertIn("Kisa cevap", result)
            rows = []
            for file in Path(tmp).glob("*.jsonl"):
                rows.extend(json.loads(line) for line in file.read_text(encoding="utf-8").splitlines())
            tool_rows = [row for row in rows if row["event"] == "tool_call"]
            self.assertEqual(tool_rows[0]["run_id"], run_id)
            self.assertEqual(tool_rows[0]["specialist"], "ResearchAgent")
            self.assertIn("https://example.com/news", tool_rows[0]["source_urls"])


if __name__ == "__main__":
    unittest.main()
