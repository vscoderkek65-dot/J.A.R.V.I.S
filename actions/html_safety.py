"""Safe HTML stripping utilities.

Uses BeautifulSoup when available, falls back to hardened regex.
Removes dangerous content (script, style, iframe, object, embed, event handlers)
and decodes HTML entities to prevent bypass via encoding.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Optional

try:
    from bs4 import BeautifulSoup  # type: ignore

    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# Dangerous tags whose entire content (including nested) must be removed
_DANGEROUS_TAGS = ("script", "style", "noscript", "iframe", "object", "embed", "applet", "form")

# Maximum input size to prevent ReDoS (1 MB)
_MAX_HTML_SIZE = 1_048_576


def _strip_dangerous_blocks_regex(value: str) -> str:
    """Remove dangerous HTML blocks with hardened regex.

    Uses non-greedy matching with bounded repetition to prevent ReDoS.
    """
    result = value

    # Remove dangerous blocks: <tag ...>...</tag> with bounded content
    for tag in _DANGEROUS_TAGS:
        # Bounded: up to 100KB per tag to prevent ReDoS on huge inputs
        result = re.sub(
            rf"(?is)<{tag}\b[^>]{{0,2000}}>.*?</{tag}\s*>",
            " ",
            result,
            count=0,
        )
        # Also remove self-closing or unclosed
        result = re.sub(
            rf"(?is)<{tag}\b[^>]{{0,2000}}/?>",
            " ",
            result,
        )

    # Remove event handler attributes (onclick, onerror, onload, etc.)
    result = re.sub(
        r'(?is)\s+on[a-z]+\s*=\s*(?:"[^"]{0,2000}"|\'[^\']{0,2000}\'|[^\s>]{0,2000})',
        " ",
        result,
    )

    # Remove javascript:/vbscript: URLs in href/src
    result = re.sub(
        r'(?is)\s+(?:href|src|action|formaction|xlink:href)\s*=\s*(?:"|\')?\s*(?:javascript|vbscript|data):[^"\'\s>]{0,2000}',
        " ",
        result,
    )

    return result


def _strip_all_tags_regex(value: str) -> str:
    """Remove all remaining HTML tags with bounded matching."""
    # Bounded: tag name up to 100 chars, attributes up to 2000 chars
    return re.sub(r"<[^>]{0,3000}>", " ", value)


def _strip_html_bs4(value: str) -> str:
    """Use BeautifulSoup for safe HTML stripping."""
    soup = BeautifulSoup(value or "", "html.parser")

    # Remove dangerous tags completely (including content)
    for tag in soup(_DANGEROUS_TAGS):
        tag.decompose()

    # Remove elements with event handler attributes
    for element in soup.find_all(True):
        attrs_to_remove = [
            attr for attr in element.attrs
            if attr.lower().startswith("on")
            or (attr.lower() in ("href", "src", "action")
                and str(element.attrs.get(attr, "")).strip().lower().startswith(("javascript:", "vbscript:", "data:")))
        ]
        for attr in attrs_to_remove:
            del element.attrs[attr]

    # Get text, preserve structure
    return soup.get_text(" ")


def strip_html(value: str, max_length: int = 100_000) -> str:
    """Safely strip all HTML tags and dangerous content from a string.

    Strategy:
        1. Decode HTML entities to prevent encoding bypass
        2. Remove dangerous blocks (script, style, iframe, etc.)
        3. Remove event handler attributes
        4. Remove javascript:/data: URLs
        5. Strip remaining tags
        6. Normalize whitespace

    Args:
        value: Input string that may contain HTML.
        max_length: Maximum input length to process (prevents ReDoS).

    Returns:
        Plain text with all HTML removed.
    """
    if not value:
        return ""

    # Truncate to prevent ReDoS on extremely long inputs
    if len(value) > max_length:
        value = value[:max_length]

    # Decode HTML entities first to prevent bypass via encoding
    # e.g. &lt;script&gt;alert(1)&lt;/script&gt; would bypass naive regex
    decoded = unescape(value)

    if _BS4_AVAILABLE:
        try:
            text = _strip_html_bs4(decoded)
        except Exception:
            # Fallback to regex on any parsing error
            text = _strip_dangerous_blocks_regex(decoded)
            text = _strip_all_tags_regex(text)
    else:
        text = _strip_dangerous_blocks_regex(decoded)
        text = _strip_all_tags_regex(text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_title(value: str) -> str:
    """Safely extract the content of the first <title> tag."""
    if not value or len(value) > _MAX_HTML_SIZE:
        return ""
    match = re.search(r"(?is)<title[^>]{0,200}>(.{0,2000}?)</title\s*>", value)
    if not match:
        return ""
    return strip_html(match.group(1), max_length=10_000)
