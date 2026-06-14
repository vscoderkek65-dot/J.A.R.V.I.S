from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import time
import urllib.parse
from typing import Any, Callable

from actions.platform_utils import open_url


BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = BASE_DIR / "memory" / "traces" / "artifacts" / "browser"
USER_AGENT = "Mozilla/5.0 JARVIS BrowserAgent"


@dataclass
class LinkItem:
    text: str
    href: str


@dataclass
class FormField:
    label: str
    name: str
    field_type: str
    selector: str


@dataclass
class PageSnapshot:
    title: str
    url: str
    text: str
    links: list[LinkItem] = field(default_factory=list)
    forms: list[FormField] = field(default_factory=list)


_ACTIVE: dict[str, Any] = {
    "manager": None,
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
    "visible": False,
    "trace_path": None,
}


def _sync_playwright():
    from playwright.sync_api import sync_playwright  # type: ignore

    return sync_playwright()


def _normalize_url(url: str) -> str:
    target = (url or "").strip()
    if not target:
        return ""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    return target


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _excerpt(text: str, limit: int = 900) -> str:
    clean = _normalize_spaces(text)
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if boundary >= 180:
        cut = cut[: boundary + 1]
    return cut.strip() + " ..."


def _artifact_paths(prefix: str = "browser") -> tuple[Path, Path]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    clean = re.sub(r"[^a-z0-9_-]+", "_", prefix.casefold()).strip("_") or "browser"
    return ARTIFACT_DIR / f"{clean}-{stamp}.png", ARTIFACT_DIR / f"{clean}-{stamp}.zip"


def _install_hint(error: Exception | str) -> str:
    message = str(error or "")
    folded = message.casefold()
    if "executable doesn't exist" in folded or "playwright install" in folded or "chromium" in folded:
        return " Playwright Chromium eksik olabilir: .\\venv\\Scripts\\python.exe -m playwright install chromium"
    return ""


def _start_browser(visible: bool, keep_open: bool):
    manager = _sync_playwright()
    playwright = manager.start()
    browser = playwright.chromium.launch(headless=not bool(visible))
    context = browser.new_context(user_agent=USER_AGENT)
    screenshot_path, trace_path = _artifact_paths("browser-agent")
    try:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    except Exception:
        trace_path = Path("")
    page = context.new_page()

    if keep_open:
        _close_active()
        _ACTIVE.update(
            {
                "manager": manager,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "visible": visible,
                "trace_path": trace_path,
            }
        )

    return manager, playwright, browser, context, page, screenshot_path, trace_path


def _close_browser(manager, browser, context, trace_path: Path | None = None, keep_trace: bool = False, playwright=None) -> None:
    try:
        if context and trace_path and trace_path and keep_trace:
            context.tracing.stop(path=str(trace_path))
        elif context:
            try:
                context.tracing.stop()
            except Exception:
                pass
    except Exception:
        pass
    try:
        if context:
            context.close()
    except Exception:
        pass
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    try:
        if playwright and hasattr(playwright, "stop"):
            playwright.stop()
            return
    except Exception:
        pass
    try:
        if manager:
            manager.stop()
    except Exception:
        pass


def _close_active() -> None:
    manager = _ACTIVE.get("manager")
    playwright = _ACTIVE.get("playwright")
    browser = _ACTIVE.get("browser")
    context = _ACTIVE.get("context")
    _close_browser(manager, browser, context, _ACTIVE.get("trace_path"), keep_trace=False, playwright=playwright)
    _ACTIVE.update({"manager": None, "playwright": None, "browser": None, "context": None, "page": None, "visible": False, "trace_path": None})


def _capture_failure(page, context, screenshot_path: Path, trace_path: Path, error: Exception | str) -> str:
    artifacts: list[str] = []
    try:
        if page:
            page.screenshot(path=str(screenshot_path), full_page=True)
            artifacts.append(f"screenshot={screenshot_path}")
    except Exception:
        pass
    try:
        if context and trace_path:
            context.tracing.stop(path=str(trace_path))
            artifacts.append(f"trace={trace_path}")
    except Exception:
        pass
    detail = f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
    if artifacts:
        return f"{detail}\nArtifact: " + ", ".join(artifacts)
    return detail


def _extract_links(raw: Any) -> list[LinkItem]:
    links: list[LinkItem] = []
    if not isinstance(raw, list):
        return links
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        href = _normalize_url(str(item.get("href") or ""))
        text = _normalize_spaces(str(item.get("text") or href))
        if not href or href in seen:
            continue
        seen.add(href)
        links.append(LinkItem(text[:180] or href, href))
        if len(links) >= 40:
            break
    return links


def _extract_forms(raw: Any) -> list[FormField]:
    fields: list[FormField] = []
    if not isinstance(raw, list):
        return fields
    for item in raw:
        if not isinstance(item, dict):
            continue
        selector = _normalize_spaces(str(item.get("selector") or ""))
        if not selector:
            continue
        fields.append(
            FormField(
                label=_normalize_spaces(str(item.get("label") or item.get("placeholder") or item.get("name") or selector))[:160],
                name=_normalize_spaces(str(item.get("name") or ""))[:120],
                field_type=_normalize_spaces(str(item.get("type") or "text"))[:60],
                selector=selector,
            )
        )
        if len(fields) >= 20:
            break
    return fields


def _snapshot(page) -> PageSnapshot:
    title = _normalize_spaces(page.title() if callable(getattr(page, "title", None)) else getattr(page, "title", ""))
    url = _normalize_url(str(getattr(page, "url", "") or ""))
    text = _normalize_spaces(
        page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
    )
    links = _extract_links(
        page.evaluate(
            """() => Array.from(document.links).map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href
            }))"""
        )
    )
    forms = _extract_forms(
        page.evaluate(
            """() => Array.from(document.querySelectorAll('input, textarea, select')).map((el, index) => {
                const label = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
                const name = el.getAttribute('name') || '';
                const type = el.getAttribute('type') || el.tagName.toLowerCase();
                const placeholder = el.getAttribute('placeholder') || '';
                const selector = el.id ? `#${el.id}` : name ? `[name="${name}"]` : `${el.tagName.toLowerCase()}:nth-of-type(${index + 1})`;
                return {label: label ? label.innerText : '', name, type, placeholder, selector};
            })"""
        )
    )
    return PageSnapshot(title=title or url, url=url, text=text, links=links, forms=forms)


def _keyword_score(label: str, href: str, question: str) -> int:
    folded = f"{label} {href}".casefold()
    words = [word for word in re.findall(r"[^\W_]+", (question or "").casefold(), flags=re.UNICODE) if len(word) > 3]
    return sum(1 for word in words if word in folded)


def _format_snapshot(snapshot: PageSnapshot, heading: str = "Sayfa") -> list[str]:
    lines = [f"{heading}: {snapshot.title}", f"Kaynak: {snapshot.url}", f"Metin onizleme:\n{_excerpt(snapshot.text, 1500)}"]
    if snapshot.forms:
        lines.append("Form alanlari:")
        for field in snapshot.forms[:8]:
            lines.append(f"- {field.label or field.name or field.selector} | type={field.field_type} | selector={field.selector}")
    if snapshot.links:
        lines.append("Ilk linkler:")
        for link in snapshot.links[:8]:
            lines.append(f"- {link.text}: {link.href}")
    return lines


def _with_browser(visible: bool, keep_open: bool, work: Callable[[Any], str], prefix: str) -> str:
    manager = playwright = browser = context = page = None
    screenshot_path = trace_path = Path("")
    try:
        manager, playwright, browser, context, page, screenshot_path, trace_path = _start_browser(visible, keep_open)
        result = work(page)
        if not keep_open:
            _close_browser(manager, browser, context, trace_path, keep_trace=False, playwright=playwright)
        return result
    except Exception as exc:
        detail = _capture_failure(page, context, screenshot_path, trace_path, exc)
        if not keep_open:
            _close_browser(manager, browser, context, trace_path, keep_trace=False, playwright=playwright)
        else:
            _close_active()
        return f"BrowserAgent basarisiz: {detail}{_install_hint(exc)}"


def browser_read_url(url: str, question: str = "", max_pages: int = 3, visible: bool = False) -> str:
    target = _normalize_url(url)
    if not target:
        return "Okunacak URL belirtilmedi."
    max_pages = max(1, min(5, int(max_pages or 3)))
    keep_open = bool(visible)

    def work(page) -> str:
        page.goto(target, wait_until="domcontentloaded", timeout=25000)
        primary = _snapshot(page)
        lines = [f"BrowserAgent okuma modu: {'gorunur' if visible else 'headless'}"]
        lines.extend(_format_snapshot(primary))

        ranked_links = sorted(
            primary.links,
            key=lambda item: _keyword_score(item.text, item.href, question),
            reverse=True,
        )
        followed = 0
        for link in ranked_links:
            if followed >= max_pages - 1:
                break
            if question and _keyword_score(link.text, link.href, question) <= 0:
                continue
            try:
                page.goto(link.href, wait_until="domcontentloaded", timeout=18000)
                child = _snapshot(page)
                lines.append("")
                lines.extend(_format_snapshot(child, heading="Ilgili alt sayfa"))
                followed += 1
            except Exception as exc:
                lines.append(f"Okunamayan alt sayfa: {link.href} ({type(exc).__name__}: {exc})")
        if keep_open:
            lines.append("Tarayici oturumu acik tutuldu; onayli click/fill/submit islemleri bu sayfada denenebilir.")
        return "\n".join(lines)

    result = _with_browser(bool(visible), keep_open, work, "browser-read")
    if result.startswith("BrowserAgent basarisiz"):
        open_url(target)
        return result + f"\nFallback: Varsayilan tarayicida acildi: {target}"
    return result


def browser_research(query: str, max_pages: int = 5, visible: bool = False) -> str:
    query = _normalize_spaces(query)
    if not query:
        return "Arastirma sorgusu belirtilmedi."
    max_pages = max(1, min(6, int(max_pages or 5)))
    search_url = "https://www.bing.com/search?setlang=tr-TR&q=" + urllib.parse.quote(query)
    keep_open = bool(visible)

    def work(page) -> str:
        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        search = _snapshot(page)
        ranked = sorted(search.links, key=lambda item: _keyword_score(item.text, item.href, query), reverse=True)
        docs: list[PageSnapshot] = []
        unreadable: list[str] = []
        for link in ranked:
            if len(docs) >= max_pages:
                break
            if urllib.parse.urlparse(link.href).netloc.lower().endswith("bing.com"):
                continue
            if _keyword_score(link.text, link.href, query) <= 0 and len(docs) > 0:
                continue
            try:
                page.goto(link.href, wait_until="domcontentloaded", timeout=20000)
                snap = _snapshot(page)
                if len(snap.text) < 80:
                    unreadable.append(f"{link.href} (yeterli metin yok)")
                    continue
                docs.append(snap)
            except Exception as exc:
                unreadable.append(f"{link.href} ({type(exc).__name__}: {exc})")

        if not docs:
            from actions.web_research import research_web

            fallback = research_web(query, max_pages=max_pages, open_browser=bool(visible))
            return (
                "BrowserAgent arama sonuclarindan okunabilir kaynak alamadi; ResearchAgent fallback calisti.\n\n"
                + fallback
            )

        first = docs[0]
        lines = [f"Arastirma: {query}", "", "Kisa cevap:"]
        lines.append(f"BrowserAgent {len(docs)} kaynak okudu. En belirgin kaynak: {first.title}. {_excerpt(first.text, 420)}")
        lines.extend(["", "Detaylar:"])
        for index, doc in enumerate(docs, start=1):
            lines.append(f"- [{index}] {_excerpt(doc.text, 620)}")
        lines.extend(["", "Kaynaklar:"])
        for index, doc in enumerate(docs, start=1):
            lines.append(f"[{index}] {doc.title}\nKaynak: {doc.url}")
        if unreadable:
            lines.extend(["", "Okunamayan kaynaklar:"])
            for index, detail in enumerate(unreadable[:5], start=1):
                lines.append(f"- {index}. {detail}")
        lines.extend(["", "Arama notlari:"])
        lines.append(f"- BrowserAgent modu: {'gorunur' if visible else 'headless'}")
        lines.append(f"- Arama kaynagi: {search_url}")
        if keep_open:
            lines.append("- Tarayici oturumu acik tutuldu; onayli click/fill/submit islemleri son sayfada denenebilir.")
        return "\n".join(lines)

    result = _with_browser(bool(visible), keep_open, work, "browser-research")
    if result.startswith("BrowserAgent basarisiz"):
        from actions.web_research import research_web

        fallback = research_web(query, max_pages=max_pages, open_browser=bool(visible))
        return result + "\n\nFallback ResearchAgent sonucu:\n" + fallback
    return result


def _active_page():
    page = _ACTIVE.get("page")
    if not page:
        return None
    return page


def _locator_by_selector_or_text(page, selector_or_text: str):
    target = (selector_or_text or "").strip()
    if not target:
        raise ValueError("Selector veya gorunen metin belirtilmedi.")
    try:
        locator = page.locator(target).first
        if hasattr(locator, "count") and locator.count() > 0:
            return locator
        if not hasattr(locator, "count"):
            return locator
    except Exception:
        pass
    return page.get_by_text(target, exact=False).first


def browser_click(selector_or_text: str, visible: bool = True) -> str:
    page = _active_page()
    if not page:
        return "Aktif BrowserAgent oturumu yok. Once browser_read_url(..., visible=true) veya browser_research(..., visible=true) calistir."
    try:
        locator = _locator_by_selector_or_text(page, selector_or_text)
        locator.click(timeout=8000)
        return f"Onayli tiklama yapildi: {selector_or_text}\nAktif URL: {getattr(page, 'url', '')}"
    except Exception as exc:
        screenshot_path, trace_path = _artifact_paths("browser-click")
        detail = _capture_failure(page, _ACTIVE.get("context"), screenshot_path, trace_path, exc)
        return f"Browser tiklama basarisiz: {detail}"


def browser_fill(selector_or_label: str, value: str, visible: bool = True) -> str:
    page = _active_page()
    if not page:
        return "Aktif BrowserAgent oturumu yok. Once browser_read_url(..., visible=true) veya browser_research(..., visible=true) calistir."
    target = (selector_or_label or "").strip()
    if not target:
        return "Doldurulacak alan selector/etiketi belirtilmedi."
    try:
        try:
            locator = page.locator(target).first
            locator.fill(str(value or ""), timeout=8000)
        except Exception:
            locator = page.get_by_label(target, exact=False).first
            locator.fill(str(value or ""), timeout=8000)
        return f"Onayli form alani dolduruldu: {target}"
    except Exception as exc:
        screenshot_path, trace_path = _artifact_paths("browser-fill")
        detail = _capture_failure(page, _ACTIVE.get("context"), screenshot_path, trace_path, exc)
        return f"Browser form doldurma basarisiz: {detail}"


def browser_submit(selector_or_text: str = "", visible: bool = True) -> str:
    page = _active_page()
    if not page:
        return "Aktif BrowserAgent oturumu yok. Once browser_read_url(..., visible=true) veya browser_research(..., visible=true) calistir."
    try:
        target = (selector_or_text or "").strip()
        if target:
            locator = _locator_by_selector_or_text(page, target)
            locator.click(timeout=8000)
        else:
            page.keyboard.press("Enter")
        return f"Onayli form gonderme denendi. Aktif URL: {getattr(page, 'url', '')}"
    except Exception as exc:
        screenshot_path, trace_path = _artifact_paths("browser-submit")
        detail = _capture_failure(page, _ACTIVE.get("context"), screenshot_path, trace_path, exc)
        return f"Browser form gonderme basarisiz: {detail}"


def close_browser_agent() -> str:
    _close_active()
    return "BrowserAgent oturumu kapatildi."
