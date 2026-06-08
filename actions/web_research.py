from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
import re
import time
import unicodedata
import urllib.parse
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree as ET

from app_config import get_app_config_value
from actions.platform_utils import open_url


USER_AGENT = "Mozilla/5.0 JARVIS Desktop Research"
MIN_TEXT_CHARS = 80


@dataclass
class Candidate:
    title: str
    url: str
    provider: str
    snippet: str = ""


@dataclass
class Document:
    title: str
    url: str
    text: str
    provider: str
    score: int = 0
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    query: str
    used_query: str
    intent: str
    docs: list[Document] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    search_url: str = ""
    browser_note: str = ""
    tavily_answer: str = ""


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().replace("ı", "i")


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", " ", html or "")
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    html = re.sub(r"(?is)<noscript.*?</noscript>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = unescape(html)
    return _normalize_spaces(html)


def _strip_reader_metadata(text: str) -> str:
    value = re.sub(r"(?im)^Title:\s*.*$", " ", text or "")
    value = re.sub(r"(?im)^URL Source:\s*.*$", " ", value)
    value = re.sub(r"(?im)^Markdown Content:\s*", " ", value)
    return value


def _soup_text_and_links(html: str, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = _normalize_spaces(soup.get_text(" "))
        links: list[tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, str(anchor.get("href") or ""))
            label = _normalize_spaces(anchor.get_text(" "))
            if href.startswith(("http://", "https://")):
                links.append((label[:140] or href, href))
        return text, _dedupe_links(links)
    except Exception:
        text = _strip_html(html)
        links = []
        for match in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or ""):
            href = urljoin(base_url, unescape(match.group(1)))
            label = _strip_html(match.group(2))[:140]
            if href.startswith(("http://", "https://")):
                links.append((label or href, href))
        return text, _dedupe_links(links)


def _dedupe_links(links: list[tuple[str, str]], limit: int = 40) -> list[tuple[str, str]]:
    seen: set[str] = set()
    clean: list[tuple[str, str]] = []
    for label, href in links:
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        if any(host in parsed.netloc for host in ("google.", "duckduckgo.com")) and "/url" not in parsed.path:
            continue
        key = href.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        clean.append((_normalize_spaces(label) or href, href))
        if len(clean) >= limit:
            break
    return clean


def _domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _text_excerpt(text: str, limit: int = 650) -> str:
    clean = _normalize_spaces(_strip_html(text))
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if boundary >= 180:
        cut = cut[: boundary + 1]
    return cut.strip() + " ..."


def _source_bullet(index: int, title: str, url: str) -> str:
    return f"[{index}] {title}\nKaynak: {url}"


def _is_news_query(query: str) -> bool:
    folded = _fold(query)
    return any(marker in folded for marker in ("haber", "son dakika", "guncel", "bugun", "spor", "vanspor"))


def _research_intent(query: str) -> str:
    folded = _fold(query)
    if _is_news_query(query):
        return "haber"
    if any(marker in folded for marker in ("karsilastir", " vs ", "farki", "fark ")):
        return "karsilastirma"
    if any(marker in folded for marker in ("nasil", "hata", "kurulum", "python", "windows", "api", "debug")):
        return "teknik"
    return "genel"


def _clean_research_query(query: str) -> str:
    value = _normalize_spaces(query).strip(" \t\r\n'\".,:;")
    value = re.sub(
        r"^(bana|bir|en son|son|guncel|gunel|lutfen|lütfen)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(oku|sesli oku|sesli olarak oku|okur musun|okuyabilir misin|arastir|araştır|araştırma yap|arama yap|bak|bul|bilgi ver|hakkinda bilgi ver|hakkında bilgi ver)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\bvan\s+spor\b", "Vanspor", value, flags=re.IGNORECASE)
    return _normalize_spaces(value).strip(" \t\r\n'\".,:;") or _normalize_spaces(query)


class ResearchAgent:
    """Balanced web research agent: search, read, score, reject, summarize."""

    def __init__(self, max_pages: int = 5):
        self.max_pages = max(3, min(6, int(max_pages or 5)))

    def run(self, query: str, open_browser: bool = False) -> ResearchResult:
        clean_query = _clean_research_query(query)
        result = ResearchResult(
            query=clean_query,
            used_query=clean_query,
            intent=_research_intent(clean_query),
        )
        if not clean_query:
            result.notes.append("Arastirma sorgusu belirtilmedi.")
            return result

        tavily_docs, tavily_answer, tavily_query = self._collect_tavily(clean_query, result)
        if tavily_docs:
            result.docs.extend(tavily_docs)
            result.tavily_answer = tavily_answer
            result.used_query = tavily_query

        if len(result.docs) < max(2, min(3, self.max_pages)):
            self._collect_fallback(clean_query, result)

        result.docs = self._dedupe_documents(result.docs)[: self.max_pages]
        if open_browser:
            urls = [result.search_url] if result.search_url else []
            urls.extend(doc.url for doc in result.docs[:2])
            result.browser_note = _visible_browser_note(urls)
        elif not result.docs and result.search_url:
            result.browser_note = _visible_browser_note([result.search_url])
        return result

    def query_variants(self, query: str) -> list[str]:
        raw = _normalize_spaces(query)
        if not raw:
            return []
        variants = [raw]
        folded = _fold(raw)
        compact_vanspor = re.sub(r"\bvan\s+spor\b", "Vanspor", raw, flags=re.IGNORECASE)
        if compact_vanspor != raw:
            variants.append(compact_vanspor)
            variants.append(re.sub(r"\bhaberleri\b", "", compact_vanspor, flags=re.IGNORECASE).strip() + " haberleri")
        if "vanspor" in _fold(compact_vanspor) and " fk" not in _fold(compact_vanspor):
            variants.append(compact_vanspor + " FK")
        intent = _research_intent(raw)
        if intent == "haber" and "haber" not in folded:
            variants.append(raw + " haberleri son dakika")
        elif intent == "karsilastirma":
            variants.append(raw + " karsilastirma")
        elif intent == "teknik":
            variants.append(raw + " cozum")
        elif len(raw.split()) <= 4:
            variants.append(raw + " nedir")

        clean: list[str] = []
        seen: set[str] = set()
        for item in variants:
            value = _normalize_spaces(item)
            key = _fold(value)
            if value and key not in seen:
                seen.add(key)
                clean.append(value)
        return clean

    def important_terms(self, query: str) -> list[str]:
        folded = _fold(query)
        if "vanspor" in folded or re.search(r"\bvan\s+spor\b", folded):
            return ["vanspor"]
        words = re.findall(r"[^\W_]+", folded, flags=re.UNICODE)
        stop = {
            "haber",
            "haberleri",
            "son",
            "dakika",
            "guncel",
            "gunel",
            "bana",
            "oku",
            "arama",
            "arastir",
            "arastirma",
            "ara",
            "bul",
            "bak",
            "sesli",
            "olarak",
            "spor",
            "football",
            "soccer",
            "the",
            "and",
            "nedir",
            "nasil",
        }
        return [word for word in words if len(word) > 3 and word not in stop][:5]

    def score_text(self, query: str, title: str, url: str, content: str) -> tuple[int, list[str], str]:
        haystack = _fold(f"{title} {url} {content}")
        terms = self.important_terms(query)
        if not terms:
            return 1, [], "genel sorgu"

        if terms == ["vanspor"]:
            ok = "vanspor" in haystack or "van spor" in haystack
            return (5 if ok else 0), (["vanspor"] if ok else []), "vanspor zorunlu terim"

        matched = [term for term in terms if term in haystack]
        if {"tekirdag", "ergene"}.issubset(set(terms)) and not {"tekirdag", "ergene"}.issubset(set(matched)):
            return 0, matched, "tekirdag ve ergene birlikte gecmeli"

        required = min(2, len(terms))
        if len(matched) < required:
            return 0, matched, f"en az {required} ana terim gerekli"

        score = len(matched) * 2
        if any(signal in _fold(title) for signal in ("haber", "son dakika", "guncel")):
            score += 1
        if _is_news_query(query) and any(signal in _fold(url) for signal in ("haber", "news", "sondakika")):
            score += 1
        return score, matched, "alakali"

    def is_relevant(self, query: str, title: str, url: str, content: str) -> bool:
        return self.score_text(query, title, url, content)[0] > 0

    def direct_topic_urls(self, query: str) -> list[Candidate]:
        folded = _fold(query)
        if "vanspor" in folded or "van spor" in folded:
            return [
                Candidate("Son Dakika Vanspor FK Haberleri", "https://www.sondakika.com/vanspor/", "direct"),
                Candidate("TGRT Vanspor Haberleri", "https://www.tgrthaber.com/vanspor", "direct"),
                Candidate("Kontraspor Van Spor Haberleri", "https://kontraspor.com/haberleri/van-spor", "direct"),
                Candidate("Mynet Vanspor Haberleri", "https://www.mynet.com/haberler/vanspor", "direct"),
                Candidate("Van Havadis Vanspor FK", "https://www.vanhavadis.com/arsiv/van-spor-fk-haberleri", "direct"),
            ]
        if "tekirdag" in folded and "ergene" in folded:
            return [
                Candidate("Son Dakika Ergene Haberleri", "https://www.sondakika.com/ergene/", "direct"),
                Candidate("Haberler Ergene Haberleri", "https://www.haberler.com/ergene/", "direct"),
                Candidate("TGRT Ergene Haberleri", "https://www.tgrthaber.com/ergene", "direct"),
                Candidate("Son Dakika Tekirdag Haberleri", "https://www.sondakika.com/tekirdag/", "direct"),
                Candidate("Haberturk Tekirdag Ergene Haberleri", "https://www.haberturk.com/tekirdag/ergene-haberleri", "direct"),
                Candidate("NTV Tekirdag Ergene Haberleri", "https://www.ntv.com.tr/tekirdag-ergene", "direct"),
                Candidate("Ergene Haber", "https://www.ergenehaber.com/", "direct"),
            ]
        return []

    def _collect_tavily(self, query: str, result: ResearchResult) -> tuple[list[Document], str, str]:
        api_key = str(get_app_config_value("tavily_api_key", "") or "").strip()
        if not api_key:
            result.notes.append("Tavily API key yok")
            return [], "", query
        try:
            import requests  # type: ignore
        except Exception as exc:
            result.notes.append(f"Tavily requests yok: {type(exc).__name__}: {exc}")
            return [], "", query

        for variant in self.query_variants(query):
            payload = {
                "query": variant,
                "search_depth": "advanced",
                "topic": "news" if _is_news_query(variant) else "general",
                "max_results": max(5, min(10, self.max_pages * 2)),
                "include_answer": "advanced",
                "include_raw_content": "text",
                "include_images": False,
            }
            payload.update(_turkish_news_payload_options(variant))
            try:
                response = requests.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=45,
                )
            except Exception as exc:
                result.notes.append(f"Tavily {variant}: {type(exc).__name__}: {exc}")
                continue
            if response.status_code >= 400:
                result.notes.append(f"Tavily HTTP {response.status_code}: {response.text[:220]}")
                continue

            data = response.json()
            docs: list[Document] = []
            for item in data.get("results") or []:
                title = _normalize_spaces(str(item.get("title") or item.get("url") or ""))
                url = _normalize_spaces(str(item.get("url") or ""))
                content = _normalize_spaces(str(item.get("raw_content") or item.get("content") or ""))
                if not url:
                    continue
                score, matched, reason = self.score_text(variant, title, url, content)
                if score <= 0:
                    result.rejected.append(f"Tavily reddedildi: {title or url} ({reason}; eslesen={','.join(matched) or '-'})")
                    continue
                docs.append(Document(title or url, url, content, "Tavily", score, matched))
            if docs:
                docs.sort(key=lambda doc: doc.score, reverse=True)
                return docs[: self.max_pages], str(data.get("answer") or "").strip(), variant
            result.notes.append(f"Tavily ilgili sonuc bulamadi: {variant}")
        return [], "", query

    def _collect_fallback(self, query: str, result: ResearchResult) -> None:
        candidates = self.direct_topic_urls(query)
        if candidates:
            result.used_query = query

        for variant in self.query_variants(query):
            try:
                search_url, results = self._search_urls(variant, limit=self.max_pages * 2, result=result)
            except Exception as exc:
                result.notes.append(f"{variant}: {type(exc).__name__}: {exc}")
                continue
            if results:
                result.search_url = search_url
                result.used_query = variant
                candidates.extend(Candidate(label, href, "search") for label, href in results)
                break
            result.notes.append(f"{variant}: arama saglayicilari sonuc dondurmedi")

        candidates = self._dedupe_candidates(candidates, self.max_pages * 3)
        for candidate in candidates:
            if len(result.docs) >= self.max_pages:
                break
            try:
                title, text, _ = self.fetch_page(candidate.url)
            except Exception as exc:
                result.unreadable.append((candidate.title, f"{candidate.url} ({type(exc).__name__}: {exc})"))
                continue
            if len(_normalize_spaces(text)) < MIN_TEXT_CHARS:
                result.unreadable.append((candidate.title, f"{candidate.url} (sayfadan yeterli metin alinamadi)"))
                continue
            score, matched, reason = self.score_text(result.used_query, title or candidate.title, candidate.url, text)
            if score <= 0:
                result.rejected.append(f"Web reddedildi: {title or candidate.title} ({reason}; eslesen={','.join(matched) or '-'})")
                continue
            result.docs.append(Document(title or candidate.title, candidate.url, text, candidate.provider, score, matched))

    def _search_urls(self, query: str, limit: int, result: ResearchResult) -> tuple[str, list[tuple[str, str]]]:
        providers = []
        jina_key_available = bool(str(get_app_config_value("jina_api_key", "") or "").strip())
        if _is_news_query(query):
            providers = [
                self._search_google_news,
                self._search_bing,
                self._search_google_web,
                self._search_yahoo_news,
                self._search_duckduckgo,
            ]
            if jina_key_available:
                providers.insert(1, self._search_jina)
        else:
            providers = [self._search_bing, self._search_google_web, self._search_duckduckgo]
            if jina_key_available:
                providers.insert(0, self._search_jina)

        collected: list[tuple[str, str]] = []
        primary_url = ""
        errors: list[str] = []
        for provider in providers:
            try:
                search_url, provider_results = provider(query, limit=max(limit * 2, 8))
            except Exception as exc:
                errors.append(f"{provider.__name__}: {type(exc).__name__}: {exc}")
                continue
            filtered = []
            for label, href in provider_results:
                score, matched, reason = self.score_text(query, label, href, "")
                if score > 0:
                    filtered.append((label, href))
                else:
                    result.rejected.append(f"Arama sonucu reddedildi: {label} ({reason}; eslesen={','.join(matched) or '-'})")
            if filtered and not primary_url:
                primary_url = search_url
            collected.extend(filtered)
            collected = _dedupe_links(collected, limit)
            if len(collected) >= limit:
                return search_url, collected

        if collected:
            return primary_url, _dedupe_links(collected, limit)
        if errors:
            raise RuntimeError(" | ".join(errors[:3]))
        return primary_url or _google_news_web_url(query), []

    @staticmethod
    def _dedupe_candidates(candidates: list[Candidate], limit: int) -> list[Candidate]:
        seen_urls: set[str] = set()
        domain_counts: dict[str, int] = {}
        clean: list[Candidate] = []
        for candidate in candidates:
            key = candidate.url.rstrip("/")
            if key in seen_urls:
                continue
            domain = _domain_of(candidate.url)
            if domain and domain_counts.get(domain, 0) >= 2:
                continue
            seen_urls.add(key)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            clean.append(candidate)
            if len(clean) >= limit:
                break
        return clean

    @staticmethod
    def _dedupe_documents(docs: list[Document]) -> list[Document]:
        seen: set[str] = set()
        clean: list[Document] = []
        for doc in sorted(docs, key=lambda item: item.score, reverse=True):
            key = doc.url.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            clean.append(doc)
        return clean

    @staticmethod
    def fetch_page(url: str, timeout: int = 12) -> tuple[str, str, list[tuple[str, str]]]:
        import requests  # type: ignore

        target = (url or "").strip()
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        last_error: Exception | None = None
        try:
            response = requests.get(target, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            title_match = re.search(r"(?is)<title>(.*?)</title>", response.text)
            title = _strip_html(title_match.group(1)) if title_match else target
            text, links = _soup_text_and_links(response.text, target)
            if len(_normalize_spaces(text)) >= 300:
                return title, text, links
            last_error = RuntimeError("sayfadan yeterli metin alinamadi")
        except Exception as exc:
            last_error = exc

        reader_url = "https://r.jina.ai/" + target
        try:
            response = requests.get(reader_url, headers={"User-Agent": USER_AGENT}, timeout=max(timeout, 20))
            response.raise_for_status()
            text = _strip_html(_strip_reader_metadata(response.text))
            title_match = re.search(r"(?im)^Title:\s*(.+)$", response.text)
            title = _normalize_spaces(title_match.group(1)) if title_match else target
            _, links = _soup_text_and_links(response.text, target)
            return title, text, links
        except Exception:
            if last_error:
                raise last_error
            raise

    @staticmethod
    def _search_duckduckgo(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        search_url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        response = requests.get(search_url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        _, links = _soup_text_and_links(response.text, search_url)
        results: list[tuple[str, str]] = []
        for label, href in links:
            parsed = urlparse(href)
            if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
                uddg = parse_qs(parsed.query).get("uddg", [""])[0]
                if uddg:
                    href = urllib.parse.unquote(uddg)
            if "duckduckgo.com" in urlparse(href).netloc:
                continue
            results.append((label, href))
            if len(results) >= limit:
                break
        return search_url, _dedupe_links(results, limit)

    @staticmethod
    def _search_bing(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        search_url = "https://www.bing.com/search?setlang=tr-TR&q=" + urllib.parse.quote(query)
        response = requests.get(search_url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        _, links = _soup_text_and_links(response.text, search_url)
        results: list[tuple[str, str]] = []
        blocked_hosts = {"www.bing.com", "bing.com", "login.live.com", "go.microsoft.com", "support.microsoft.com"}
        for label, href in links:
            parsed = urlparse(href)
            host = parsed.netloc.lower()
            if host in blocked_hosts or host.endswith(".bing.com"):
                continue
            if parsed.scheme in {"http", "https"} and label:
                results.append((label, href))
            if len(results) >= limit:
                break
        return search_url, _dedupe_links(results, limit)

    @staticmethod
    def _search_google_news(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        news_url = "https://news.google.com/rss/search?hl=tr&gl=TR&ceid=TR:tr&q=" + urllib.parse.quote(query)
        response = requests.get(news_url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        payload = getattr(response, "content", None) or response.text.encode("utf-8")
        root = ET.fromstring(payload)
        results: list[tuple[str, str]] = []
        for item in root.findall(".//item"):
            title = _normalize_spaces(item.findtext("title") or "")
            link = _normalize_spaces(item.findtext("link") or "")
            if title and link:
                results.append((title, link))
            if len(results) >= limit:
                break
        return news_url, _dedupe_links(results, limit)

    @staticmethod
    def _search_google_web(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        search_url = "https://www.google.com/search?hl=tr&q=" + urllib.parse.quote(query)
        response = requests.get(search_url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        _, links = _soup_text_and_links(response.text, search_url)
        results: list[tuple[str, str]] = []
        blocked_hosts = {"www.google.com", "google.com", "accounts.google.com", "support.google.com"}
        for label, href in links:
            parsed = urlparse(href)
            if parsed.netloc.lower() in blocked_hosts and parsed.path == "/url":
                target = parse_qs(parsed.query).get("q", [""])[0]
                if target:
                    href = target
                    parsed = urlparse(href)
            host = parsed.netloc.lower()
            if host in blocked_hosts or host.endswith(".google.com"):
                continue
            if parsed.scheme in {"http", "https"} and label:
                results.append((label, href))
            if len(results) >= limit:
                break
        return search_url, _dedupe_links(results, limit)

    @staticmethod
    def _search_yahoo_news(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        search_url = "https://news.search.yahoo.com/search?p=" + urllib.parse.quote(query)
        response = requests.get(search_url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        _, links = _soup_text_and_links(response.text, search_url)
        results: list[tuple[str, str]] = []
        for label, href in links:
            parsed = urlparse(href)
            host = parsed.netloc.lower()
            if "yahoo.com" in host:
                continue
            if parsed.scheme in {"http", "https"} and label:
                results.append((label, href))
            if len(results) >= limit:
                break
        return search_url, _dedupe_links(results, limit)

    @staticmethod
    def _search_jina(query: str, limit: int = 6) -> tuple[str, list[tuple[str, str]]]:
        import requests  # type: ignore

        api_key = str(get_app_config_value("jina_api_key", "") or "").strip()
        if not api_key:
            raise RuntimeError("Jina Search API key yok")
        search_url = "https://s.jina.ai/?q=" + urllib.parse.quote(query)
        response = requests.get(
            search_url,
            headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {api_key}"},
            timeout=25,
        )
        response.raise_for_status()
        text = response.text or ""
        results: list[tuple[str, str]] = []
        blocks = re.split(r"(?im)^\s*Title:\s*", text)
        for block in blocks[1:]:
            title = _normalize_spaces(block.splitlines()[0] if block.splitlines() else "")
            url_match = re.search(r"(?im)^URL Source:\s*(https?://\S+)", block)
            if url_match:
                results.append((title or url_match.group(1), url_match.group(1).strip()))
            if len(results) >= limit:
                break
        if not results:
            for match in re.finditer(r"\[([^\]]{4,140})\]\((https?://[^)]+)\)", text):
                results.append((_normalize_spaces(match.group(1)), match.group(2).strip()))
                if len(results) >= limit:
                    break
        return search_url, _dedupe_links(results, limit)


def _turkish_news_payload_options(query: str) -> dict:
    folded = _fold(query)
    payload: dict = {}
    if "vanspor" in folded or "van spor" in folded:
        payload["exclude_domains"] = ["foxsports.com", "reuters.com", "skysports.com", "espn.com", "theguardian.com"]
    if "tekirdag" in folded and "ergene" in folded:
        payload["exclude_domains"] = ["natlawreview.com", "reuters.com", "skysports.com", "foxsports.com", "theguardian.com"]
    return payload


def _google_news_web_url(query: str) -> str:
    return "https://news.google.com/search?hl=tr&gl=TR&ceid=TR:tr&q=" + urllib.parse.quote(query)


def _visible_browser_note(urls: list[str]) -> str:
    if not urls:
        return ""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            artifact_dir = Path(__file__).resolve().parents[1] / "memory" / "traces" / "artifacts" / "browser"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            stamp = int(time.time() * 1000)
            trace_path = artifact_dir / f"playwright-{stamp}.zip"
            screenshot_path = artifact_dir / f"playwright-{stamp}.png"
            try:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            except Exception:
                pass
            page = context.new_page()
            page.goto(urls[0], wait_until="domcontentloaded", timeout=15000)
            for url in urls[1:3]:
                other = context.new_page()
                other.goto(url, wait_until="domcontentloaded", timeout=15000)
            screenshot_saved: Path | None = screenshot_path
            trace_saved: Path | None = trace_path
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                screenshot_saved = None
            try:
                context.tracing.stop(path=str(trace_path))
            except Exception:
                trace_saved = None
            artifacts = []
            if screenshot_saved:
                artifacts.append(f"screenshot={screenshot_saved}")
            if trace_saved:
                artifacts.append(f"trace={trace_saved}")
            suffix = " (" + ", ".join(artifacts) + ")" if artifacts else ""
            return "Gorunur Playwright tarayicisi acildi." + suffix
    except Exception as exc:
        open_url(urls[0])
        return f"Gorunur Playwright acilamadi ({type(exc).__name__}: {exc}); varsayilan tarayicida acildi."


def _build_research_response(result: ResearchResult, open_browser: bool = False) -> str:
    if not result.docs:
        fallback_url = _google_news_web_url(result.used_query or result.query) if _is_news_query(result.query) else "https://www.google.com/search?q=" + urllib.parse.quote(result.query)
        if open_browser:
            open_url(fallback_url)
        lines = [
            "Kisa cevap:",
            "Bu konuda okunabilir ve alakali kaynak bulamadim; arama sayfasini actim."
            if open_browser
            else "Bu konuda okunabilir ve alakali kaynak bulamadim; arama URL'si onerildi.",
            "",
            "Detaylar:",
            f"- Denenen sorgu: {result.used_query or result.query}",
            f"- Acilan arama: {fallback_url}" if open_browser else f"- Arama URL'si onerildi: {fallback_url}",
        ]
        if result.notes:
            lines.append("- Denenen saglayicilar: " + " | ".join(result.notes[:4]))
        if result.rejected:
            lines.append("- Reddedilen alakasiz kaynaklar: " + " | ".join(result.rejected[:3]))
        return "\n".join(lines)

    first = result.docs[0]
    lines = [f"Arastirma: {result.used_query or result.query}", "", "Kisa cevap:"]
    if result.tavily_answer:
        lines.append(_text_excerpt(result.tavily_answer, 520))
    else:
        lines.append(
            f"{len(result.docs)} alakali kaynak okudum. En belirgin kaynakta {first.title} basligi altinda su bilgiler one cikiyor: "
            f"{_text_excerpt(first.text, 360)}"
        )

    lines.extend(["", "Detaylar:"])
    for index, doc in enumerate(result.docs, start=1):
        matched = f" (eslesen: {', '.join(doc.matched_terms)})" if doc.matched_terms else ""
        lines.append(f"- [{index}] {_text_excerpt(doc.text, 520)}{matched}")

    lines.extend(["", "Kaynaklar:"])
    for index, doc in enumerate(result.docs, start=1):
        lines.append(_source_bullet(index, doc.title, doc.url))

    if result.unreadable:
        lines.extend(["", "Okunamayan kaynaklar:"])
        for index, (label, detail) in enumerate(result.unreadable[:5], start=1):
            lines.append(f"- {index}. {label}: {detail}")

    notes = list(result.notes)
    if result.rejected:
        notes.append("Reddedilen alakasiz kaynaklar: " + " | ".join(result.rejected[:3]))
    if notes:
        lines.extend(["", "Arama notlari:"])
        lines.append("- Denenen saglayicilar: " + " | ".join(notes[:5]))
    if result.search_url:
        lines.append(f"- Arama kaynagi: {result.search_url}")
    if result.browser_note:
        lines.append(f"- Tarayici: {result.browser_note}")
    return "\n".join(lines)


def web_search(query: str, open_results: bool = True) -> str:
    query = (query or "").strip()
    if not query:
        return "Arama sorgusu belirtilmedi."
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    if open_results:
        open_url(url)
        return f"Arama acildi: {query}\nKaynak: {url}"
    return f"Arama URL'si: {url}"


def tavily_search(query: str, max_results: int = 5, search_depth: str = "advanced") -> str:
    agent = ResearchAgent(max_results)
    result = ResearchResult(query=query, used_query=query, intent=_research_intent(query))
    docs, answer, used_query = agent._collect_tavily(query, result)
    if not docs:
        return "Tavily ilgili sonuc bulamadi: " + query + ("\n" + "\n".join(result.notes[:3]) if result.notes else "")
    lines = [f"Tavily arastirma: {used_query}"]
    if answer:
        lines.append(f"Kisa cevap:\n{_text_excerpt(answer, 700)}")
    for index, doc in enumerate(docs[: max(1, min(10, int(max_results or 5)))], start=1):
        lines.append(f"\n[{index}] {doc.title}\nKaynak: {doc.url}\nIcerik: {_text_excerpt(doc.text, 700)}")
    return "\n".join(lines)


def open_and_summarize_url(url: str, max_chars: int = 2500) -> str:
    target = (url or "").strip()
    if not target:
        return "Ozetlenecek URL belirtilmedi."
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    try:
        title, text, _ = ResearchAgent.fetch_page(target)
    except Exception as exc:
        open_url(target)
        return f"Sayfa metni alinamadi ({type(exc).__name__}: {exc}). Tarayicida acildi: {target}"
    max_chars = max(800, min(8000, int(max_chars or 2500)))
    excerpt = text[:max_chars] + (" ..." if len(text) > max_chars else "")
    open_url(target)
    return f"Sayfa acildi ve metin alindi.\nBaslik: {title}\nKaynak: {target}\nMetin onizleme:\n{excerpt}"


def research_web(query: str, max_pages: int = 5, open_browser: bool = False) -> str:
    result = ResearchAgent(max_pages).run(query, open_browser)
    if not result.query:
        return "Arastirma sorgusu belirtilmedi."
    return _build_research_response(result, open_browser=bool(open_browser))


def answer_research_question(query: str, depth: str = "balanced", speak: bool = False) -> str:
    depth_key = (depth or "balanced").strip().lower()
    max_pages = 3 if depth_key in {"quick", "fast", "hizli"} else 6 if depth_key in {"deep", "derin"} else 5
    result = research_web(query, max_pages=max_pages, open_browser=False)
    if speak:
        result += "\n\nSesli okuma notu: Bu yanit sesli okunmaya uygundur."
    return result


def _keyword_score(label: str, href: str, question: str) -> int:
    folded = _fold(f"{label} {href}")
    words = [w for w in re.findall(r"[^\W_]+", _fold(question), flags=re.UNICODE) if len(w) > 3]
    return sum(1 for word in words if word in folded)


def browse_url(url: str, question: str = "", max_pages: int = 2, open_browser: bool = False) -> str:
    target = (url or "").strip()
    if not target:
        return "Gezilecek URL belirtilmedi."
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    max_pages = max(1, min(5, int(max_pages or 2)))
    browser_note = _visible_browser_note([target]) if open_browser else ""
    try:
        title, text, links = ResearchAgent.fetch_page(target)
    except Exception as exc:
        open_url(target)
        return f"Sayfa okunamadi ({type(exc).__name__}: {exc}). Tarayicida acildi: {target}"

    lines = [f"Sayfa: {title}", f"Kaynak: {target}"]
    if browser_note:
        lines.append(browser_note)
    lines.append(f"Metin onizleme:\n{text[:1800] + (' ...' if len(text) > 1800 else '')}")

    ranked_links = sorted(links, key=lambda item: _keyword_score(item[0], item[1], question), reverse=True)
    followed = 0
    for label, href in ranked_links:
        if followed >= max_pages - 1:
            break
        if question and _keyword_score(label, href, question) <= 0:
            continue
        try:
            child_title, child_text, _ = ResearchAgent.fetch_page(href)
            lines.append(f"\nIlgili alt sayfa: {child_title}\nKaynak: {href}\nOnizleme: {child_text[:1200] + (' ...' if len(child_text) > 1200 else '')}")
            followed += 1
        except Exception:
            continue

    if links:
        lines.append("\nBulunan linkler:")
        for label, href in links[:8]:
            lines.append(f"- {label}: {href}")
    return "\n".join(lines)
