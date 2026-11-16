"""Sanitize HTML for preview. Stored source is not rewritten."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

__all__ = ["preview_html"]

# Tags allowed in catalogue HTML previews (structure + emphasis only).
_ALLOWED_TAGS = frozenset({
    "a", "b", "br", "code", "em", "i", "li", "ol", "p", "span", "strong",
    "sub", "sup", "u", "ul",
})
_VOID = frozenset({"br"})
_SAFE_HREF = re.compile(r"^(?:#|/|https?://|mailto:)", re.IGNORECASE)
_ON_ATTR = re.compile(r"^on", re.IGNORECASE)


class _AllowlistParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag_l not in _ALLOWED_TAGS:
            self._skip_depth = 1
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            if name is None:
                continue
            n = name.lower()
            if _ON_ATTR.match(n) or n in {"srcdoc", "srcset", "formaction"}:
                continue
            if n in {"href", "src"}:
                v = (value or "").strip()
                if not v or not _SAFE_HREF.match(v):
                    continue
                if v.lower().startswith("javascript:"):
                    continue
                safe_attrs.append(f'{n}="{html.escape(v, quote=True)}"')
                continue
            if n in {"class", "title", "lang", "dir"}:
                safe_attrs.append(f'{n}="{html.escape(value or "", quote=True)}"')
        attr_s = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        if tag_l in _VOID:
            self.parts.append(f"<{tag_l}{attr_s}>")
        else:
            self.parts.append(f"<{tag_l}{attr_s}>")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag_l in _ALLOWED_TAGS and tag_l not in _VOID:
            self.parts.append(f"</{tag_l}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(f"&#{name};")


def preview_html(text: str, locale: str = "") -> str:
    """Allowlist-sanitize HTML for catalogue preview. *locale* is unused."""
    del locale
    if not text:
        return ""
    parser = _AllowlistParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return html.escape(text)
    return "".join(parser.parts)
