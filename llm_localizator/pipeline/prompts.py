"""Prompt construction for translation.

The domain sentence is configurable (``[prompt] domain``) rather than hardcoded
to any one product. Everything else here is generic translation instruction plus
whatever guidance the project supplied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.cldr import required_plural_categories
from ..core.locales import profile
from ..core.icu import extract_placeholders, extract_plural_categories
from ..core.locale_policy import LocalePolicy

__all__ = [
    "BatchItem",
    "PROMPT_FAMILIES",
    "build_batch_prompt",
    "build_batch_prompt_parts",
    "build_single_prompt",
    "build_single_prompt_parts",
    "build_shorten_prompt",
    "build_backtranslate_prompt",
    "build_batch_backtranslate_prompt",
    "build_refine_prompt",
    "build_icu_span_prompt",
    "build_fragment_prompt",
    "build_icu_message_prompt_parts",
    "frame_hint",
    "BATCH_SCHEMA",
    "normalize_family",
]

BATCH_SCHEMA: dict = {"type": "array", "items": {"type": "string"}}

# chat = full instruction stack (default). mt_chat = shorter rules for
# MT-oriented chat models (e.g. TranslateGemma) that overfit dense rule lists.
PROMPT_FAMILIES = frozenset({"chat", "mt_chat"})

_REGISTER_LINES = {
    "informal": "Use informal second person (tu / du / ty / أنت) throughout where applicable.",
    "formal": "Use formal second person (vous / Sie / Pan/Pani / حضرتك) throughout where applicable.",
}

# Key-name fragment → UI role hint injected as [role: …] per-item annotation.
_ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bbutton\b", re.IGNORECASE), "button label"),
    (re.compile(r"\b(?:title|header|heading)\b", re.IGNORECASE), "title"),
    (re.compile(r"\b(?:placeholder|hint)\b", re.IGNORECASE), "placeholder"),
    (re.compile(r"\b(?:tooltip|tip)\b", re.IGNORECASE), "tooltip"),
    (re.compile(r"\b(?:error|err)\b", re.IGNORECASE), "error message"),
    (re.compile(r"\blabel\b", re.IGNORECASE), "label"),
    (re.compile(r"\btab\b", re.IGNORECASE), "tab label"),
    (re.compile(r"\bmenu\b", re.IGNORECASE), "menu item"),
]

# Matches strings that look like technical identifiers rather than natural language.
_CODE_LIKE_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"          # ALL_CAPS_CONSTANT (PDF, API are words)
    r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"             # snake_case
    r"|[a-z][a-z0-9]*[A-Z][a-z0-9]*[A-Z][a-zA-Z0-9]*)$"  # getUserName; iPhone is a word
)
_KEY_WORD_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[_.\-/]+")


def _role_from_key(key: str) -> str:
    """Derive a UI role hint from a message key, or return empty string."""
    words = _KEY_WORD_SPLIT.sub(" ", key)
    for pattern, role in _ROLE_PATTERNS:
        if pattern.search(words):
            return role
    return ""


def _is_code_like(source: str) -> bool:
    """True when the source looks like a technical identifier, not a UI string."""
    s = source.strip()
    return bool(s and _CODE_LIKE_RE.match(s))


@dataclass
class BatchItem:
    source: str
    context: str = ""
    llm_note: str = ""
    ui_role: str = ""  # from the element the key renders into (ADR-129)
    pivot: str | None = None
    max_chars: int | None = None
    examples: list[tuple[str, str]] | None = None  # (en, target) few-shots
    siblings: list[tuple[str, str]] | None = None  # related on-screen pairs
    image_b64: str | None = None  # base64 screenshot, sent alongside the prompt
    prompt_source: str | None = None  # masked source sent to the model
    placeholder_mask: dict[str, str] | None = None  # token -> original `{name}`
    message_key: str = ""  # catalogue key path for disambiguation
    html: bool = False  # source carries HTML that must be preserved
    incomplete: list[str] | None = None  # context-completeness lint reasons
    block_translate: bool = False  # needs_context — do not call the model
    glossary_note: str = ""  # compact [glossary: …] from glossary_hits
    pivot_locale: str = ""   # locale of the pivot translation, e.g. "en-GB"
    file_note: str = ""      # namespace-level translator note from context/_note
    register: str = ""       # per-key "formal" / "informal" override
    gender: str = ""         # grammatical gender of the entity a placeholder stands for
    group: str = ""          # sentence this key is a fragment of
    group_parts: list[tuple[str, str]] | None = None  # (key, source) of the other fragments
    risk: str = "medium"     # "low" | "medium" | "high" from risk_level()
    # Non-ICU standards. The prompt lists these tokens and must not mask braces.
    native_standard: bool = False
    preserve_tokens: tuple[str, ...] = ()
    # Why the previous attempt was discarded; set only on a retry.
    previous_rejection: str | None = None
    # Multi-sample agreement, set by the translate loop; never rendered in a prompt.
    sample_consistency: float | None = None
    # Retrieval trace from the context assembler; shown by ``suggest --explain``, never rendered.
    trace: list[str] = field(default_factory=list)
    # Short placeholder frame (ADR-124): ``{"{rank}": "Ace", ...}`` sample values to show.
    frame_samples: dict[str, str] | None = None
    # Why the ICU route (whole message, then fragments) failed; set by the engine, never rendered.
    icu_failure: str | None = None

    def text_for_prompt(self) -> str:
        return self.prompt_source if self.prompt_source is not None else self.source


def rejection_tag(reason: str | None) -> str:
    """``[previous attempt rejected: …]`` for a retry prompt, or ``""``."""
    text = " ".join((reason or "").split())
    if not text:
        return ""
    if len(text) > 160:
        text = text[:157] + "..."
    return f"[previous attempt rejected: {text}]"


def _item_annotations(item: BatchItem) -> str:
    bits: list[str] = []
    if item.file_note:
        bits.append(f"[file note: {item.file_note}]")
    if item.message_key:
        bits.append(f"[key: {item.message_key}]")
        role = item.ui_role or _role_from_key(item.message_key)
        if role:
            bits.append(f"[role: {role}]")
    if item.context:
        bits.append(f"[context: {item.context}]")
    if item.llm_note:
        bits.append(f"[translator note: {item.llm_note}]")
    if item.register:
        bits.append(f"[register: {item.register}]")
    if item.gender:
        bits.append(f"[gender: {item.gender}]")
    if item.group and item.group_parts:
        parts = "; ".join(f"{k}: {s!r}" for k, s in item.group_parts)
        bits.append(
            f"[sentence fragment: '{item.group}' is joined with {parts} — "
            "translate so the pieces read as one sentence]"
        )
    if item.pivot:
        if item.pivot_locale:
            bits.append(f"[reference ({item.pivot_locale}): {item.pivot}]")
        else:
            bits.append(f"[reference: {item.pivot}]")
    if item.max_chars:
        bits.append(f"[max {item.max_chars} chars]")
    if item.html:
        bits.append("[html: preserve tags]")
    if item.glossary_note:
        note = item.glossary_note.strip()
        bits.append(note if note.startswith("[") else f"[glossary: {note}]")
    if _is_code_like(item.source):
        bits.append(
            "[code-like: looks like a technical identifier — "
            "translate the meaning if there is one, or keep as-is]"
        )
    if item.frame_samples:
        bits.append(f"[frame: {frame_hint(item, compact=True)}]")
    tag = rejection_tag(item.previous_rejection)
    if tag:
        bits.append(tag)
    return ("  " + "  ".join(bits)) if bits else ""


def frame_hint(item: BatchItem, *, compact: bool = False, language: str = "") -> str:
    """The frame filled with sample values, and what the model must send back (ADR-124).

    A frame like ``{rank} of {suit}`` has one word outside its placeholders; alone,
    "of" is a guess. Filled ("Ace of Spades") it is a phrase the model knows.
    """
    samples = item.frame_samples or {}
    if not samples:
        return ""
    filled = item.source
    for span, value in samples.items():
        filled = filled.replace(span, value)
    by_span = {span: tok for tok, span in (item.placeholder_mask or {}).items()}
    pairs = ", ".join(f"{by_span.get(span, span)} = {value}" for span, value in samples.items())
    kind = "numeric stand-ins" if by_span else "placeholders"
    if compact:
        return (
            f'with sample values it reads "{filled}" ({pairs}); translate the whole frame '
            f"and output it with the {kind}, not the sample values"
        )
    target = f" in {language}" if language else ""
    return (
        f"This string is a short frame around dynamic values. With sample values it reads: "
        f'"{filled}" ({pairs}).\n'
        f"Translate the whole frame so it reads naturally{target} with values like these, "
        f"and output it with the {kind} in place of the sample values.\n"
    )


def _preamble(
    domain: str,
    glossary_block: str,
    register: str = "informal",
    style_notes: str = "",
    locale: str = "",
) -> str:
    line = f"You are a professional translator for {domain}.\n"
    reg = _REGISTER_LINES.get(register, _REGISTER_LINES["informal"])
    line += f"{reg}\n"
    # ``style_for`` joins locale notes and project lines with a newline (ADR-60).
    head, _, extra = (style_notes or "").partition("\n")
    if head.strip():
        line += f"Style notes for this locale: {head.strip()}\n"
    if extra.strip():
        line += f"{extra.strip()}\n"
    if locale:
        typo = profile(locale).typography_prompt
        if typo:
            line += f"Typography for {locale}: {typo}\n"
        line += grammar_block(locale)
    return line + (f"{glossary_block}\n" if glossary_block else "")


def grammar_block(locale: str) -> str:
    """The language's grammar rules and worked examples (stable per locale, so cacheable)."""
    prof = profile(locale)
    out = ""
    if prof.grammar_prompt:
        out += f"Grammar for {locale}:\n{prof.grammar_prompt.strip()}\n"
    if prof.grammar_examples:
        pairs = "\n".join(f"  {src!r} -> {dst!r}" for src, dst in prof.grammar_examples)
        out += f"Correct {locale} examples:\n{pairs}\n"
    return out


def _html_rules(items: list[BatchItem]) -> str:
    """Tag guidance, only when a string carries HTML: tags may move with the words."""
    if not any(item.html for item in items):
        return ""
    return (
        "Inline tags may move so the sentence reads naturally, but every tag pair must still "
        "wrap the translation of the same words.\n"
        "   Worked example: EN `Click <b>here</b> to continue` → DE "
        "`Klicken Sie <b>hier</b>, um fortzufahren` (tags kept, word order changed).\n"
    )


def _script_rule(locale: str, language: str) -> str:
    del language  # LocalePolicy derives the language name from the locale.
    return LocalePolicy.for_locale(locale).script_rule()


def _mask_token_rules(items: list[BatchItem]) -> str:
    tokens: list[str] = []
    for item in items:
        if item.placeholder_mask:
            tokens.extend(sorted(item.placeholder_mask))
    if not tokens:
        return ""
    token_list = ", ".join(tokens)
    return (
        "Some strings use numeric stand-ins for dynamic values "
        f"({token_list}). Copy each number exactly into your translation — "
        "same digits, never omitted or altered. Translate only the surrounding words.\n"
        "   Worked example: EN `900000001 players · 900000002 tables` → PL "
        "`900000001 graczy · 900000002 stoły` (numbers unchanged).\n"
    )


def _placeholder_rules(items: list[BatchItem]) -> str:
    """Placeholder guidance. Non-ICU standards list their own tokens."""
    if any(item.native_standard for item in items):
        names: list[str] = []
        for item in items:
            names.extend(item.preserve_tokens)
        if not names:
            return (
                "This source has no replacement tokens. "
                "Do not invent any.\n"
            )
        listed = ", ".join(dict.fromkeys(names))
        return (
            "Copy these replacement tokens unchanged — same characters, "
            f"never translated or omitted: {listed}.\n"
        )
    masked = _mask_token_rules(items)
    if masked:
        return masked
    names: set[str] = set()
    for item in items:
        names |= extract_placeholders(item.source)
    if not names:
        return (
            "This source has NO ICU placeholders (`{name}` tokens). "
            "Do not invent any curly-brace tokens — output plain translated text only.\n"
        )
    lines = [
        "ICU placeholders are `{name}` tokens (curly braces around an identifier). "
        "Each name is an English code identifier — keep it in Latin letters, "
        "never translated into the target language. "
        "Copy every placeholder from the source exactly — same braces, same spelling. "
        "Never omit a placeholder, and never replace one with a literal number, "
        "count, or translated word.",
    ]
    tokens = ", ".join(f"{{{n}}}" for n in sorted(names))
    lines.append(
        f"   Placeholders in this {'batch' if len(items) > 1 else 'string'}: {tokens}."
    )
    lines.append(
        "   Worked example: EN `{players} players · {tables} tables` → keep `{players}` "
        "and `{tables}` with those exact English names; translate only the words "
        "outside the braces."
    )
    lines.append(
        "   Worked example: EN `{pct}% ({made}/{bid})` must keep `{pct}`, `{made}`, "
        "and `{bid}` unchanged in every language (translate around them, not instead of them)."
    )
    return "\n".join(lines) + "\n"


def _plural_guidance(items: list[BatchItem], locale: str, language: str) -> str:
    """Worked plural example, included only when the batch actually needs it."""
    if not any(extract_plural_categories(i.source) is not None for i in items):
        return ""
    example = profile(locale).plural_example
    if not example:
        return ""
    required = sorted(required_plural_categories(locale))
    return (
        f"   This batch contains an ICU plural string. {language} requires ALL of "
        f"these categories: {', '.join(required)}. Worked example of the expected shape:\n"
        f"   {example}\n"
    )


def _example_compatible(source: str, example_en: str) -> bool:
    """Drop few-shots that would teach placeholders the source does not have.

    Dogfood failure mode: ``cardStats`` (``{done}/{stale}/{missing}``) in
    ``examples_file`` was injected into every prompt, so short buttons like
    ``▶ Translate`` invented those tokens and failed validation.
    """
    extra = extract_placeholders(example_en) - extract_placeholders(source)
    return not extra


def _examples_block(items: list[BatchItem]) -> str:
    pairs: list[tuple[str, str]] = []
    for item in items:
        for pair in item.examples or []:
            if pair not in pairs:
                pairs.append(pair)
        for pair in item.siblings or []:
            if pair not in pairs:
                pairs.append(pair)
    # Keep an example only if every item in the batch can safely see it
    # (example placeholders ⊆ each item's source placeholders).
    filtered: list[tuple[str, str]] = []
    for en, tr in pairs:
        if all(_example_compatible(item.source, en) for item in items):
            filtered.append((en, tr))
    if not filtered:
        return ""
    lines = [f'  EN: {en} → {tr}' for en, tr in filtered[:8]]
    return "Examples / related strings (match their terminology and register):\n" + "\n".join(lines) + "\n\n"


def build_fragment_prompt(
    fragment: str,
    language: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    placeholder_mask: dict[str, str] | None = None,
    style_notes: str = "",
    locale: str = "",
) -> str:
    mask_rules = ""
    if placeholder_mask:
        tokens = ", ".join(sorted(placeholder_mask))
        mask_rules = (
            f"Numeric stand-ins ({tokens}) are dynamic values — copy each number "
            f"exactly into your output.\n"
        )
    return (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}"
        f"Translate the following short UI glue text from English to {language}.\n"
        f"Output ONLY the translated glue on ONE line — no labels, no explanations, "
        f"no quotes, no repeated instructions, no curly braces.\n"
        f"Never output placeholders or `{{...}}` — glue text has no variables.\n"
        f"Preserve middle dots (·), slashes, and spacing pattern.\n"
        f"{mask_rules}"
        f"\n"
        f"Fragment:\n"
        f"{fragment}"
    )


def build_icu_span_prompt(
    span: str,
    language: str,
    locale: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    strict: bool = False,
    style_notes: str = "",
) -> str:
    var = sorted(extract_placeholders(span))
    var_name = var[0] if var else "n"
    required = sorted(required_plural_categories(locale))
    example = profile(locale).plural_example
    example_line = f"   Worked example for {language}: {example}\n" if example else ""
    branches = " ".join(f"{cat} {{# ...}}" for cat in required)
    skeleton = f"{{{var_name}, plural, {branches}}}"
    strict_block = ""
    if strict:
        strict_block = (
            f"Your previous attempt was invalid. Output MUST match this skeleton "
            f"(replace ... with natural {language} words, keep `#`):\n"
            f"   {skeleton}\n"
        )
    return (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}"
        f"Translate this ICU message fragment from English to {language}.\n"
        f"\n"
        f"Rules (follow exactly):\n"
        f"1. Output ONLY the translated ICU fragment on ONE line — no explanations.\n"
        f"2. Keep the variable name `{var_name}` exactly — your output must contain "
        f"`{{{var_name},` and must NOT rename it.\n"
        f"3. {language} requires ALL of these plural categories: {', '.join(required)}.\n"
        f"   English may only show one/other — you MUST still emit every {language} "
        f"category branch ({len(required)} branches total).\n"
        f"4. Keep `#` inside each branch where the source has it.\n"
        f"{example_line}"
        f"{strict_block}"
        f"\n"
        f"ICU fragment:\n"
        f"{span}"
    )


def build_icu_message_prompt_parts(
    item: BatchItem,
    language: str,
    locale: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    style_notes: str = "",
) -> tuple[str, str]:
    """``(system, user)`` for one whole ICU plural/select message (ADR-124).

    Fragment-wise translation failed validation piece by piece and skipped every
    plural/select key in the first consumer runs. The whole message keeps the
    sentence together; the rules name what V47 and V03 check afterwards.
    """
    from ..core.validate import icu_choice_args

    args = icu_choice_args(item.source)
    kinds = ", ".join(f"{{{a}, {k}}}" for a, k, _ in args) or "none"
    rules = [
        "Output ONLY the translated message on ONE line: no explanations, no quotes, "
        "no code fences, no labels.",
        f"Keep the ICU structure. Every argument keeps its name and its kind: {kinds}. "
        "Never rename an argument, never turn a select into a plural or the reverse.",
    ]
    selects = [(a, keys) for a, k, keys in args if k == "select" and keys]
    if selects:
        listed = "; ".join(f"{a}: {', '.join(keys)}" for a, keys in selects)
        rules.append(
            f"Keep every select key exactly as in the source (the code passes them): {listed}. "
            "Translate only the text inside each branch."
        )
    example_line = ""
    if any(k in ("plural", "selectordinal") for _a, k, _ in args):
        required = sorted(required_plural_categories(locale))
        rules.append(
            f"Every plural must have all {language} categories: {', '.join(required)} "
            f"({len(required)} branches), even where English shows only one and other. "
            "Keep explicit =0 / =1 branches."
        )
        rules.append("Keep `#` inside each plural branch where the source has it: it is the number.")
        example = profile(locale).plural_example
        if example:
            example_line = f"   Worked example for {language}: {example}\n"
    rules.append(_placeholder_rules([item]).strip())
    rules.append(_script_rule(locale, language))
    numbered = "".join(f"{i}. {r}\n" for i, r in enumerate(rules, 1))
    system = (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}"
        f"Translate one complete ICU MessageFormat message from English to {language}.\n"
        f"Rules (follow exactly):\n{numbered}{example_line}"
    ).rstrip() + "\n"
    ctx = f"Context: {item.context}\n" if item.context else ""
    llm = f"Translator note: {item.llm_note}\n" if item.llm_note else ""
    key_line = f"Message key: {item.message_key}\n" if item.message_key else ""
    glossary_note = f"{item.glossary_note}\n" if item.glossary_note else ""
    rejection = rejection_tag(item.previous_rejection)
    rejection_line = f"{rejection} Fix this in the new translation.\n" if rejection else ""
    user = (
        f"{key_line}{ctx}{llm}{glossary_note}{rejection_line}"
        f"Translate the whole ICU message below from English to {language}.\n"
        f"\n"
        f"String to translate:\n"
        f"{item.text_for_prompt()}"
    )
    return system, user


def normalize_family(family: str) -> str:
    name = (family or "chat").strip() or "chat"
    return name if name in PROMPT_FAMILIES else "chat"


def _indent_continuation(text: str) -> str:
    """Keep a multi-line source under its own number.

    An unindented second line such as ``2. foo`` would read as the next item
    and let a source string forge extra numbered entries.
    """
    if "\n" not in text and "\r" not in text:
        return text
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n   ".join(lines)


def build_batch_prompt_parts(
    items: list[BatchItem],
    language: str,
    locale: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    family: str = "chat",
    style_notes: str = "",
) -> tuple[str, str]:
    """Return ``(system, user)`` for prompt-cache friendly cloud calls.

    System holds the stable prefix (domain / register / style / glossary /
    shared rules). User holds the volatile string list. Concatenating both
    yields the same text as :func:`build_batch_prompt`.
    """
    lines: list[str] = []
    for i, item in enumerate(items, 1):
        line = f"{i}. {_indent_continuation(item.text_for_prompt())}"
        line += _item_annotations(item)
        lines.append(line)

    if normalize_family(family) == "mt_chat":
        rules = (
            f"Rules:\n"
            f"1. Output ONLY a JSON array of translated strings matching the input "
            f"count, in the same order.\n"
            f'   Example for 3 items: ["translation 1", "translation 2", "translation 3"]\n'
            f"2. Identical source strings get identical translations; different sources get "
            f"different ones. Pick ONE sense using [key]/[context]/glossary — never invent "
            f"another sense.\n"
            f"3. {_placeholder_rules(items)}"
            f"4. ICU plurals must use every category {language} requires.\n"
            f"{_plural_guidance(items, locale, language)}"
            f"5. {_script_rule(locale, language)}\n"
            f"6. No explanations or markdown — only the JSON array.\n"
        )
    else:
        rules = (
            f"Rules:\n"
            f"1. Output ONLY a JSON array of translated strings matching the input "
            f"count, in the same order.\n"
            f'   Example for 3 items: ["translation 1", "translation 2", "translation 3"]\n'
            f"2. Identical source strings MUST produce identical translations. Different source "
            f"strings MUST produce different translations. Never copy the translation of one "
            f"source onto a different source.\n"
            f"3. {_placeholder_rules(items)}"
            f"4. If a source uses ICU plural syntax ({{var, plural, one {{...}} other {{...}}}}), "
            f"output valid ICU plural syntax with the categories {language} grammar requires.\n"
            f"{_plural_guidance(items, locale, language)}"
            f"5. Preserve punctuation style.\n"
            f"6. For strings marked [max N chars]: stay within that budget. Many languages run "
            f"20-40% longer than English -- prefer a shorter synonym over truncation.\n"
            f"7. {_script_rule(locale, language)}\n"
            f"8. No explanations, no extra keys, no markdown -- only the JSON array of strings. "
            f"Never echo [key:…] or translator notes inside a string.\n"
        )
    rules += _html_rules(items)

    high_risk = any(getattr(item, "risk", "medium") == "high" for item in items)
    self_check = (
        "\nHigh-risk strings are present. Before outputting, verify for each item: "
        "(1) all placeholders are present, (2) meaning is not inverted, "
        "(3) glossary terms are respected.\n"
        if high_risk else ""
    )
    system = (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}"
        f"{rules}"
        f"{self_check}"
    ).rstrip() + "\n"
    user = (
        f"{_examples_block(items)}"
        f"Translate the following {len(items)} numbered UI strings from English to {language}.\n"
        f"\n"
        f"Strings to translate:\n"
        + "\n".join(lines)
        + f"\n\nJSON array of {len(items)} translations:"
    )
    return system, user


def build_batch_prompt(
    items: list[BatchItem],
    language: str,
    locale: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    family: str = "chat",
    style_notes: str = "",
) -> str:
    system, user = build_batch_prompt_parts(
        items, language, locale, domain, glossary_block,
        register=register, family=family, style_notes=style_notes,
    )
    return f"{system}\n{user}" if system else user


def build_single_prompt_parts(
    item: BatchItem,
    language: str,
    domain: str,
    glossary_block: str,
    *,
    locale: str = "",
    register: str = "informal",
    family: str = "chat",
    style_notes: str = "",
) -> tuple[str, str]:
    """Return ``(system, user)`` — stable rules vs volatile string payload."""
    ctx = f"Context: {item.context}\n" if item.context else ""
    llm = f"Translator note: {item.llm_note}\n" if item.llm_note else ""
    key_line = f"Message key: {item.message_key}\n" if item.message_key else ""
    html_line = (
        "This string contains HTML — preserve every tag and attribute exactly.\n"
        if item.html else ""
    )
    rejection = rejection_tag(item.previous_rejection)
    rejection_line = f"{rejection} Fix this in the new translation.\n" if rejection else ""
    frame_line = frame_hint(item, language=language)
    pivot = ""
    if item.pivot:
        pivot = (
            f"A reference translation into a closely related variant is provided: "
            f"{item.pivot!r}. Keep terminology consistent with it unless this "
            f"language's usage genuinely differs.\n"
        )
    if normalize_family(family) == "mt_chat":
        rules = (
            f"Rules (follow exactly):\n"
            f"1. Output ONLY the translated UI text. No explanations, no quotes, no extra "
            f"lines. Never echo [key:…], role tags, or translator notes.\n"
            f"2. Pick ONE sense using Message key, Context, and glossary. "
            f"Do not invent another sense of the English word.\n"
            f"3. {_placeholder_rules([item])}"
            f"4. If the source uses ICU plural syntax, output valid ICU with every "
            f"category this language requires, keeping '#' inside each branch.\n"
            f"5. {_script_rule(locale, language)}\n"
        )
    else:
        rules = (
            f"Rules (follow exactly):\n"
            f"1. Output ONLY the translated UI text. No explanations, no quotes, no extra "
            f"lines. Never echo [key:…], role tags, or translator notes.\n"
            f"2. {_placeholder_rules([item])}"
            f"3. If the source uses ICU plural syntax, output valid ICU plural syntax with every "
            f"category this language's grammar requires, keeping '#' inside each branch.\n"
            f"4. Preserve punctuation style: if the English ends with '...' keep it.\n"
            f"5. If the string is a single short word or abbreviation, output only that "
            f"translation -- nothing else.\n"
            f"6. {_script_rule(locale, language)}\n"
        )
    rules += _html_rules([item])
    system = (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}"
        f"{rules}"
    ).rstrip() + "\n"
    user = (
        f"{key_line}{ctx}{llm}"
        f"{(item.glossary_note + chr(10)) if item.glossary_note else ''}"
        f"{html_line}{pivot}{rejection_line}"
        f"{_examples_block([item])}"
        f"{frame_line}"
        f"Translate the following UI string from English to {language}.\n"
        f"\n"
        f"String to translate:\n"
        f"{item.text_for_prompt()}"
    )
    return system, user


def build_single_prompt(
    item: BatchItem,
    language: str,
    domain: str,
    glossary_block: str,
    *,
    locale: str = "",
    register: str = "informal",
    family: str = "chat",
    style_notes: str = "",
) -> str:
    system, user = build_single_prompt_parts(
        item, language, domain, glossary_block,
        locale=locale, register=register, family=family, style_notes=style_notes,
    )
    return f"{system}\n{user}" if system else user


def build_shorten_prompt(
    source: str, translated: str, language: str, max_chars: int,
    domain: str, glossary_block: str, context: str = "",
    *,
    register: str = "informal",
    style_notes: str = "",
    locale: str = "",
) -> str:
    ctx = f"Context: {context}\n" if context else ""
    return (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}{ctx}"
        f"The following {language} translation is too long for a UI element limited to "
        f"{max_chars} characters. Shorten it to fit while preserving the meaning.\n"
        f"\n"
        f"Rules:\n"
        f"1. Output ONLY the shortened translation. No explanations, no quotes.\n"
        f"2. {_placeholder_rules([BatchItem(source=source)])}"
        f"3. Keep abbreviations natural in {language} -- do not invent new ones.\n"
        f"\n"
        f"English original: {source}\n"
        f"Current translation ({len(translated)} chars, limit {max_chars}): {translated}"
    )


def build_backtranslate_prompt(translated: str, language: str) -> str:
    return (
        f"Translate the following {language} UI string back to English.\n"
        f"Output ONLY the English text. No explanations.\n\n"
        f"{translated}"
    )


def build_batch_backtranslate_prompt(
    numbered: list[tuple[int, str]],
    language: str,
) -> str:
    lines = [f"{idx}. {_indent_continuation(text)}" for idx, text in numbered]
    n = len(numbered)
    return (
        f"Translate each numbered {language} UI string back to English.\n"
        f"Output ONLY a JSON array of exactly {n} English strings in order.\n"
        f"No explanations.\n\n"
        + "\n".join(lines)
    )


def build_refine_prompt(
    item: BatchItem,
    previous: str,
    language: str,
    domain: str,
    glossary_block: str,
    *,
    register: str = "informal",
    family: str = "chat",
    style_notes: str = "",
    locale: str = "",
    rejection: str | None = None,
) -> str:
    """Ask the model to improve a prior attempt (Phase 3 refine loop)."""
    del family  # refine keeps the shared chat refine shape for all families
    ctx = f"Context: {item.context}\n" if item.context else ""
    tag = rejection_tag(rejection)
    rejected = f"{tag} Do not repeat that mistake.\n" if tag else ""
    return (
        f"{_preamble(domain, glossary_block, register, style_notes, locale=locale)}{ctx}"
        f"{_examples_block([item])}{rejected}"
        f"Here is a first attempt at translating to {language}: {previous!r}.\n"
        f"Improve it. {_placeholder_rules([item])}"
        f"Fix register, terminology, and grammar issues. Output ONLY the improved {language} text.\n"
        f"\n"
        f"English original:\n"
        f"{item.source}"
    )

