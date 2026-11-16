"""Per-locale translation state.

One JSON file per target locale, mapping ``"{namespace}.{dotted.key}"`` to a
record of how that key was last translated. The key format and the two hash
algorithms are frozen (ADR-7) -- consumers have thousands of live entries.

A record looks like::

    {
      "src_text":      "Save",       # optional; source at translation time (history "what changed")
      "context_sha":   "<12 hex>",   # optional; note/screen/maxChars fingerprint
      "src_sha":       "<12 hex>",   # content fingerprint of the source string
      "structure_sig": "<12 hex>",   # ICU shape fingerprint
      "translated_at": "2026-08-15T10:04:11Z",
      "model":         "llama3.2",
      "provider":      "ollama",     # optional; ADR-19 channel provenance
      "status":        "machine"
    }

``translated_at`` historically held the literal strings ``"now"`` or
``"bootstrap"`` (F-003). Those are still accepted on read and reported as an
unknown time; new writes always emit ISO 8601.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..core.hash import src_hash, structure_signature
from ._locale_json_store import LocaleJsonStore
from .provenance import PROVIDER_CLOUD, PROVIDER_LOCAL, normalize_provider, provider_of

__all__ = [
    "StateStore",
    "state_key",
    "needs_translation",
    "translation_status",
    "is_translated_value",
    "matches_status_filter",
    "make_entry",
    "parse_translated_at",
    "is_verified",
    "LEGACY_TIMESTAMPS",
    "TRUSTED_STATUSES",
]

#: Statuses treated as trusted human-or-handoff copies (coherence, ADR-48).
TRUSTED_STATUSES = frozenset({
    "human", "agent", "imported", "verified", "llm_reviewed",
})

LEGACY_TIMESTAMPS = {"now", "bootstrap"}

STATUS_MACHINE = "machine"
STATUS_BOOTSTRAP = "machine"


def state_key(namespace: str, key: str) -> str:
    """The frozen state-file key format."""
    return f"{namespace}.{key}" if namespace else key


def split_operator_key(raw: str, namespaces: set[str] | None = None) -> tuple[str, str]:
    """Map ``namespace.key`` to ``(namespace, key)``.

    A known namespace wins, including ``admin/users`` written as
    ``admin.users``. Otherwise split on the first dot. ``admin/users.signIn``
    already splits that way. A dotted key in the empty namespace stays
    ambiguous; that is the frozen state-key format (ADR-7).
    """
    text = str(raw).strip()
    known = {ns for ns in (namespaces or set()) if ns}
    best: tuple[int, str, str] | None = None
    for ns in known:
        forms = [ns]
        if "/" in ns:
            forms.append(ns.replace("/", "."))
        for form in forms:
            prefix = form + "."
            if text.startswith(prefix) and (best is None or len(form) > best[0]):
                rest = text[len(prefix):]
                if rest:
                    best = (len(form), ns, rest)
    if best is not None:
        return best[1], best[2]
    if "." in text:
        namespace, key = text.split(".", 1)
        return namespace, key
    return "", text


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_translated_at(value: object) -> datetime | None:
    """Best-effort read of a ``translated_at`` field.

    Returns ``None`` for the legacy sentinels and anything unparseable, which
    callers should present as "unknown", never as an error.
    """
    if not isinstance(value, str) or value in LEGACY_TIMESTAMPS:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def context_fingerprint(
    note: str | None, screen: str | None, max_chars: int | None,
) -> str | None:
    """Hash of the translator context, or ``None`` when no context was supplied.

    ``None`` means "unknown" (the caller did not look at the context notes);
    an empty note is a real, comparable value, so adding or removing a note is
    detected.
    """
    if note is None and screen is None and max_chars is None:
        return None
    return src_hash(
        "\x1f".join([note or "", screen or "", "" if max_chars is None else str(max_chars)])
    )


def make_entry(
    source_value: str,
    model: str,
    status: str = STATUS_MACHINE,
    *,
    provider: str | None = None,
    note: str | None = None,
    screen: str | None = None,
    max_chars: int | None = None,
    target_value: str | None = None,
) -> dict:
    """Build a state record for a freshly translated key.

    *target_value* is the text written to the catalogue; its hash lets later
    runs notice a value changed out-of-band (``external_edit``).
    """
    entry: dict = {
        "src_text": source_value,
        "src_sha": src_hash(source_value),
        "structure_sig": structure_signature(source_value),
        "translated_at": now_iso(),
        "model": model,
        "provider": normalize_provider(provider),
        "status": status,
    }
    if isinstance(target_value, str):
        entry["tgt_sha"] = src_hash(target_value.strip())
    fingerprint = context_fingerprint(note, screen, max_chars)
    if fingerprint is not None:
        entry["context_sha"] = fingerprint
    return entry


def is_verified(entry: dict | None) -> bool:
    """Whether a key has human verification sign-off."""
    if not entry:
        return False
    verified_at = entry.get("verified_at")
    return isinstance(verified_at, str) and bool(verified_at.strip())


def is_locked(entry: dict | None) -> bool:
    """Optional do-not-translate flag. Unknown to older readers, never a status."""
    return bool(entry) and entry.get("locked") is True


def needs_translation(
    source_value: str,
    entry: dict | None,
    force: bool = False,
    *,
    note: str | None = None,
    screen: str | None = None,
    max_chars: int | None = None,
) -> bool:
    """Whether a key must be (re)translated.

    True when it has never been translated, when ``force`` is set, when the
    recorded source fingerprint no longer matches the current source string, or
    when the translator context (note/screen/maxChars) has changed. Context is
    compared only when the caller supplies it and the entry recorded it, so
    older records and callers that pass nothing never look stale.
    """
    if entry is None or force:
        return True
    if entry.get("src_sha") != src_hash(source_value):
        return True
    current = context_fingerprint(note, screen, max_chars)
    if current is not None:
        stored = entry.get("context_sha")
        if stored is not None and stored != current:
            return True
    return False


def translation_status(source: str, value: str | None, entry: dict | None) -> str:
    """Table status for one locale. Same rules as the web message index."""
    if value is None or entry is None:
        return "missing"
    if needs_translation(source, entry):
        return "stale"
    if value == source:
        if entry.get("status") == "intentional":
            return "intentional"
        return "untranslated"
    # ADR-114: intentional means "kept source"; a divergent value is not a
    # source mirror anymore, so the table shows human (use locked for a hold).
    if entry.get("status") == "intentional":
        return "human"
    status = entry.get("status", "machine")
    # ADR-48: legacy human+agent/import rows surface as agent/imported.
    if status == "human":
        channel = provider_of(entry)
        if channel == "agent":
            return "agent"
        if channel == "import":
            return "imported"
    return status


def is_translated_value(source: str, value: str | None) -> bool:
    """True when the locale has a non-empty value that is not still the source."""
    if not isinstance(value, str) or not value.strip():
        return False
    return value != source


def matches_status_filter(
    only: str,
    *,
    status: str,
    provider: str | None,
    verified: bool,
    quality_score: float | None,
    threshold: float,
) -> bool:
    """Whether one locale view matches an export or table filter.

    ``has_findings`` is not handled here — it needs the findings index.
    """
    if not only or only == "all":
        return True
    if only == "low_score":
        return quality_score is not None and quality_score < threshold
    if only == "unscored":
        return quality_score is None and status != "missing"
    if only == "verified":
        return verified
    if only == "unverified":
        return (not verified) and status not in ("missing", "stale")
    if only == "provider_local":
        return provider in PROVIDER_LOCAL
    if only == "provider_cloud":
        return provider in PROVIDER_CLOUD
    if only == "provider_agent":
        return provider == "agent"
    if only == "provider_human":
        return provider == "human"
    if only == "provider_import":
        return provider == "import"
    return only == status


def is_structurally_stale(source_value: str, entry: dict | None) -> bool:
    """Whether the source's ICU *shape* changed since translation.

    A wording tweak leaves the structure signature intact; a placeholder or
    plural-category change does not. The distinction drives the fallback policy:
    a reworded string keeps its old translation pending retranslation, a
    restructured one must fall back to source immediately, because the existing
    translation is now actively wrong.
    """
    if entry is None:
        return False
    return entry.get("structure_sig") != structure_signature(source_value)


class StateStore(LocaleJsonStore):
    """Loads, mutates, and persists per-locale state files."""

    def record(self, locale: str, namespace: str, key: str, entry: dict) -> None:
        self.load(locale)[state_key(namespace, key)] = entry

    def entry(self, locale: str, namespace: str, key: str) -> dict | None:
        return self.load(locale).get(state_key(namespace, key))

    def drop(self, locale: str, namespace: str, key: str) -> None:
        self.load(locale).pop(state_key(namespace, key), None)
