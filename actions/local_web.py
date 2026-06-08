from __future__ import annotations

import re
import unicodedata

from actions.browser import browser_control
from actions.browser_agent import browser_read_url, browser_research
from actions.web_research import (
    answer_research_question,
    browse_url,
    open_and_summarize_url,
    research_web,
    web_search,
)


_DOMAIN_RE = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/[^\s]*)?$", re.IGNORECASE)


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold().replace("ı", "i")


def _clean_query(text: str) -> str:
    query = re.sub(r"\s+", " ", text or "").strip(" \t\r\n'\".,:;")
    query = re.sub(
        r"^(google|google'da|googleda|internette|internet|webde|web'de|tarayicida|tarayici|browser|gorunur|youtube|youtube'da|youtubeda|yt)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n'\".,:;")
    query = re.sub(
        r"^(tarayıcıda|tarayıcı|görünür)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n'\".,:;")

    folded = _fold(query)
    for verb in ("arama yap", "haber ara", "arastir", "araştır", "ozetle", "summarize", "ara", "arat", "ac", "cal", "oynat"):
        suffix = " " + verb
        if folded.endswith(suffix):
            query = query[: -len(suffix)].strip(" \t\r\n'\".,:;")
            break
    return re.sub(r"\s+", " ", query).strip()


def _clean_news_query(text: str) -> str:
    query = _clean_query(text)
    query = re.sub(r"\bvan\s+spor\b", "Vanspor", query, flags=re.IGNORECASE)
    query = re.sub(
        r"\b(bana|bir|en son|son|guncel|güncel|sesli|olarak|oku|okur musun|okuyabilir misin|arastir|araştır|bak|bul)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\bhaberlerini\b", "haberleri", query, flags=re.IGNORECASE)
    query = re.sub(r"\bhaberi\b", "haberleri", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip(" \t\r\n'\".,:;")
    folded = _fold(query)
    if "haber" not in folded:
        query = f"{query} haberleri"
    if "son dakika" not in folded and "guncel" not in folded:
        query = f"{query} son dakika"
    return re.sub(r"\s+", " ", query).strip()


def _wants_research_or_reading(text: str) -> bool:
    folded = _fold(text)
    return any(
        marker in folded
        for marker in (
            "arastir",
            "araştır",
            "haber",
            "guncel",
            "güncel",
            "son dakika",
            "oku",
            "sesli",
            "kavra",
            "ozetle",
            "özetle",
            "incele",
            "nedir",
            "ne demek",
            "hakkinda",
            "hakkında",
            "bilgi ver",
            "karsilastir",
            "karşılaştır",
        )
    )


def _clean_question_query(text: str) -> str:
    query = _clean_query(text)
    query = re.sub(
        r"\b(nedir|ne demek|hakkinda bilgi ver|hakkında bilgi ver|hakkinda bilgi|hakkında bilgi|bilgi ver|karsilastir|karşılaştır)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", query).strip(" \t\r\n'\".,:;")


def _wants_visible_browser(folded: str) -> bool:
    return any(marker in folded for marker in ("tarayici", "tarayÄ±cÄ±", "browser", "gorunur", "gÃ¶rÃ¼nÃ¼r", "ekranda gez"))


def handle_local_web_command(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None

    folded = _fold(raw)

    if _DOMAIN_RE.match(folded):
        return browser_control("open_url", url=raw)

    url_match = re.search(
        r"(?P<url>(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?)",
        folded,
    )
    if url_match and any(marker in folded for marker in ("ozetle", "summarize", "oku", "incele")):
        if _wants_visible_browser(folded):
            return browser_read_url(url_match.group("url"), question=raw, visible=True)
        return open_and_summarize_url(url_match.group("url"))

    if url_match and _wants_visible_browser(folded) and any(marker in folded for marker in ("gez", "arastir", "ara", "incele")):
        return browser_read_url(url_match.group("url"), question=raw, visible=True)

    if url_match and any(marker in folded for marker in ("gez", "arastir", "araştır", "incele")):
        return browse_url(
            url_match.group("url"),
            question=raw,
            open_browser="tarayici" in folded or "tarayıcı" in folded or "browser" in folded,
        )

    open_match = re.match(
        r"^(?:siteyi|sayfayi|url(?:yi|yi)?)?\s*(?P<url>(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?)\s+(?:ac|open)$",
        folded,
    )
    if open_match:
        return browser_control("open_url", url=open_match.group("url"))

    youtube_markers = ("youtube", "youtube'da", "youtubeda", "yt ")
    youtube_verbs = (" ac", " cal", " oynat", " ara")
    if any(marker in folded for marker in youtube_markers) and any(verb in folded for verb in youtube_verbs):
        query = _clean_query(raw)
        if query:
            return browser_control("play_youtube", query=query)

    if _wants_visible_browser(folded) and any(marker in folded for marker in ("arastir", "ara", "haber", "guncel", "son dakika", "oku", "incele", "nedir")):
        query = _clean_news_query(raw) if "haber" in folded else _clean_query(raw)
        if query:
            return browser_research(query, visible=True)

    search_prefix = re.match(
        r"^(?:google(?:'da|da)?|internette|internet(?:te)?|web(?:'de|de)?)\s+(?P<query>.+?)(?:\s+(?:ara|arat|arama yap))?$",
        folded,
    )
    if search_prefix:
        query = _clean_query(raw)
        if query:
            if _wants_research_or_reading(raw):
                if any(marker in folded for marker in ("haber", "son dakika", "guncel", "güncel")):
                    query = _clean_news_query(raw)
                return research_web(
                    query,
                    open_browser="tarayici" in folded or "tarayıcı" in folded or "browser" in folded,
                )
            return browser_control("search", query=query)

    if "haber" in folded and any(
        marker in folded
        for marker in (" ara", " bul", " bak", "guncel", "güncel", "son dakika", "oku", "sesli", "en son")
    ):
        query = _clean_news_query(raw)
        if query:
            return research_web(query, open_browser="tarayici" in folded or "tarayıcı" in folded or "browser" in folded)

    if any(
        marker in folded
        for marker in (" nedir", "ne demek", "hakkinda bilgi", "hakkında bilgi", "bilgi ver", "karsilastir", "karşılaştır")
    ):
        query = _clean_question_query(raw)
        if query:
            return answer_research_question(query, depth="balanced", speak="oku" in folded or "sesli" in folded)

    if any(
        marker in folded
        for marker in ("arastir", "araştır", "webde bak", "internette bak", "tarayicida arastir", "tarayıcıda araştır")
    ):
        query = _clean_query(raw)
        if query:
            return research_web(
                query,
                open_browser="tarayici" in folded or "tarayıcı" in folded or "browser" in folded,
            )

    if folded.startswith(("ara ", "arat ", "arama yap ")):
        query = re.sub(r"^(ara|arat|arama yap)\s+", "", raw, flags=re.IGNORECASE).strip()
        if query:
            if _wants_research_or_reading(query):
                return research_web(_clean_news_query(query) if "haber" in _fold(query) else query)
            return web_search(query)

    if folded.endswith(" ara"):
        query = raw[:-4].strip()
        if query:
            if _wants_research_or_reading(query):
                return research_web(_clean_news_query(query) if "haber" in _fold(query) else query)
            return web_search(query)

    return None
