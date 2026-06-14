from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalToolIntent:
    tool_name: str
    args: dict


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def _clean_subject(text: str, patterns: tuple[str, ...]) -> str:
    value = str(text or "").strip()
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" ,.!?'\"")


def parse_local_tool_intent(text: str, context_messages: list[dict] | None = None) -> LocalToolIntent | None:
    raw = str(text or "").strip()
    folded = _fold(raw)
    if not folded:
        return None

    reference_only = re.fullmatch(
        r"(?:youtube\s*(?:dan)?\s*)?(?:ac|oynat|cal)(?:\s*(?:onu|oradan))?",
        folded.replace("'", " ").strip(),
    )
    if reference_only and "youtube" in folded:
        for message in reversed(context_messages or []):
            if message.get("role") != "user":
                continue
            prior = parse_local_tool_intent(message.get("content", ""), [])
            if prior and prior.tool_name == "play_media":
                args = dict(prior.args)
                args["provider"] = "youtube"
                return LocalToolIntent("play_media", args)

    if "youtube" in folded and any(word in folded for word in ("ac", "oynat", "cal")):
        explicit = _clean_subject(
            raw,
            (
                r"\b(youtube|youtube'dan|youtubedan|youtube üzerinden|youtube uzerinden)\b",
                r"\b(aç|ac|oynat|çal|cal|lütfen|lutfen)\b",
            ),
        )
        if not explicit:
            for message in reversed(context_messages or []):
                if message.get("role") != "user":
                    continue
                prior = parse_local_tool_intent(message.get("content", ""), [])
                if prior and prior.tool_name == "play_media":
                    args = dict(prior.args)
                    args["provider"] = "youtube"
                    return LocalToolIntent("play_media", args)
        elif explicit:
            return LocalToolIntent("play_media", {"query": explicit, "provider": "youtube", "autoplay": True})

    media_words = ("sarki", "muzik", "album", "klip", "playlist", "parca")
    play_words = ("ac", "cal", "oynat", "dinlet")
    if any(word in folded for word in media_words) and any(word in folded for word in play_words):
        query = _clean_subject(
            raw,
            (
                r"\b(bana|bir|tane|lütfen|lutfen)\b",
                r"\b(şarkılarından|sarkilarindan|şarkısını|sarkisini|şarkı|sarki|müzik|muzik|parça|parca|klip)\b",
                r"\b(açabilir misin|acabilir misin|açar mısın|acar misin|aç|ac|çal|cal|oynat|dinlet)\b",
            ),
        )
        query = re.sub(r"\b(birini|birisi|herhangi birini)\b", " ", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()
        if query:
            return LocalToolIntent("play_media", {"query": query, "provider": "youtube", "autoplay": True})

    app_match = re.search(
        r"(?:bana\s+)?(?P<app>[\w .+\-]+?)\s+(?:uygulamasini|uygulamasını|programini|programını)?\s*"
        r"(?:acabilir misin|açabilir misin|acar misin|açar mısın|ac|aç)\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if app_match and not any(word in folded for word in ("site", "url", "youtube", "sarki", "muzik")):
        app = app_match.group("app").strip()
        app = re.sub(r"^(bana|lütfen|lutfen)\s+", "", app, flags=re.IGNORECASE)
        if app:
            return LocalToolIntent("open_app", {"app_name": app})

    folder_match = re.search(
        r"(?P<path>(?:[a-zA-Z]:\\|\\\\)[^\"']+?)\s+(?:klasorune|klasörüne|klasor|klasör)"
        r"(?:\s+(?:bakabilir misin|bak|listele|incele))?\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if folder_match:
        return LocalToolIntent("list_folder", {"path": folder_match.group("path").strip()})

    return None
