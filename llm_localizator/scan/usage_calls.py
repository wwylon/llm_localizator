"""Where source code already routes text through the i18n layer (ADR-120).

One definition shared by ``check-keys`` (which keys are used), the scanner (which
literals are already routed, so not hardcoded) and the QA crawl locator. Before
this module each kept its own regexes and they drifted.

Pure: text in, findings out.
"""

from __future__ import annotations

from .views import blank_match

import re
from contextvars import ContextVar
from collections import defaultdict

__all__ = [
    "ROUTED_CALLS", "ROUTED_LINE", "is_routed_callee", "DATA_I18N_ATTRS", "KeyUsage",
    "blank_block_comments", "collect_key_usage", "collect_ecosystem_usage", "ECOSYSTEM_SUFFIXES", "EXTRA_ROUTED",
    "ROUTED_TABLE", "routed_names", "routed_re",
]

#: Callees whose string arguments are already routed through the i18n layer.
ROUTED_CALLS = frozenset({
    "t", "i18n.t", "uiT", "$t", "this.$t", "gettext", "ngettext", "tr", "__", "_",
    "formatMessage", "intl.formatMessage", "useTranslations", "getTranslations",
    "translate", "i18next.t", "props.t", "this.props.t", "L", "this.L", "uiLocale.t",
    "i18n.__", "i18n._", "i18n.__n", "$_", "$format", "$formatMessage", "gettext_lazy", "pgettext", "npgettext",
})
#: A dotted callee is routed when its last segment is one of these (``i18n.__``, ``this.i18n.t``).
ROUTED_TAILS = frozenset({"t", "$t", "__", "_", "$_", "tr", "gettext", "ngettext", "formatMessage", "$format"})


#: Project-specific translate wrappers (``[scan] t_functions``), set for the duration of one scan.
EXTRA_ROUTED: ContextVar[frozenset[str]] = ContextVar("extra_routed", default=frozenset())


def is_routed_callee(callee: str | None) -> bool:
    if not callee:
        return False
    extra = EXTRA_ROUTED.get()
    return callee in ROUTED_CALLS or callee.rsplit(".", 1)[-1] in ROUTED_TAILS or callee in extra or callee.rsplit(".", 1)[-1] in extra
#: User-visible attributes the shipped runtime fills from ``data-i18n-<attr>``.
DATA_I18N_ATTRS = ("title", "placeholder", "aria-label", "alt")


# ---------------------------------------------------------------- the routed-call table (M3, audit D1)
#: Every scanner's "already routed" pattern, in one place. Each row is ``(template, alternatives)``: the alternatives
#: are joined with ``|`` (in this order) and put where the template says ``{names}``. Scanners used to keep their own
#: copies (``literals._ROUTED*``, ``propdef._ROUTED_CALL``, ``js_context._ROUTED_FALLBACK``, ``raw_js._ALREADY_I18N``,
#: ``next_intl._ALREADY_ROUTED``, ``content._ROUTED``); a new translate call now goes into one row here.
_LITERAL_NAMES = (
    r"i18n\.t", r"i18n\.__", r"gettext(?:_lazy|_noop)?", r"ngettext", r"pgettext", r"npgettext",
    r"gotext\.Get[A-Za-z]*", r"NSLocalizedString", r"String\(localized:", r"esc_html__", r"esc_attr__",
    r"esc_html_e", r"__", r"_e", r"_x", r"_n", r"getString", r"getMessage", r"GetString", r"tr", r"trans",
    r"translate", r"T", r"t", r"_", r"L",
)
ROUTED_TABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    # A source line that routes something (cheap per-line guard for line scanners).
    "line": ("{names}", (
        r"\bt\s*\(", r"i18n\.t\(", r"\buiT\s*\(", r"data-i18n", r"<Trans[\s>/]", r"<FormattedMessage",
        r"(?<![\w$])(?:i18n\.)?__\s*\(", r"\$_\s*\(", r"\$format\s*\(",
    )),
    # Calls that hand English text to a translation layer in the literal languages (English-as-key ecosystems):
    # gettext family, Qt/C++ ``tr``, Swift ``NSLocalizedString``/``String(localized:)``, PHP/WordPress
    # ``__``/``_e``/``esc_html__``, Go ``gotext.Get``/``T``, Java/Android ``getString``/``getMessage``, and ``L``, a
    # project's own one-letter wrapper (``func L(_ en: String) -> String``, pool D: highball).
    "literal_call": (r"(?<![\w$.])(?:{names})\s*\(", _LITERAL_NAMES),
    # The quoted first argument of one of those calls, or C# ``Localizer["…"]``. ``\\.`` is an escaped character;
    # ``[^\\]`` keeps the alternatives disjoint so an unterminated ``t("...`` cannot backtrack exponentially.
    "literal_arg": (
        r"""(?<![\w$])(?:{names})\s*\(\s*(["'`])((?:\\.|(?!\1)[^\\])*)\1"""
        r"""|(?<!\w)\w*[Ll]ocalizer\s*\[\s*(["'])((?:\\.|(?!\3)[^\\])*)\3""",
        _LITERAL_NAMES,
    ),
    # ``'text'.tr()`` / ``"text".tr`` (Dart easy_localization, Ruby): the literal comes first.
    "literal_suffix": (r"""(["'])((?:\\.|(?!\1)[^\\\n])*)\1\s*\.\s*(?:{names})\b""", ("tr", "translate", "i18n")),
    # ``t("key") || "Fallback"`` in JavaScript: the literal after it is the catalogue's fallback.
    "js_fallback": (r"(?<![\w$.])(?:{names})\s*\((?:[^()]|\([^()]*\))*\)\s*(?:\|\||\?\?|:)\s*$", (
        r"t", r"uiT", r"i18n\.t", r"\$t", r"tr", r"gettext", r"L",
    )),
    # QML: Qt's own, KDE ``i18n*``, and a project's helper object (``I18n.t("key", "FALLBACK")``, ``Tr.tr(...)``).
    "qml_call": (r"\b(?:{names})\s*\(", (
        r"qsTr\w*", r"qsTranslate", r"[iI]18[nN]\w*", r"tr", r"(?:[A-Za-z_]\w*\.)(?:t|tr|translate)",
    )),
    # Lines routed through a known i18n call or wrapper other than next-intl: react-i18next, react-intl, vue-i18n,
    # rails, laravel, django, angular.
    "next_intl_line": ("{names}", (
        r"<Trans[\s>/]", r"<FormattedMessage", r"\$t\s*\(", r"this\.\$t\s*\(", r"I18n\.t\s*\(", r"\| translate\b",
        r"\| i18n\b", r"<%= t\(", r"__\s*\(", r"@lang\s*\(", r"{%[-\s]*trans", r"{%[-\s]*blocktrans", r"_\(\s*[\"']",
    )),
    # Lines the raw-JS scanner treats as already translated.
    "raw_js_line": ("{names}", (
        r"i18n\.t\(", r"data-i18n", r"uiLocale\.t\(", r"\buiT\s*\(", r"<Trans[\s>/]", r"<FormattedMessage",
        r"\$t\s*\(", r"__\s*\(", r"@lang\s*\(",
    )),
    # A content-file value that is a lookup, not text: ``%key%``, ``__MSG_x__``, ``${…}``, ``{{…}}``, ``@string/x``.
    "content_value": (r"^(?:{names})", (r"%[\w.\-]+%", r"__MSG_\w+__", r"\$\{", r"\{\{", r"@string/", r"\$\(")),
}


def routed_names(kind: str, extra=()) -> str:
    """The ``|``-joined alternatives of one table row, plus *extra* plain names (escaped)."""
    names = "|".join(ROUTED_TABLE[kind][1])
    if extra:
        names += "|" + "|".join(re.escape(n) for n in extra)
    return names


def routed_re(kind: str, extra=(), flags: int = 0) -> re.Pattern[str]:
    """The compiled pattern of one table row (``extra``: the project's ``[scan] t_functions``)."""
    return re.compile(ROUTED_TABLE[kind][0].replace("{names}", routed_names(kind, extra)), flags)


#: A source line that routes something (cheap per-line guard for line scanners).
ROUTED_LINE = routed_re("line")

_ATTR_ALT = "|".join(re.escape(a) for a in DATA_I18N_ATTRS)
_KEY_OK = re.compile(r"^[A-Za-z0-9_][\w.\-:/]*$")
# i18n.t / uiT('key' …) anywhere; a bare t('key' …) only when the key is dotted.
_CALL = re.compile(
    r"""(?:\b(?:i18n\.t|i18n\.__|uiT)|(?<![\w$.])(?:this\.)?\$(?:t|_|format)|(?<![\w$.])t)\(\s*"""
    r"""(?:(['"])((?:(?!\1)[^\\\n])*)\1|`([^`\n]*)`|([^)'"`\s][^),]*))""")
_ATTR = re.compile(rf"""data-i18n(?:-(?:{_ATTR_ALT}))?\s*=\s*(?:(['"])([^'"\n]*)\1|\{{)""")
_SET_ATTR = re.compile(
    r"""setAttribute\(\s*['"]data-i18n(?:-[\w-]+)?['"]\s*,\s*(?:(['"])([^'"\n]*)\1|[^)]*)""")
_PROP_ATTR = re.compile(
    rf"""['"]data-i18n(?:-(?:{_ATTR_ALT}))?['"]\s*:\s*(?:(['"])([^'"\n]*)\1|[^,}}]*)""")
# Only block comments that open a line: `// games/*.js` must not start one.
_BLOCK_COMMENT = re.compile(r"^[ \t]*/\*.*?\*/|<!--.*?-->", re.S | re.M)


def blank_block_comments(text: str) -> str:
    """Block and HTML comments hold usage examples, not usage; keep line numbers."""
    return _BLOCK_COMMENT.sub(blank_match, text)


#: Element or attribute a key renders into -> the role the translator needs (ADR-129).
_TAG_ROLES = {
    "button": "button label: imperative verb", "a": "link or button label",
    "th": "table column header: noun phrase", "td": "table cell",
    "h1": "page title", "h2": "section title", "h3": "section title", "h4": "heading",
    "h5": "heading", "h6": "heading", "title": "window title",
    "label": "form field label: noun phrase", "dt": "field label: noun phrase",
    "legend": "group label", "option": "option in a list", "summary": "expandable section title",
    "caption": "caption",
}
_ATTR_ROLES = {
    "title": "tooltip", "placeholder": "input placeholder: short hint",
    "aria-label": "screen-reader label", "alt": "image alt text",
}
_OPEN_TAG = re.compile(r"<\s*([A-Za-z][\w-]*)[^<>]*$")


def _role_at(text: str, start: int, attr: str | None) -> str | None:
    if attr:
        return _ATTR_ROLES.get(attr)
    m = _OPEN_TAG.search(text[max(0, start - 400):start])
    return _TAG_ROLES.get(m.group(1).lower()) if m else None


class KeyUsage:
    """Keys a set of files uses: literal keys, dynamic prefixes, unresolvable sites."""

    def __init__(self) -> None:
        self.keys: dict[str, list[str]] = defaultdict(list)
        self.prefixes: set[str] = set()
        self.dynamic: list[str] = []
        #: key -> UI role from the element or attribute it is rendered into.
        self.roles: dict[str, str] = {}
        #: keys found by the per-ecosystem collector; compared without their namespace prefix.
        self.eco: set[str] = set()
        #: keys found by the per-ecosystem collector; compared without their namespace prefix.
        self.eco: set[str] = set()

    def literal(self, key: str, where: str, *, bare_call: bool = False) -> None:
        key = key.strip()
        if "${" in key or "{{" in key or "{%" in key:
            self.partial(key, where)
            return
        if not _KEY_OK.match(key) or (bare_call and "." not in key):
            return
        self.keys[key].append(where)

    def partial(self, text: str, where: str) -> None:
        head = re.split(r"\$\{|\{\{|\{%", text, maxsplit=1)[0]
        if head:
            self.prefixes.add(head)
        else:
            self.dynamic.append(where)

    def covers(self, key: str) -> bool:
        """Used literally, or under a dynamic prefix."""
        return key in self.keys or any(key.startswith(p) for p in self.prefixes)


def _concatenated(text: str, end: int) -> bool:
    return text[end:end + 40].lstrip().startswith("+")


def collect_key_usage(text: str, rel: str, usage: KeyUsage) -> None:
    """Add every i18n key ``text`` (one file, ``rel`` for locations) uses to ``usage``."""
    text = blank_block_comments(text)
    line_starts = [0]
    line_starts.extend(i + 1 for i, ch in enumerate(text) if ch == "\n")

    def where(pos: int) -> str:
        lo, hi = 0, len(line_starts)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid
        return f"{rel}:{lo + 1}"

    for m in _CALL.finditer(text):
        bare = not m.group(0).startswith(("i18n", "uiT", "$", "this."))
        if m.group(2) is not None:
            if _concatenated(text, m.end()):
                usage.partial(m.group(2) + "${", where(m.start()))
            else:
                usage.literal(m.group(2), where(m.start()), bare_call=bare)
        elif m.group(3) is not None:
            usage.literal(m.group(3), where(m.start()), bare_call=bare)
        elif not bare:
            usage.dynamic.append(where(m.start()))
    for pattern in (_ATTR, _SET_ATTR, _PROP_ATTR):
        for m in pattern.finditer(text):
            if m.group(2) is not None:
                if _concatenated(text, m.end()):
                    usage.partial(m.group(2) + "${", where(m.start()))
                else:
                    usage.literal(m.group(2), where(m.start()))
                    attr = re.search(r"data-i18n-([a-z-]+)", m.group(0))
                    role = _role_at(text, m.start(), attr.group(1) if attr else None)
                    if role and pattern is _ATTR:
                        usage.roles.setdefault(m.group(2).strip(), role)
                    elif role and attr:
                        usage.roles.setdefault(m.group(2).strip(), role)
            else:
                usage.dynamic.append(where(m.start()))


# ---------------------------------------------------------------- other ecosystems (ADR-141)
_Q = r"""(?:"([^"\\\n]+)"|'([^'\\\n]+)')"""
#: group -> patterns whose first non-empty capture is a catalogue key.
_ECOSYSTEM_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "android": (
        re.compile(r"\bR\.(?:string|plurals|array)\.(\w+)"),
        re.compile(r"@(?:string|plurals|array)/(\w+)"),
    ),
    "swift": (
        re.compile(r"\bNSLocalizedString\(\s*" + _Q),
        re.compile(r"\bString\(\s*localized:\s*" + _Q),
        re.compile(r"\bLocalizedStringKey\(\s*" + _Q),
    ),
    "java": (
        re.compile(r"\b(?:getString|getMessage|getObject)\(\s*" + _Q),
        re.compile(r"#\{([\w.\-]+)\}"),
        re.compile(r"<fmt:message\s+key\s*=\s*" + _Q),
    ),
    "csharp": (
        re.compile(r"\bResources\.(\w+)"),
        re.compile(r"\b_?[Ll]ocalizer\[\s*" + _Q),
        re.compile(r"\bGetString\(\s*" + _Q),
        re.compile(r"\bx:Uid\s*=\s*" + _Q),
    ),
    "dart": (
        re.compile(r"\bAppLocalizations\.of\([^)]*\)!?\.(\w+)"),
        re.compile(r"\b(?:context\.)?l10n\.(\w+)"),
        re.compile(r"\bS\.of\([^)]*\)\.(\w+)"),
        re.compile(_Q + r"\.tr\(\)"),
    ),
    "rails": (
        re.compile(r"\bI18n\.(?:t|translate)\(?\s*" + _Q),
        re.compile(r"(?<![\w.])t\(\s*" + _Q),
    ),
    "fluent": (
        re.compile(r"\b(?:fl|t)!\(\s*" + _Q),
    ),
}
_SUFFIX_GROUPS = {
    ".kt": ("android",), ".java": ("android", "java"), ".xml": ("android",),
    ".swift": ("swift",), ".m": ("swift",), ".mm": ("swift",),
    ".cs": ("csharp",), ".cshtml": ("csharp",), ".razor": ("csharp",), ".xaml": ("csharp",),
    ".dart": ("dart",), ".rb": ("rails",), ".erb": ("rails",), ".rs": ("fluent",),
}
#: Source suffixes read by the per-ecosystem collector (besides the JavaScript family).
ECOSYSTEM_SUFFIXES = tuple(_SUFFIX_GROUPS)


def collect_ecosystem_usage(text: str, rel: str, suffix: str, usage: KeyUsage) -> None:
    """Keys used through Android ``R.string``, Swift ``NSLocalizedString``, .NET ``Resources.X``, Flutter ``l10n.x`` and friends."""
    groups = _SUFFIX_GROUPS.get(suffix.lower())
    if not groups:
        return
    text = blank_block_comments(text)
    for group in groups:
        for pattern in _ECOSYSTEM_PATTERNS[group]:
            for m in pattern.finditer(text):
                key = next((g for g in m.groups() if g), "").strip()
                if not key:
                    continue
                usage.literal(key, f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
                usage.eco.add(key)

