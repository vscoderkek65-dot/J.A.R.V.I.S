from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200, content: bytes | None = None, payload: dict | None = None):
        self.text = text
        self.status_code = status_code
        self.content = content if content is not None else text.encode("utf-8")
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        if self._payload is not None:
            return self._payload
        return json.loads(self.text or "{}")


class FakeRequests:
    def __init__(self):
        self.get_handler = lambda url, **kwargs: FakeResponse("<html><body></body></html>")
        self.post_handler = lambda url, **kwargs: FakeResponse(payload={})

    def get(self, url: str, **kwargs):
        return self.get_handler(url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.post_handler(url, **kwargs)


fake_requests = FakeRequests()
sys.modules["requests"] = fake_requests

import actions.web_research as wr  # noqa: E402
import actions.local_web as lw  # noqa: E402


EMPTY_RSS = b'<?xml version="1.0"?><rss><channel></channel></rss>'


class ResearchAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        wr.get_app_config_value = lambda key, default="": ""
        fake_requests.get_handler = lambda url, **kwargs: FakeResponse("<html><body></body></html>")
        fake_requests.post_handler = lambda url, **kwargs: FakeResponse(payload={})

    def test_rejects_irrelevant_tavily_and_reads_tekirdag_ergene_direct_source(self) -> None:
        def post(_url: str, **_kwargs):
            return FakeResponse(
                payload={
                    "answer": "The provided sources do not contain any recent news about Tekirdag Ergene.",
                    "results": [
                        {
                            "title": "DataGreat Founder Alper Tekin Analyzes Iran-Israel-US Risk to Turkish Tourism",
                            "url": "https://natlawreview.com/press-releases/foo",
                            "content": "Turkish tourism risk analysis",
                        }
                    ],
                }
            )

        def get(url: str, **_kwargs):
            if "news.google.com/rss" in url:
                return FakeResponse(content=EMPTY_RSS)
            if url == "https://www.sondakika.com/ergene/":
                return FakeResponse("<html><body></body></html>")
            if url.startswith("https://r.jina.ai/https://www.sondakika.com/ergene/"):
                return FakeResponse(
                    "Title: Son Dakika Ergene Haberleri\n"
                    "URL Source: https://www.sondakika.com/ergene/\n"
                    "Markdown Content:\n"
                    "Tekirdag Ergene haberleri son dakika. Tekirdag ilinin Ergene ilcesinde ekipler inceleme baslatti. "
                    "Ergene Belediyesi yol bakim calismalarini surduruyor.\n"
                )
            return FakeResponse("<html><body></body></html>")

        wr.get_app_config_value = lambda key, default="": "fake-key" if key == "tavily_api_key" else default
        fake_requests.post_handler = post
        fake_requests.get_handler = get

        result = wr.research_web("TEKIRDAG ERGENE haberleri son dakika", max_pages=5, open_browser=False)

        self.assertIn("Kisa cevap:", result)
        self.assertIn("Kaynak: https://www.sondakika.com/ergene/", result)
        self.assertNotIn("natlawreview", result.lower())
        self.assertNotIn("provided sources do not contain", result.lower())
        self.assertIn("Reddedilen alakasiz kaynaklar", result)

    def test_search_engines_empty_but_vanspor_direct_source_reader_succeeds(self) -> None:
        def get(url: str, **_kwargs):
            if "news.google.com/rss" in url:
                return FakeResponse(content=EMPTY_RSS)
            if url == "https://www.sondakika.com/vanspor/":
                return FakeResponse("<html><body></body></html>")
            if url.startswith("https://r.jina.ai/https://www.sondakika.com/vanspor/"):
                return FakeResponse(
                    "Title: Son Dakika Vanspor FK Haberleri\n"
                    "URL Source: https://www.sondakika.com/vanspor/\n"
                    "Markdown Content:\n"
                    "Vanspor FK haberleri son dakika. Vanspor yeni mac hazirliklarini surduruyor. "
                    "Teknik ekip ve transfer gelismeleri takip ediliyor.\n"
                )
            return FakeResponse("<html><body></body></html>")

        fake_requests.get_handler = get

        result = wr.research_web("Vanspor haberleri son dakika", max_pages=5, open_browser=False)

        self.assertIn("Kisa cevap:", result)
        self.assertIn("Kaynak: https://www.sondakika.com/vanspor/", result)
        self.assertNotIn("Bu konuda okunabilir ve alakali kaynak bulamadim", result)

    def test_general_research_uses_search_result_and_standard_sections(self) -> None:
        def get(url: str, **_kwargs):
            if "bing.com/search" in url:
                return FakeResponse(
                    '<html><body><a href="https://example.com/ai-agents">Yapay zeka ajanlari nedir</a></body></html>'
                )
            if url == "https://example.com/ai-agents":
                return FakeResponse("<html><body></body></html>")
            if url.startswith("https://r.jina.ai/https://example.com/ai-agents"):
                return FakeResponse(
                    "Title: Yapay zeka ajanlari\n"
                    "URL Source: https://example.com/ai-agents\n"
                    "Markdown Content:\n"
                    "Yapay zeka ajanlari hedefleri takip eden, arac kullanabilen ve cok adimli gorevleri planlayan yazilim sistemleridir.\n"
                )
            return FakeResponse("<html><body></body></html>")

        fake_requests.get_handler = get

        result = lw.handle_local_web_command("yapay zeka ajanlari nedir")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Kisa cevap:", result)
        self.assertIn("Detaylar:", result)
        self.assertIn("Kaynaklar:", result)
        self.assertIn("https://example.com/ai-agents", result)

    def test_technical_research_uses_search_result_and_reader_fallback(self) -> None:
        reader_urls: list[str] = []

        def get(url: str, **_kwargs):
            if "bing.com/search" in url:
                return FakeResponse(
                    '<html><body><a href="https://docs.example.com/pyaudio-windows-error">'
                    "Windows PyAudio host error cozum rehberi</a></body></html>"
                )
            if url == "https://docs.example.com/pyaudio-windows-error":
                return FakeResponse("<html><title>PyAudio Windows</title><body>short</body></html>")
            if url.startswith("https://r.jina.ai/https://docs.example.com/pyaudio-windows-error"):
                reader_urls.append(url)
                return FakeResponse(
                    "Title: Windows PyAudio host error cozum rehberi\n"
                    "URL Source: https://docs.example.com/pyaudio-windows-error\n"
                    "Markdown Content:\n"
                    "Windows PyAudio host error cozum adimlari arasinda varsayilan giris cihazini kontrol etmek, "
                    "WASAPI cihazlarini yenilemek, Python wheel uyumlulugunu dogrulamak ve uygulamayi text mode fallback ile "
                    "calistirmak bulunur. Teknik ariza icin mikrofon izinleri ve ses hizmetleri de incelenmelidir.\n"
                )
            return FakeResponse("<html><body></body></html>")

        fake_requests.get_handler = get

        result = wr.research_web("Windows PyAudio host error cozum", max_pages=5, open_browser=False)

        self.assertIn("Kisa cevap:", result)
        self.assertIn("Kaynaklar:", result)
        self.assertIn("https://docs.example.com/pyaudio-windows-error", result)
        self.assertTrue(reader_urls)

    def test_empty_research_does_not_open_browser_when_open_browser_false(self) -> None:
        opened: list[str] = []
        old_open_url = wr.open_url
        wr.open_url = lambda url: opened.append(url) or f"opened {url}"
        try:
            result = wr.research_web("benzersiz bulunmayan konu qqq", max_pages=2, open_browser=False)
        finally:
            wr.open_url = old_open_url

        self.assertEqual(opened, [])
        self.assertIn("Arama URL", result)
        self.assertIn("onerildi", result)
        self.assertNotIn("arama sayfasini actim", result.casefold())

    def test_empty_research_opens_browser_when_open_browser_true(self) -> None:
        opened: list[str] = []
        old_open_url = wr.open_url
        wr.open_url = lambda url: opened.append(url) or f"opened {url}"
        try:
            result = wr.research_web("benzersiz bulunmayan konu qqq", max_pages=2, open_browser=True)
        finally:
            wr.open_url = old_open_url

        self.assertEqual(len(opened), 1)
        self.assertIn("Acilan arama", result)

    def test_plain_google_search_does_not_trigger_research_agent(self) -> None:
        result = lw.handle_local_web_command("Google'da Python ogren ara")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("arama", result.casefold())
        self.assertNotIn("Kisa cevap:", result)


if __name__ == "__main__":
    unittest.main()
