from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import core.agent_runtime as ar  # noqa: E402
from core.agent_runtime import AgentRuntime  # noqa: E402
from core.llm_client import OpenAICompatibleConfig  # noqa: E402


class AgentRuntimeTests(unittest.TestCase):
    def test_plan_routes_research_prompt_to_research_agent(self) -> None:
        runtime = AgentRuntime([])
        plan = runtime.plan_task("Tekirdag Ergene haberlerini arastir")

        self.assertIn("ResearchAgent", plan.specialists)
        self.assertIn("arastirma", plan.strategy)

    def test_execute_tool_records_specialist_and_evaluation(self) -> None:
        async def executor(name: str, args: dict) -> str:
            return "Kisa cevap:\nTamam.\n\nKaynaklar:\n[1] Test\nKaynak: https://example.com"

        runtime = AgentRuntime([])
        result = asyncio.run(runtime.execute_tool("research_web", {"query": "test"}, executor))

        self.assertIn("Kisa cevap", result)
        self.assertEqual(runtime.history[-1].specialist, "ResearchAgent")
        self.assertEqual(runtime.history[-1].status, "completed")

    def test_execute_tool_marks_pending_actions_as_waiting_approval(self) -> None:
        async def executor(name: str, args: dict) -> str:
            return "Onay bekleniyor: Dosyaya yaz: test.txt. Onayla veya iptal de."

        runtime = AgentRuntime([])
        asyncio.run(runtime.execute_tool("write_text_file", {"path": "test.txt"}, executor))

        self.assertEqual(runtime.history[-1].specialist, "FileAgent")
        self.assertEqual(runtime.history[-1].status, "waiting_approval")

    def test_local_command_is_planned_and_recorded_by_runtime(self) -> None:
        runtime = AgentRuntime([])
        result = runtime.execute_local_command(
            "bana Vanspor haberlerini oku",
            lambda _text: "Kisa cevap:\nOkundu.\n\nKaynaklar:\n[1] Test\nKaynak: https://example.com",
        )

        self.assertIsNotNone(result)
        self.assertEqual(runtime.history[-1].tool_name, "local_command")
        self.assertEqual(runtime.history[-1].specialist, "ResearchAgent")

    def test_text_agent_runs_model_tool_loop_through_runtime(self) -> None:
        calls = []
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "research_web",
                                        "arguments": '{"query": "Tekirdag Ergene haberleri"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Tekirdag Ergene icin kaynakli arastirma tamamlandi.",
                        }
                    }
                ]
            },
        ]

        def fake_post(config, payload):
            calls.append(payload)
            return responses.pop(0)

        old_post = ar._post_chat_completion
        ar._post_chat_completion = fake_post
        try:
            runtime = AgentRuntime(
                [
                    {
                        "name": "research_web",
                        "description": "research",
                        "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}}},
                    }
                ]
            )

            async def executor(name: str, args: dict) -> str:
                self.assertEqual(name, "research_web")
                self.assertEqual(args["query"], "Tekirdag Ergene haberleri")
                return "Kisa cevap:\nOkundu.\n\nKaynaklar:\n[1] Test\nKaynak: https://example.com"

            result = asyncio.run(
                runtime.run_text_agent(
                    OpenAICompatibleConfig("http://localhost:1/v1", "mock-model", "mock-key"),
                    "system",
                    "Tekirdag Ergene haberlerini arastir",
                    runtime.tool_declarations,
                    executor,
                )
            )
        finally:
            ar._post_chat_completion = old_post

        self.assertEqual(result, "Tekirdag Ergene icin kaynakli arastirma tamamlandi.")
        self.assertEqual(len(calls), 2)
        self.assertEqual(runtime.history[-1].specialist, "ResearchAgent")
        self.assertEqual(runtime.history[-1].status, "completed")
        tool_message = calls[1]["messages"][-1]["content"]
        self.assertIn("specialist=ResearchAgent", tool_message)
        self.assertIn("status=completed", tool_message)

    def test_text_agent_can_make_second_tool_call_after_insufficient_result(self) -> None:
        calls = []
        tool_calls = []
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "research_web",
                                        "arguments": '{"query": "Vanspor haberleri"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {
                                        "name": "browser_research",
                                        "arguments": '{"query": "Vanspor haberleri son dakika", "visible": false}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Alternatif kaynakla Vanspor arastirmasi tamamlandi.",
                        }
                    }
                ]
            },
        ]

        def fake_post(config, payload):
            calls.append(payload)
            return responses.pop(0)

        old_post = ar._post_chat_completion
        ar._post_chat_completion = fake_post
        try:
            runtime = AgentRuntime(
                [
                    {
                        "name": "research_web",
                        "description": "research",
                        "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}}},
                    },
                    {
                        "name": "browser_research",
                        "description": "browser research",
                        "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}}},
                    },
                ]
            )

            async def executor(name: str, args: dict) -> str:
                tool_calls.append((name, args))
                if name == "research_web":
                    return "Kisa cevap:\nBu konuda okunabilir ve alakali kaynak bulamadim; arama sayfasini actim."
                return "Kisa cevap:\nOkundu.\n\nKaynaklar:\n[1] Test\nKaynak: https://example.com/vanspor"

            result = asyncio.run(
                runtime.run_text_agent(
                    OpenAICompatibleConfig("http://localhost:1/v1", "mock-model", "mock-key"),
                    "system",
                    "Vanspor haberlerini arastir",
                    runtime.tool_declarations,
                    executor,
                )
            )
        finally:
            ar._post_chat_completion = old_post

        self.assertEqual(result, "Alternatif kaynakla Vanspor arastirmasi tamamlandi.")
        self.assertEqual([name for name, _args in tool_calls], ["research_web", "browser_research"])
        self.assertEqual(runtime.history[0].status, "needs_followup")
        self.assertEqual(runtime.history[1].status, "completed")
        system_followup = [message for message in calls[1]["messages"] if message.get("role") == "system"][-1]["content"]
        self.assertIn("yetersiz", system_followup)


if __name__ == "__main__":
    unittest.main()
