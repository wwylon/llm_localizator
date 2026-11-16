"""Non-UI string filters shared by hardcoded detectors.

Keeps event names, wire enums, and listener first-args out of reports even if a
future widget-word rule would otherwise promote them.
"""

from __future__ import annotations

import re

__all__ = [
    "DOM_EVENTS",
    "WIRE_ENUMS",
    "NON_USER_ATTRS",
    "is_non_ui_literal",
    "is_listener_event_arg",
    "is_non_user_attr_value",
]

# Common DOM / Node event types (addEventListener first arg).
DOM_EVENTS = frozenset({
    "abort", "animationend", "animationiteration", "animationstart",
    "beforeinput", "beforeunload", "blur", "canplay", "canplaythrough",
    "change", "click", "close", "compositionend", "compositionstart",
    "compositionupdate", "contextmenu", "copy", "cut", "dblclick",
    "drag", "dragend", "dragenter", "dragleave", "dragover", "dragstart",
    "drop", "durationchange", "emptied", "ended", "error", "focus",
    "focusin", "focusout", "fullscreenchange", "gotpointercapture",
    "input", "invalid", "keydown", "keypress", "keyup", "load",
    "loadeddata", "loadedmetadata", "loadstart", "lostpointercapture",
    "mousedown", "mouseenter", "mouseleave", "mousemove", "mouseout",
    "mouseover", "mouseup", "paste", "pause", "play", "playing",
    "pointercancel", "pointerdown", "pointerenter", "pointerleave",
    "pointermove", "pointerout", "pointerover", "pointerup", "progress",
    "ratechange", "reset", "resize", "scroll", "seeked", "seeking",
    "select", "selectionchange", "slotchange", "stalled", "submit",
    "suspend", "timeupdate", "toggle", "touchcancel", "touchend",
    "touchmove", "touchstart", "transitionend", "volumechange", "waiting",
    "wheel",
})

WIRE_ENUMS = frozenset({
    "human", "machine", "stale", "agent", "imported", "intentional",
    "verified", "locked", "missing", "pending", "ok", "error",
    "get", "post", "put", "patch", "delete", "head", "options",
    "true", "false", "null", "undefined",
})

NON_USER_ATTRS = frozenset({
    "type", "role", "method", "enctype", "rel", "target", "dir",
    "autocomplete", "inputmode", "crossorigin", "referrerpolicy",
})

#: An upper-case SQL statement: ``SELECT id FROM users WHERE …``. Prose such as "Select a file" does not match.
_SQL_STATEMENT = re.compile(
    r"^\s*(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE|DROP\s+TABLE|WITH)\b"
    r".*\b(?:FROM|INTO|SET|TABLE|VALUES|WHERE|JOIN|INDEX)\b"
)
#: Pieces of a regular expression that survived unescaping: ``(?<name>``, ``[^x]``, ``d+),(?``.
_REGEX_FRAGMENT = re.compile(r"\(\?[<:=!P]|\(\?$|\[\^[^\]]+\]|\bd\+\)")
_LISTENER_CALL = re.compile(
    r"""\b(?:addEventListener|removeEventListener|\.on)\s*\(\s*(["'])([^"'\\\n]+)\1""",
)
_ATTR_ASSIGN = re.compile(
    r"""\b(?:setAttribute)\s*\(\s*(["'])([^"'\\\n]+)\1\s*,\s*(["'])([^"'\\\n]*)\3"""
)
_HTML_ATTR = re.compile(
    r"""\b(""" + "|".join(sorted(NON_USER_ATTRS)) + r""")\s*=\s*["']([^"']*)["']""",
    re.I,
)


def is_non_ui_literal(text: str) -> bool:
    """True when *text* is an API/enum token, never product copy."""
    t = (text or "").strip()
    if not t:
        return True
    low = t.casefold()
    # ``close`` / ``DELETE`` are tokens; ``Close``, ``Delete``, ``OK`` are button labels (M2: compare the case).
    if (t == low or t == t.upper()) and (low in DOM_EVENTS or low in WIRE_ENUMS) and t != "OK":
        return True
    if _SQL_STATEMENT.match(t) or _REGEX_FRAGMENT.search(t):
        return True
    if _SVG_PATH.match(t):
        return True  # ``"M12 2L2 7l10 5 10-5z"``: SVG path data
    if _KEYWORD_LIST.match(t):
        return True  # ``"spicetify, spotify, customization"``: SEO keywords / tags, not a message
    if len(t) <= 200 and ("." in t or "#" in t) and _CSS_SELECTOR.match(t) and re.search(r"(?:^|[\s>+~,])[.#][A-Za-z_]|[a-z][.#][A-Za-z_]", t):
        return True
    return False


#: Three or more comma-separated lowercase terms of one or two words each: SEO keywords or tag lists.
_KEYWORD_LIST = re.compile(r"^[a-z0-9][a-z0-9+#.-]*(?: [a-z0-9+#.-]+)?(?:, ?[a-z0-9][a-z0-9+#.-]*(?: [a-z0-9+#.-]+)?){2,}$")
#: SVG path data: a move command, then only path commands, numbers, commas and spaces.
_SVG_PATH = re.compile(r"^[Mm]\s*-?[\d.]+[\s,]*-?[\d.]+[MmLlHhVvCcSsQqTtAaZz\d.,\s-]*$")
#: A CSS selector list (``.user-info .name``, ``header+div article,.post .article``, ``a:nth-child(1)``).
_CSS_TAG = (
    r"(?:a|abbr|article|aside|b|blockquote|body|button|code|dd|div|dl|dt|em|figure|footer|form|h[1-6]|header|i|img|"
    r"input|label|li|main|nav|ol|p|picture|pre|section|select|small|span|strong|table|tbody|td|th|thead|tr|ul)"
)
_CSS_COMPOUND = rf"(?:{_CSS_TAG}(?:[.#:][\w()-]+)*|[.#][\w-]+(?:[.#:][\w()-]+)*)"
_CSS_SELECTOR = re.compile(rf"^{_CSS_COMPOUND}(?:(?: ?[>+~,] ?| )(?![ >+~,]){_CSS_COMPOUND})*$")


def is_listener_event_arg(line: str, text: str) -> bool:
    """True when *text* is the first string arg of add/removeEventListener or .on()."""
    if not text:
        return False
    for match in _LISTENER_CALL.finditer(line or ""):
        if match.group(2) == text:
            return True
    return False


def is_non_user_attr_value(line: str, text: str) -> bool:
    """True when *text* is the value of a non-user-facing HTML/DOM attribute."""
    if not text:
        return False
    for match in _HTML_ATTR.finditer(line or ""):
        if match.group(2) == text:
            return True
    for match in _ATTR_ASSIGN.finditer(line or ""):
        if match.group(2).casefold() in NON_USER_ATTRS and match.group(4) == text:
            return True
    return False
