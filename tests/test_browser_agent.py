from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import actions.browser_agent as ba  # noqa: E402
import actions.local_web as lw  # noqa: E402


class FakeLocator:
    def __init__(self):
        self.first = self
        self.actions: list[tuple[str, str]] = []

    def count(self):
        return 1

    def click(self, timeout=0):
        self.actions.append(("click", str(timeout)))

    def fill(self, value, timeout=0):
        self.actions.append(("fill", str(value)))


class FakeKeyboard:
    def __init__(self):
        self.pressed: list[str] = []

    def press(self, key):
        self.pressed.append(key)


class FakePage:
    def __init__(self, manager):
        self.manager = manager
        self.url = ""
        self.keyboard = FakeKeyboard()
        self._locator = FakeLocator()

    def goto(self, url, wait_until=None, timeout=0):
        self.url = url
        self.manager.visited.append(url)
        if url in self.manager.fail_urls:
            raise RuntimeError("boom")

    def title(self):
        return self.manager.pages.get(self.url, {}).get("title", self.url)

    def evaluate(self, script):
        page = self.manager.pages.get(self.url, {})
        if "document.body" in script:
            return page.get("text", "")
        if "document.links" in script:
            return page.get("links", [])
        if "querySelectorAll" in script:
            return page.get("forms", [])
        return ""

    def screenshot(self, path, full_page=True):
        Path(path).write_bytes(b"fake-png")

    def locator(self, _target):
        return self._locator

    def get_by_text(self, _target, exact=False):
        return self._locator

    def get_by_label(self, _target, exact=False):
        return self._locator


class FakeTracing:
    def __init__(self):
        self.started = False

    def start(self, **_kwargs):
        self.started = True

    def stop(self, path=None):
        if path:
            Path(path).write_bytes(b"fake-trace")


class FakeContext:
    def __init__(self, manager):
        self.manager = manager
        self.tracing = FakeTracing()
        self.page = FakePage(manager)

    def new_page(self):
        return self.page

    def close(self):
        self.manager.closed.append("context")


class FakeBrowser:
    def __init__(self, manager):
        self.manager = manager

    def new_context(self, **kwargs):
        self.manager.context_kwargs = kwargs
        self.manager.context = FakeContext(self.manager)
        return self.manager.context

    def close(self):
        self.manager.closed.append("browser")


class FakeChromium:
    def __init__(self, manager):
        self.manager = manager

    def launch(self, headless=True):
        self.manager.launch_headless_values.append(headless)
        if self.manager.fail_launch:
            raise RuntimeError("Executable doesn't exist")
        return FakeBrowser(self.manager)


class FakePlaywright:
    def __init__(self, manager):
        self.chromium = FakeChromium(manager)


class FakeManager:
    def __init__(self):
        self.pages = {}
        self.fail_urls: set[str] = set()
        self.fail_launch = False
        self.launch_headless_values: list[bool] = []
        self.visited: list[str] = []
        self.closed: list[str] = []
        self.context = None
        self.context_kwargs = {}

    def start(self):
        return FakePlaywright(self)

    def stop(self):
        self.closed.append("manager")


class BrowserAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_sync = ba._sync_playwright
        self.old_artifact_dir = ba.ARTIFACT_DIR
        self.old_open_url = ba.open_url
        self.tmp = tempfile.TemporaryDirectory()
        ba.ARTIFACT_DIR = Path(self.tmp.name)
        ba.open_url = lambda _url: True
        ba.close_browser_agent()

    def tearDown(self) -> None:
        ba.close_browser_agent()
        ba._sync_playwright = self.old_sync
        ba.ARTIFACT_DIR = self.old_artifact_dir
        ba.open_url = self.old_open_url
        self.tmp.cleanup()

    def test_browser_read_url_visible_extracts_text_links_and_forms(self) -> None:
        manager = FakeManager()
        manager.pages = {
            "https://example.com": {
                "title": "Main Page",
                "text": "Ana sayfa fiyat ve urun bilgileri.",
                "links": [{"text": "Fiyatlar", "href": "https://example.com/pricing"}],
                "forms": [{"label": "E-posta", "name": "email", "type": "email", "selector": "#email"}],
            },
            "https://example.com/pricing": {
                "title": "Pricing",
                "text": "Fiyatlar sayfasi aylik planlari anlatir.",
                "links": [],
                "forms": [],
            },
        }
        ba._sync_playwright = lambda: manager

        result = ba.browser_read_url("https://example.com", question="fiyat", max_pages=2, visible=True)

        self.assertIn("BrowserAgent okuma modu: gorunur", result)
        self.assertIn("Main Page", result)
        self.assertIn("Ilgili alt sayfa: Pricing", result)
        self.assertIn("Form alanlari", result)
        self.assertEqual(manager.launch_headless_values, [False])

    def test_browser_research_headless_returns_standard_sections(self) -> None:
        manager = FakeManager()
        search_url = "https://www.bing.com/search?setlang=tr-TR&q=" + "python%20paket%20kurulumu"
        manager.pages = {
            search_url: {
                "title": "Search",
                "text": "Search page",
                "links": [
                    {"text": "Python paket kurulumu Windows rehberi", "href": "https://example.com/python-windows"},
                    {"text": "Baska sonuc", "href": "https://example.org/other"},
                ],
                "forms": [],
            },
            "https://example.com/python-windows": {
                "title": "Python Windows Kurulum Rehberi",
                "text": "Python paket kurulumu Windows ortaminda pip, wheel ve build tools adimlarini anlatir. Bu rehber paket kurulumu sorunlarini anlamak icin yeterli detay icerir.",
                "links": [],
                "forms": [],
            },
            "https://example.org/other": {
                "title": "Other",
                "text": "Python paketleri hakkinda ek bilgi, sanal ortam kullanimi ve Windows kurulum notlari bu kaynakta ayrintili olarak verilir.",
                "links": [],
                "forms": [],
            },
        }
        ba._sync_playwright = lambda: manager

        result = ba.browser_research("python paket kurulumu", max_pages=2, visible=False)

        self.assertIn("Kisa cevap:", result)
        self.assertIn("Detaylar:", result)
        self.assertIn("Kaynaklar:", result)
        self.assertIn("Arama notlari:", result)
        self.assertEqual(manager.launch_headless_values, [True])

    def test_browser_failure_writes_artifacts(self) -> None:
        manager = FakeManager()
        manager.pages = {}
        manager.fail_urls.add("https://broken.example")
        ba._sync_playwright = lambda: manager

        result = ba.browser_read_url("https://broken.example", visible=False)

        self.assertIn("BrowserAgent basarisiz", result)
        self.assertIn("Artifact:", result)
        self.assertTrue(list(Path(self.tmp.name).glob("*.png")))
        self.assertTrue(list(Path(self.tmp.name).glob("*.zip")))

    def test_local_tarayicida_research_routes_to_browser_agent_visible(self) -> None:
        calls = []
        old_browser_research = lw.browser_research
        lw.browser_research = lambda query, max_pages=5, visible=False: calls.append((query, visible)) or "browser research ok"
        try:
            result = lw.handle_local_web_command("tarayicida Vanspor haberlerini arastir")
        finally:
            lw.browser_research = old_browser_research

        self.assertEqual(result, "browser research ok")
        self.assertTrue(calls)
        self.assertTrue(calls[0][1])

    def test_main_dispatch_keeps_risky_browser_actions_pending(self) -> None:
        main_text = (ROOT / "main.py").read_text(encoding="utf-8")
        fill_block = main_text.split('elif name == "browser_fill":', 1)[1].split('elif name == "browser_submit":', 1)[0]
        submit_block = main_text.split('elif name == "browser_submit":', 1)[1].split('elif name == "shell_run":', 1)[0]

        self.assertIn('elif name == "browser_fill"', main_text)
        self.assertIn('elif name == "browser_submit"', main_text)
        self.assertIn("self._guarded_tool_action(", fill_block)
        self.assertIn("lambda: browser_fill", fill_block)
        self.assertIn("self._guarded_tool_action(", submit_block)
        self.assertIn("lambda: browser_submit", submit_block)


if __name__ == "__main__":
    unittest.main()
