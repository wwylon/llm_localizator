"""Translation validation: hard rejections and soft warnings.

A *rejection* means the candidate translation is discarded and the previous
value kept, leaving the key stale. A *warning* is advisory -- the translation is
accepted.

Nothing here performs I/O or knows about any particular project. The glossary is
passed in as a plain dict.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .cldr import required_plural_categories
from .dnt_spans import check_dnt_spans
from .locales import profile
from .icu import satisfied_categories
from .standards import MessageStandard, get_standard

__all__ = [
    "icu_choice_args",
    "GlossaryIssue",
    "ValidationFailure",
    "validate_translation",
    "validate_translation_detailed",
    "glossary_violations",
    "check_translation_length",
    "check_max_chars",
    "check_expansion_band",
    "check_word_count_band",
    "check_fullkey_coherence",
    "check_html_integrity",
    "check_literal_presence",
    "check_untranslated_fragments",
    "check_locale_grammar",
    "check_locale_typography",
    "check_register",
    "check_agent_artifacts",
    "check_translator_meta",
    "source_has_html_tags",
    "term_pattern",
    "source_term_pattern",
]

# Trailing catalogue pollution from models echoing prompt annotations.
_KEY_TRAILER_RE = re.compile(r"\s*\[key:\s*[^\]]+\]\s*", re.IGNORECASE)
# Whole-value quote wrappers left by models ("Translated text").
_WRAPPED_QUOTES_RE = re.compile(r'^["“”„«»](.+)["“”»«]$', re.DOTALL)
# Translator deliberation leaked into product copy (any language).
_META_NOTE_RE = re.compile(
    r"\(\s*(zamiast|instead of|anstatt|plutôt que|بدلاً)\b|"
    r"\bco nie jest naturalne\b|"
    r"\bwhich is not natural\b",
    re.IGNORECASE,
)

# HTML tags that break websites when dropped or invented. Letter after ``<``
# avoids false positives on comparisons like ``a < b``.
_HTML_TAG_RE = re.compile(
    r"</?([A-Za-z][A-Za-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)?)\b[^>]*/?>"
)
_VOID_HTML = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})
_DANGEROUS_URL_RE = re.compile(
    r"""(?ix)(?:href|src)\s*=\s*['"]?\s*(javascript|vbscript|data)\s*:"""
)

# V32 — verbatim literals that must survive translation. ALL-CAPS words are
# deliberately excluded: "OK", "ID" and the like are routinely localised.
_LITERAL_RE = re.compile(
    r"(https?://\S{4,}"              # URLs
    r"|\S+@\S+\.\S+"                 # emails
    r"|[A-Za-z]+_[A-Za-z_]+)"       # snake_case identifiers
)


def source_has_html_tags(text: str) -> bool:
    """Whether ``text`` contains HTML-like tags (not bare ``<`` comparisons)."""
    return _HTML_TAG_RE.search(text or "") is not None


def _html_tag_multiset(text: str) -> dict[str, int]:
    """Count open / close / void-or-self-closing tags by normalized name."""
    counts: dict[str, int] = {}
    for match in _HTML_TAG_RE.finditer(text or ""):
        raw = match.group(0)
        name = match.group(1).lower()
        if raw.startswith("</"):
            key = f"/{name}"
        elif raw.rstrip().endswith("/>") or name in _VOID_HTML:
            key = f"{name}/"
        else:
            key = name
        counts[key] = counts.get(key, 0) + 1
    return counts


def check_html_integrity(
    en_val: str, translated: str, *, force: bool = False,
) -> str | None:
    """Reject when HTML tag structure diverges from the source (V27).

    Runs when the source has tags, or when ``force`` is set (context ``html:
    true``). Inventing tags in a tag-free source is also a failure under
    ``force`` or when the translation introduces tags unprompted.
    """
    src = _html_tag_multiset(en_val)
    tr = _html_tag_multiset(translated)
    introduced = _introduced_dangerous_urls(en_val, translated)
    if introduced:
        return "dangerous URL introduced in translation: " + ", ".join(introduced)
    if not src and not force:
        if tr:
            invented = ", ".join(sorted(tr))
            return f"HTML tags invented in translation: {invented}"
        return None
    if src == tr:
        return None
    missing = sorted(k for k, n in src.items() if tr.get(k, 0) < n)
    extra = sorted(k for k, n in tr.items() if src.get(k, 0) < n)
    parts: list[str] = []
    if missing:
        parts.append(f"missing {missing}")
    if extra:
        parts.append(f"extra {extra}")
    return "HTML tag mismatch: " + "; ".join(parts) if parts else "HTML tag mismatch"


def _introduced_dangerous_urls(source: str, translated: str) -> list[str]:
    """Schemes in ``href``/``src`` that the translation adds and the source lacks."""
    src = Counter(
        m.group(1).casefold() for m in _DANGEROUS_URL_RE.finditer(source or "")
    )
    out = Counter(
        m.group(1).casefold() for m in _DANGEROUS_URL_RE.finditer(translated or "")
    )
    return sorted(scheme for scheme, n in out.items() if n > src.get(scheme, 0))


@dataclass(frozen=True)
class GlossaryIssue:
    """One glossary problem, with an honest confidence signal.

    ``blocking`` distinguishes the two precise rules from the one heuristic
    rule. Dropping a do-not-translate term and using an explicitly forbidden
    variant are both exact string facts, so they reject. "The approved
    translation does not appear" is inflection-blind -- Arabic ``التوزيعة``
    carries a definite-article prefix and will not substring-match an inflected
    form -- so it advises rather than rejects. See ADR-8.
    """

    kind: str  # "missing-dnt" | "forbidden-variant" | "missing-approved"
    term: str
    message: str
    blocking: bool

    def __str__(self) -> str:
        return self.message


def term_pattern(term: str, *, allow_suffix: bool = False) -> str:
    """Build a word-boundary regex for a glossary term.

    Uses explicit lookarounds rather than ``\\b``. Python's ``\\b`` is defined
    against ``\\w``, and for Arabic, Hebrew, and CJK text the resulting boundary
    positions are wrong -- ``\\bterm\\b`` silently fails to match, so glossary
    rules were never actually enforced for exactly the locales that need them
    most. ``(?<!\\w)term(?!\\w)`` is correct for any script that uses spaces.

    For unsegmented scripts (Chinese, Japanese, Thai) no boundary concept
    applies at all; callers should consult the language profile (``segmented``) and treat
    a miss as "cannot verify" rather than "violation". See
    :func:`glossary_violations`.

    ``allow_suffix`` permits inflections: "bid" also matches "bidding". Prefer
    :func:`source_term_pattern` for English source detection — ``\\w*`` is too
    broad and flags derivational forms like "bidding" under the "bid" entry.
    """
    core = re.escape(term)
    tail = r"\w*" if allow_suffix else ""
    return rf"(?<!\w){core}{tail}(?!\w)"


def source_term_pattern(term: str) -> str:
    """Detect a glossary term in English source text.

  Allows simple plural inflection (``trick``/``tricks``, ``bid``/``bids``) but
    not derivational suffixes (``bid``/``bidding``). The old ``\\w*`` suffix
    matched derived forms and demanded the wrong approved translation — e.g.
    Polish ``licytacja`` for "bidding" was flagged because the glossary maps
    ``bid`` → ``zapowiedź``.
    """
    core = re.escape(term)
    return rf"(?<!\w){core}(?:s|es)?(?!\w)"


def _contains(haystack: str, term: str, *, locale: str, allow_suffix: bool = False,
              flags: int = 0) -> bool:
    """Whether ``term`` occurs in ``haystack`` as a whole word.

    For unsegmented scripts, falls back to plain substring containment, since
    word boundaries do not exist in the writing system.
    """
    if not profile(locale).segmented:
        if flags & re.IGNORECASE:
            return term.casefold() in haystack.casefold()
        return term in haystack
    pattern = term_pattern(term, allow_suffix=allow_suffix)
    if flags & re.IGNORECASE:
        # re.IGNORECASE misses ß/SS. Casefold both sides, then match exactly.
        pattern = term_pattern(term.casefold(), allow_suffix=allow_suffix)
        return re.search(pattern, haystack.casefold()) is not None
    return re.search(pattern, haystack, flags) is not None


def _bare_label(text: str) -> str:
    """Letters only, lowercased, placeholders removed: "Ten:" and "ten" compare equal."""
    text = re.sub(r"\{[^{}]*\}|%\(?\w*\)?[sdif]", " ", text or "")
    return " ".join(re.findall(r"[^\W\d_]+", text)).casefold()


# ---- V49 / V50 / V51 (ADR-130)

_DOMAIN_STOP = frozenset("""about after again against their there these those where which while
would could should other people using without within between through before under""".split())


def domain_tokens(prompt_text: str) -> set[str]:
    """Distinctive words of the project description (5+ letters, not common English)."""
    return {w for w in re.findall(r"[^\W\d_]{5,}", (prompt_text or "").casefold())
            if w not in _DOMAIN_STOP}


def check_domain_leak(en_val: str, translated: str, prompt_text: str | None) -> str | None:
    """V49: the output carries two or more distinctive description words the source lacks.

    Models echo the project description into short frames, often translated around the
    proper nouns ("Graj w euchre lub whist przeciwko botom!"); the nouns survive.
    """
    if not prompt_text:
        return None
    words = domain_tokens(prompt_text)
    src = set(re.findall(r"[^\W\d_]+", (en_val or "").casefold()))
    out = set(re.findall(r"[^\W\d_]+", (translated or "").casefold()))
    leaked = sorted((out & words) - src)
    if len(leaked) >= 2:
        return f"leaked project description into the output ({', '.join(leaked[:4])})"
    return None


_MARKDOWN = re.compile(r"\*\*|__|`")


def check_invented_markup(en_val: str, translated: str) -> str | None:
    """V50: markdown the source lacks, or text moved outside a whole-ICU message."""
    for token in ("**", "__", "`"):
        if token in (translated or "") and token not in (en_val or ""):
            return f"invented markup {token!r} not in the source"
    src = (en_val or "").strip()
    out = (translated or "").strip()
    if src.startswith("{") and src.endswith("}") and _ICU_HEAD_ANY_RE.match(src):
        if not out.startswith("{") or not out.endswith("}"):
            return "text moved outside the ICU message"
    return None


_LEAD_SYMBOLS = "~≈±<>×"


def check_leading_symbol(en_val: str, translated: str) -> str | None:
    """V51: a leading approximation/comparison symbol was dropped or spelled out."""
    src = (en_val or "").lstrip()
    if src[:1] and src[0] in _LEAD_SYMBOLS and not (translated or "").lstrip().startswith(src[0]):
        return f"leading symbol {src[0]!r} dropped or spelled out"
    return None


def glossary_answer(source: str, glossary: dict, locale: str) -> str | None:
    """The approved rendering when the whole source is one glossary term (ADR-128).

    "Ten" with ``ten: {pl: dziesiątka}`` -> "Dziesiątka" (the first letter follows
    the source). ``None`` for anything longer, or a term without an approved word.
    """
    if re.search(r"\{[^{}]*\}|%[sd]|\$\{", source):
        return None  # "Run: {id}" is a frame around the term, not the term (keeps {id})
    bare = _bare_label(source)
    if not bare:
        return None
    for term, data in (glossary.get("terms") or {}).items():
        if not isinstance(data, dict) or _bare_label(term) != bare:
            continue
        approved = data.get(locale)
        if not isinstance(approved, str) or not approved.strip():
            return None
        from .normalize import normalize_candidate

        text, _ = normalize_candidate(source, approved.strip(), locale)
        lead = re.match(r"^\W*", source).group(0)
        trail = re.search(r"\W*$", source).group(0)
        return f"{lead}{text}{trail}" if (lead or trail) and not re.search(r"[{}%]", lead + trail) else text
    return None


def glossary_violations(
    en_val: str, translated: str, glossary: dict, locale: str
) -> list[GlossaryIssue]:
    """Return glossary problems, empty if the translation complies.

    Each issue carries a ``blocking`` flag; only blocking ones cause
    :func:`validate_translation` to reject.
    """
    problems: list[GlossaryIssue] = []

    # Do-not-translate terms must survive verbatim into the output. The source
    # side is always the source language, so it uses ordinary word boundaries.
    for term in glossary.get("doNotTranslate", []):
        in_source = re.search(term_pattern(term), en_val) is not None
        if in_source and not _contains(translated, term, locale=locale):
            problems.append(GlossaryIssue(
                "missing-dnt", term,
                f"do-not-translate term '{term}' missing from output",
                blocking=True,
            ))

    for term, data in glossary.get("terms", {}).items():
        # Every rule below is conditional on the *source* actually using this
        # glossary term. Without that gate the forbidden-variant check fires on
        # any homonym: a card-game glossary forbids Arabic 'عرض' as a rendering of
        # "bid", but the same word ordinarily means "view", so the string
        # "Public view only" was reported as a bid mistranslation.
        if not _term_in_source(term, en_val):
            continue

        for bad in data.get(f"{locale}_forbidden", []):
            if _contains_forbidden(translated, bad, locale, approved=data.get(locale)):
                problems.append(GlossaryIssue(
                    "forbidden-variant", term,
                    f"forbidden variant '{bad}' used for glossary term '{term}'",
                    blocking=True,
                ))

        # If the source uses this term (allowing inflections like "bid" ->
        # "bidding") and the glossary has an approved translation, that term
        # should appear -- otherwise a synonym the model invents passes silently
        # just because no forbidden variant was used.
        #
        # Advisory, not blocking: the comparison is exact substring, so any
        # inflected form of the approved term is a false positive. Measured on
        # a production card-game catalogue this rule fires 155 times across pl+ar, a mix of
        # genuine mistranslations and morphology. Real signal, unsafe as a
        # build-breaker.
        approved = data.get(locale)
        # Project-maintained inflected forms (``pl_forms``) are exact and always win;
        # the stem heuristic below stays as the automatic fallback.
        forms = [str(form) for form in data.get(f"{locale}_forms") or [] if form]
        listed_form = any(
            _contains(translated, form, locale=locale, flags=re.IGNORECASE) for form in forms
        )
        if approved and not listed_form and not _contains_morphological(
            translated, approved, locale,
        ):
            # When the whole source is the term ("Ten", "Hearts"), the label is the
            # dictionary form: no inflection excuse, so a missing approved term is a
            # wrong word ("Dziesiętka", an untranslated "Hearts") and rejects (ADR-127).
            whole = _bare_label(en_val) == _bare_label(term)
            problems.append(GlossaryIssue(
                "missing-approved", term,
                f"approved term '{approved}' for glossary term '{term}' missing from output",
                blocking=whole,
            ))
    return problems


@dataclass(frozen=True)
class ValidationFailure:
    id: str
    message: str
    field: str = "translation"
    severity: str = "error"


def check_fullkey_coherence(short_val: str, long_val: str) -> str | None:
    """Advisory warning when a constrained short form diverges from its long sibling."""
    if not short_val.strip() or not long_val.strip():
        return None
    short = short_val.strip()
    long = long_val.strip()
    if short in long or long in short:
        return None
    return (
        f"short form does not appear in fullKey sibling "
        f"({len(short)} vs {len(long)} chars)"
    )


def check_word_count_band(en_val: str, translated: str, locale: str) -> str | None:
    """Advisory warning when word-count ratio is extreme.

    Unsegmented scripts (zh/ja/th/…) do not use spaces the way English does, so
    a 1-token Chinese string vs 16 English words is expected — skip V23 there
    (ADR-48 editor work; use expansion/char bands instead).
    """
    if not profile(locale).segmented:
        return None
    en_words = len(en_val.split())
    tr_words = len(translated.split())
    if en_words < 2:
        return None
    ratio = tr_words / en_words
    if ratio < 0.35:
        return f"word count much lower than source ({tr_words} vs {en_words} EN words)"
    if ratio > 3.0:
        return f"word count much higher than source ({tr_words} vs {en_words} EN words)"
    return None


def classify_failure(reason: str) -> str:
    """The check id for a :func:`validate_translation` rejection reason.

    One mapping for ``validate``, import, the web editor and the translate pipeline, so the
    same defect never carries two different ids.
    """
    if "leaked prompt text" in reason:
        return "V46"
    if "leaked project description" in reason:
        return "V49"
    if "invented markup" in reason or "outside the ICU message" in reason:
        return "V50"
    if "leading symbol" in reason:
        return "V51"
    if "ICU structure" in reason or "ICU select" in reason:
        return "V47"
    if "placeholder" in reason:
        return "V02"
    if "plural" in reason:
        return "V03"
    if "glossary" in reason or "do-not-translate" in reason or "forbidden" in reason:
        return "V04"
    if "HTML" in reason or "dangerous URL" in reason:
        return "V27"
    if "literal" in reason:
        return "V32"
    if "backslash" in reason:
        return "V39"
    if "[key:" in reason.lower() or "wrapped in quotes" in reason:
        return "V43"
    return "V05"


def check_agent_artifacts(en_val: str, translated: str) -> str | None:
    """Hard reject when the model left prompt/key junk in the product string (V43)."""
    if _KEY_TRAILER_RE.search(translated):
        return "translation contains [key: …] trailer (do not echo message keys)"
    en = (en_val or "").strip()
    tr = (translated or "").strip()
    if _WRAPPED_QUOTES_RE.match(tr) and not _WRAPPED_QUOTES_RE.match(en):
        return "translation is wrapped in quotes (strip model quoting)"
    return None


_ICU_HEAD_ANY_RE = re.compile(r"\{\s*(\w+)\s*,\s*(plural|select|selectordinal)\s*,")
_WORD_RE = re.compile(r"[^\W\d_]+")


def _select_keys(span: str) -> frozenset[str]:
    """Branch keys of one ``{arg, select, a {..} b {..}}`` span (top level only)."""
    head = _ICU_HEAD_ANY_RE.match(span)
    if not head:
        return frozenset()
    body = span[head.end():-1]
    keys: list[str] = []
    depth, token = 0, ""
    for ch in body:
        if ch == "{":
            if depth == 0 and token.split():
                keys.append(token.split()[-1])
            depth += 1
            token = ""
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            token += ch
    return frozenset(keys)


def check_icu_structure(en_val: str, translated: str) -> str | None:
    """V47: the translation must keep every ICU argument's kind and select branches.

    A plural rerun once turned ``{won, select, ...}`` into ``plural``: the runtime then
    picks a branch by number and shows the wrong text. Plural categories are checked
    elsewhere (they legitimately differ by locale); select keys are values the code
    passes, so they must match exactly.
    """
    src_heads = sorted(_ICU_HEAD_ANY_RE.findall(en_val or ""))
    if not src_heads:
        return None
    out_heads = sorted(_ICU_HEAD_ANY_RE.findall(translated or ""))
    if src_heads != out_heads:
        want = ", ".join(f"{{{a}, {k}}}" for a, k in src_heads)
        got = ", ".join(f"{{{a}, {k}}}" for a, k in out_heads) or "none"
        return f"ICU structure changed: source has {want}, translation has {got}"
    src_select = {
        _ICU_HEAD_ANY_RE.match(sp).group(1): _select_keys(sp)
        for sp in _icu_spans(en_val) if _ICU_HEAD_ANY_RE.match(sp).group(2) == "select"
    }
    for sp in _icu_spans(translated):
        m = _ICU_HEAD_ANY_RE.match(sp)
        if m.group(2) == "select" and m.group(1) in src_select:
            want_keys, got_keys = src_select[m.group(1)], _select_keys(sp)
            if want_keys != got_keys:
                return (
                    f"ICU select branches changed for {{{m.group(1)}}}: "
                    f"source {sorted(want_keys)}, translation {sorted(got_keys)}"
                )
    return None


def icu_choice_args(text: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """``(argument, kind, select keys)`` for every plural/select span, in order, deduplicated.

    The whole-message ICU prompt (ADR-124) lists these so the model keeps them; V47
    checks the same facts afterwards.
    """
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for sp in _icu_spans(text):
        m = _ICU_HEAD_ANY_RE.match(sp)
        keys = tuple(sorted(_select_keys(sp))) if m.group(2) == "select" else ()
        row = (m.group(1), m.group(2), keys)
        if row not in out:
            out.append(row)
    return out


def _icu_spans(text: str) -> list[str]:
    """Every ``{arg, plural|select…}`` span, nested ones included."""
    out: list[str] = []
    for m in _ICU_HEAD_ANY_RE.finditer(text or ""):
        depth = 0
        for j in range(m.start(), len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[m.start(): j + 1])
                    break
    return out


def check_prompt_leak(en_val: str, translated: str) -> str | None:
    """V46: a tiny source whose translation balloons carries prompt or domain text.

    Placeholder frames such as ``k={k} · silhouette`` gave the model almost nothing to
    translate, and it answered with the app description from the prompt. A translation
    of one or two words is never six or more words, and a short label never grows by
    more than 2.2x plus a little slack.
    """
    def words(text: str) -> int:
        return len(_WORD_RE.findall(_PLACEHOLDER_SPAN_RE.sub(" ", text or "")))

    src_words, out_words = words(en_val), words(translated)
    src_len, out_len = len((en_val or "").strip()), len((translated or "").strip())
    if _ICU_HEAD_ANY_RE.search(en_val or "") or _ICU_HEAD_ANY_RE.search(translated or ""):
        return None  # plural expansion legitimately multiplies the text
    if src_words < 3 and out_words >= max(6, 3 * src_words + 3):
        return f"translation looks like leaked prompt text ({out_words} words for {src_words})"
    if src_len < 40 and out_len > 2.2 * src_len + 15:
        return f"translation looks like leaked prompt text ({out_len} chars for {src_len})"
    return None


_PLACEHOLDER_SPAN_RE = re.compile(r"\{[^{}]*\}")

# A chat answer instead of a translation: "The translation of "X" into Polish is ...".
_CHAT_ANSWER_RE = re.compile(
    r"(?i:\b(translat(ed|ion)\s+(string|text|of)|here\s+is\s+the\s+translation)\b)"
    r"|\b(into|to|in)\s+[A-Z][a-z]+\s+(is|would\s+be)\b"  # "into Polish is": case-sensitive
)


def check_chat_answer(en_val: str, translated: str) -> str | None:
    """The model talked about the translation instead of giving it.

    Scores used to rate these 1.0, because the right word sits inside the sentence and
    the back-translation matches. The source must not contain the phrase itself.
    """
    if not translated or _CHAT_ANSWER_RE.search(en_val or ""):
        return None
    if _CHAT_ANSWER_RE.search(translated):
        return "translation is a chat answer about the translation, not the translation"
    return None


def answer_leak(en_val: str, translated: str) -> str | None:
    """Hard score failure: a chat answer or leaked prompt text (V46 shape)."""
    return check_chat_answer(en_val, translated) or check_prompt_leak(en_val, translated)


def check_translator_meta(en_val: str, translated: str) -> str | None:
    """Advisory: translator notes leaked into short UI labels."""
    if not translated:
        return None
    if not _META_NOTE_RE.search(translated):
        return None
    # Only warn when the English source is a short label (nav / button shaped).
    if len((en_val or "").split()) > 8:
        return None
    return "translation looks like a translator note, not product copy"


def validate_translation_detailed(
    en_val: str, translated: str, locale: str, glossary: dict,
    *, max_chars: int | None = None,
    fullkey_sibling: str | None = None,
    check_whitespace: bool = True,
    check_script: bool = True,
    check_digraphs: bool = True,
    check_max_chars_warn: bool = True,
    check_word_count: bool = True,
    check_fullkey: bool = True,
    check_html: bool | None = None,
    check_untranslated: bool = True,
    check_typography: bool = True,
    standard: MessageStandard | None = None,
) -> tuple[bool, list[ValidationFailure]]:
    """Structured validation result for APIs and import.

    Advisory flags default to on (import/web blur). Pipeline validate passes
    subsets when Length/Script/Digraphs are toggled independently.
    """
    ok, reason = validate_translation(
        en_val, translated, locale, glossary, check_html=check_html,
        standard=standard,
    )
    if not ok:
        return False, [ValidationFailure(classify_failure(reason), reason)]

    warnings: list[ValidationFailure] = []
    from .quality import (
        check_suspicious_digraphs,
        check_whitespace_parity,
    )
    from .script_checks import check_script_issues

    if check_whitespace:
        ws = check_whitespace_parity(en_val, translated)
        if ws:
            warnings.append(ValidationFailure("V17", ws, severity="warning"))
    if check_script:
        for issue in check_script_issues(en_val, translated, locale):
            warnings.append(ValidationFailure("V21", issue, severity="warning"))
    if check_max_chars_warn:
        mc = check_max_chars(translated, max_chars)
        if mc:
            warnings.append(ValidationFailure("V22", mc, severity="warning"))
    if check_word_count:
        wc = check_word_count_band(en_val, translated, locale)
        if wc:
            warnings.append(ValidationFailure("V23", wc, severity="warning"))
    if check_fullkey and fullkey_sibling is not None:
        fk = check_fullkey_coherence(translated, fullkey_sibling)
        if fk:
            warnings.append(ValidationFailure("V24", fk, severity="warning"))
    if check_digraphs:
        dig = check_suspicious_digraphs(translated, locale)
        if dig:
            warnings.append(ValidationFailure("V25", dig, severity="warning"))
    for issue in glossary_violations(en_val, translated, glossary, locale):
        if not issue.blocking:
            warnings.append(ValidationFailure("V13", issue.message, severity="warning"))
    if check_untranslated:
        uf = check_untranslated_fragments(translated, locale)
        if uf:
            warnings.append(ValidationFailure("V33", uf, severity="warning"))
    if check_typography:
        typ = check_locale_typography(translated, locale)
        if typ:
            warnings.append(ValidationFailure("V34", typ, severity="warning"))
        gram = check_locale_grammar(translated, locale)
        if gram:
            warnings.append(ValidationFailure("V45", gram, severity="warning"))
    dnt = check_dnt_spans(en_val, translated)
    if dnt:
        warnings.append(ValidationFailure("V42", dnt, severity="warning"))
    meta = check_translator_meta(en_val, translated)
    if meta:
        warnings.append(ValidationFailure("V44", meta, severity="warning"))
    return True, warnings


def validate_translation(
    en_val: str, translated: str, locale: str, glossary: dict,
    *, check_html: bool | None = None,
    standard: MessageStandard | None = None,
    prompt_text: str | None = None,
) -> tuple[bool, str]:
    """Return ``(ok, reason)``. ``reason`` is empty when ``ok`` is True.

    Rejection families, in order of evaluation:
      0. a backslash the source does not have (V39: truncated or escaped text)
      1. empty / whitespace-only output
      2. placeholder set mismatch (missing or extra)
      3. plural-ness lost, or CLDR category set incomplete for the locale
      4. output longer than ``max(6 x len(EN), 200)`` -- the model explained itself
      5. newlines not present in the source
      6. glossary violations
      7. HTML tag integrity (when source has tags, or ``check_html=True``)
      8. agent artefacts (``[key:]`` trailer / whole-value quotes — V43)
    """
    if not translated or not str(translated).strip():
        return False, "empty or whitespace-only translation"
    if "\\" in translated and "\\" not in en_val:
        return False, "stray backslash in translation (the source has none): text was cut or escaped"
    artifact = check_agent_artifacts(en_val, translated)
    if artifact:
        return False, artifact

    spec = standard or get_standard("icu")
    en_ph = spec.tokens(en_val)
    tr_ph = spec.tokens(translated)
    missing = en_ph - tr_ph
    extra = tr_ph - en_ph
    if missing:
        return False, f"missing placeholders {sorted(missing)}"
    if extra:
        return False, f"extra placeholders {sorted(extra)} not in source"
    counter = getattr(spec, "sequential_counts", None)
    if counter is not None:
        want, got = counter(en_val), counter(translated)
        if want != got:
            return False, (
                f"placeholder count differs: source {dict(want)}, translation {dict(got)}"
            )

    en_plural = spec.plural_categories(en_val)
    if en_plural is not None:
        tr_plural = spec.plural_categories(translated)
        if tr_plural is None:
            return False, "source is an ICU plural but translation is not"
        satisfied = satisfied_categories(tr_plural) if spec.id == "icu" else tr_plural
        missing_cats = required_plural_categories(locale) - satisfied
        if missing_cats:
            return False, (
                f"missing required plural categories for {locale}: {sorted(missing_cats)}"
            )

    if spec.id == "icu":
        structure = check_icu_structure(en_val, translated)
        if structure:
            return False, structure
    if len(translated) > max(len(en_val) * 6, 200):
        return False, "output too long (LLM included explanation)"
    leak = check_prompt_leak(en_val, translated)
    if leak:
        return False, leak
    for extra in (check_domain_leak(en_val, translated, prompt_text),
                  check_invented_markup(en_val, translated),
                  check_leading_symbol(en_val, translated)):
        if extra:
            return False, extra
    if "\n" in translated and "\n" not in en_val:
        return False, "output contains unexpected newlines"

    blocking = [p for p in glossary_violations(en_val, translated, glossary, locale) if p.blocking]
    if blocking:
        return False, "; ".join(p.message for p in blocking)

    force_html = check_html is True
    skip_html = check_html is False
    if not skip_html and (force_html or source_has_html_tags(en_val) or source_has_html_tags(translated)):
        html_issue = check_html_integrity(en_val, translated, force=force_html)
        if html_issue:
            return False, html_issue

    lit = check_literal_presence(en_val, translated)
    if lit:
        return False, lit

    return True, ""

def check_max_chars(translated: str, max_chars: int | None) -> str | None:
    """Return a warning if an explicit character budget is exceeded.

    A hard budget declared in a context note. Unlike the expansion band this is
    a real constraint from a real UI element, and it is what triggers the
    shorten pass during translation.
    """
    if max_chars and len(translated) > max_chars:
        return f"exceeds maxChars budget ({len(translated)} > {max_chars})"
    return None


def check_expansion_band(en_val: str, translated: str, locale: str) -> str | None:
    """Return a warning if the length ratio falls outside the locale's band.

    **Advisory and noisy.** The bands describe how much longer rendered text
    tends to *look*, but this compares character counts, and the two diverge
    badly for scripts that are visually wide yet character-sparse. Measured on
    a production card-game catalogue this fires on 872 of ~1794 pl+ar keys, 782 of them
    "suspiciously short" -- almost all because Arabic omits short vowels and
    ligates, not because anything is wrong. Off by default in ``validate``;
    enable with ``--check-expansion``. See ADR-8.

    Uses rendered display width (CJK full-width = 2) rather than raw character
    count to reduce false positives for Arabic and CJK scripts.
    """
    en_width = _display_width(en_val)
    if en_width < 8:  # too noisy for very short strings
        return None
    band = profile(locale).expansion_band
    if band is None:
        return None

    ratio = _display_width(translated) / en_width
    lo, hi = band
    if ratio < lo:
        return f"suspiciously short ({ratio:.1%} of EN, expected >={lo:.0%})"
    if ratio > hi:
        return f"suspiciously long ({ratio:.1%} of EN, expected <={hi:.0%})"
    return None


def check_translation_length(
    en_val: str, translated: str, locale: str, max_chars: int | None = None
) -> str | None:
    """Both length checks, budget first. Used by the translation pipeline.

    ``validate`` calls the two halves separately so the noisy one can be gated.
    """
    if len(en_val) == 0:
        return None
    return check_max_chars(translated, max_chars) or check_expansion_band(
        en_val, translated, locale
    )


def _display_width(text: str) -> int:
    """Rendered character width: CJK full-width counts as 2, everything else as 1."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_PLURAL_ENDINGS = "s|es|x|e|en|n|er"
_AR_PREFIXES = ("\u0648\u0627\u0644", "\u0628\u0627\u0644", "\u0643\u0627\u0644", "\u0641\u0627\u0644",
                "\u0644\u0644", "\u0627\u0644", "\u0648", "\u0628", "\u0644", "\u0643", "\u0641")
_AR_ARTICLE = "\u0627\u0644"


def _term_in_source(term: str, en_val: str) -> bool:
    """Whether the English source uses ``term`` as a word of its own.

    A placeholder name (``{bid}``) and a hyphenated compound (``double-dummy``) are
    not the term, so neither demands its approved translation.
    """
    plain = _PLACEHOLDER.sub(" ", en_val)
    core = re.escape(term)
    return re.search(rf"(?<![\w-]){core}(?:s|es)?(?![\w-])", plain, re.IGNORECASE) is not None


def _fold(text: str) -> str:
    """Case, combining marks (Arabic harakat, Polish accents) and ``l``-stroke removed."""
    import unicodedata

    decomposed = unicodedata.normalize("NFD", text)
    kept = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return kept.replace("\u0142", "l").replace("\u0141", "L").casefold()


def _contains_morphological(haystack: str, term: str, locale: str) -> bool:
    """Match ``term`` or an inflected form of it for rich-inflection locales.

    Comparison ignores case and combining marks, so ``Stół`` matches ``stół`` and Arabic
    with or without harakat matches. For languages whose profile sets ``inflects``
    (Polish, Arabic) the approved term may also appear inflected:

    * Arabic: the definite article and a one-letter preposition or conjunction may be
      attached, and up to three letters of ending follow (``شريك`` for ``الشريك``).
    * Others: the stem is the folded term minus up to three letters (at least four kept);
      a shorter term must match a whole word plus up to three letters (``stół`` in ``stołu``),
      after dropping a final vowel (``lewa`` in ``lewy``).
    """
    if _contains(haystack, term, locale=locale, flags=re.IGNORECASE):
        return True
    lang = profile(locale)
    hay, folded = _fold(haystack), _fold(term)
    if lang.code == "ar" and " " not in folded:
        base = folded[len(_AR_ARTICLE):] if folded.startswith(_AR_ARTICLE) and len(folded) > 4 else folded
        if base.endswith("\u0629") and len(base) > 3:  # ta marbuta drops in plurals: توزيعة -> توزيعات
            base = base[:-1]
        prefixes = "|".join(re.escape(p) for p in _AR_PREFIXES)
        return re.search(rf"(?<!\w)(?:{prefixes})?{re.escape(base)}\w{{0,3}}(?!\w)", hay) is not None
    if not lang.inflects:
        # Regular plurals and simple endings (Tisch/Tische, table/tables, tournoi/tournois).
        return re.search(rf"(?<!\w){re.escape(folded)}(?:{_PLURAL_ENDINGS})?(?!\w)", hay) is not None
    prefix_len = max(4, len(folded) - 3)
    if prefix_len >= len(folded):
        stem = folded[:-1] if len(folded) >= 4 and folded[-1] in "aeiouy" else folded
        return re.search(rf"(?<!\w){re.escape(stem)}\w{{0,3}}(?!\w)", hay) is not None
    return folded[:prefix_len] in hay


def _contains_forbidden(haystack: str, term: str, locale: str, *, approved: str | None = None) -> bool:
    """A forbidden variant in any case and, for inflecting languages, any inflected form.

    "trik" must also fire on "Triki" and "trikiem" (E9: the exact-word check let them
    through). Stricter than :func:`_contains_morphological` because this one blocks: the
    stem must start a word, and multi-word variants still match exactly.
    """
    if _contains(haystack, term, locale=locale, flags=re.IGNORECASE):
        return True
    lang = profile(locale)
    if not lang.segmented or " " in term.strip():
        return False
    if lang.code == "ar" or not lang.inflects:
        return _contains_morphological(haystack, term, locale)
    folded = _fold(term)
    stem = folded[:-1] if len(folded) >= 4 and folded[-1] in "aeiouyąę" else folded
    if len(stem) < 3:
        return False
    # "trefle" is forbidden only as the plural of the approved "trefl": the shared stem
    # would match the approved form itself, so such a variant matches exactly only.
    if approved and _fold(approved).startswith(stem):
        return False
    return re.search(rf"(?<!\w){re.escape(stem)}\w{{0,4}}(?!\w)", _fold(haystack)) is not None


# Sentence punctuation that follows a URL/email in prose but is not part of it.
_LITERAL_TRAILING = ".,;:!?)]}>'\"’”»。、，！？）"


def _trim_literal(lit: str) -> str:
    if lit.startswith(("http://", "https://")) or "@" in lit:
        return lit.rstrip(_LITERAL_TRAILING)
    return lit


def check_literal_presence(en_val: str, translated: str) -> str | None:
    """V32: verbatim substrings (URLs, emails, identifiers) must survive translation."""
    literals = [lit for lit in (_trim_literal(m) for m in _LITERAL_RE.findall(en_val)) if lit]
    if not literals:
        return None
    missing = [lit for lit in literals if lit not in translated]
    if missing:
        return "literal(s) missing from translation: " + ", ".join(missing)
    return None


def check_untranslated_fragments(translated: str, locale: str) -> str | None:
    """V33: possible English fragment left in a non-English translation (warning).

    Words that are ordinary in the target language (Italian "a", "in") are ignored.
    """
    target = profile(locale)
    if target.code == "en":
        return None
    stopwords = profile("en").stopwords - target.english_word_collisions
    words = re.findall(r"\b[a-z]+\b", translated.lower())
    hits = [w for w in words if w in stopwords]
    if len(hits) >= 2:
        return f"possible English fragment in {locale}: {hits[:4]}"
    return None


def check_register(translated: str, locale: str, register: str) -> str | None:
    """V40: a pronoun of the other register appears (advisory, warning only)."""
    prof = profile(locale)
    other = prof.formal_marker if register == "informal" else prof.informal_marker
    if other is None or register not in ("informal", "formal"):
        return None
    hit = other.search(translated)
    if not hit:
        return None
    return f"{register} register set, but '{hit.group(0)}' is a {'formal' if register == 'informal' else 'informal'} form"


def check_locale_grammar(translated: str, locale: str) -> str | None:
    """V45: the language's grammar heuristics (warning). Rules live in its profile."""
    violations = [
        check.message
        for check in profile(locale).grammar_checks
        if check.fires(translated)
    ]
    return "; ".join(violations) if violations else None


def check_locale_typography(translated: str, locale: str) -> str | None:
    """V34: the language's typography rules (warning). Rules live in its profile."""
    violations = [
        check.message
        for check in profile(locale).typography_checks
        if check.fires(translated)
    ]
    return "; ".join(violations) if violations else None
