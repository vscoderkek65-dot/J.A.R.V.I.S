from __future__ import annotations

import re


MAX_TRANSCRIPT_CHARS = 1800


def merge_streaming_text(current: str, incoming: str) -> str:
    """Merge cumulative or overlapping streaming transcript fragments."""
    current = " ".join(str(current or "").split())
    incoming = " ".join(str(incoming or "").split())
    if not incoming:
        return current
    if not current:
        return incoming
    if incoming == current or current.endswith(incoming):
        return current
    if incoming.startswith(current):
        return incoming[:MAX_TRANSCRIPT_CHARS]

    max_overlap = min(len(current), len(incoming), 240)
    for size in range(max_overlap, 2, -1):
        if current[-size:].casefold() == incoming[:size].casefold():
            return (current + incoming[size:])[:MAX_TRANSCRIPT_CHARS]

    return f"{current} {incoming}"[:MAX_TRANSCRIPT_CHARS]


def repetition_reason(text: str) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) < 48:
        return ""

    folded = clean.casefold()
    if re.search(r"(.{1,24}?)\1{5,}", folded):
        return "repeated_pattern"

    words = re.findall(r"\w+", folded, flags=re.UNICODE)
    if len(words) >= 18:
        unique_ratio = len(set(words)) / len(words)
        most_common = max(words.count(word) for word in set(words))
        if unique_ratio < 0.22 or most_common >= 10:
            return "repeated_words"

    trigrams = [folded[i:i + 3] for i in range(max(0, len(folded) - 2))]
    if len(trigrams) >= 60 and len(set(trigrams)) / len(trigrams) < 0.16:
        return "low_entropy_text"
    return ""


def sanitize_streaming_transcript(text: str) -> tuple[str, str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return "", "empty"
    reason = repetition_reason(clean)
    if reason:
        return "", reason
    if len(clean) > MAX_TRANSCRIPT_CHARS:
        clean = clean[:MAX_TRANSCRIPT_CHARS].rsplit(" ", 1)[0] + "..."
    return clean, ""
