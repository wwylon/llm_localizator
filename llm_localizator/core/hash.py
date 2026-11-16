"""Source and structure fingerprints for translation state tracking.

``src_hash`` is **frozen** (ADR-7): it drives ``needs_translation``, so changing
it would mark every key in every locale stale and force a full retranslation.

``structure_signature`` is **versioned and migratable** (ADR-11). It is derived
data — recomputing it costs one deterministic pass with no model calls — and its
original serialisation could not be reimplemented reliably in a second language,
which is a defect worth fixing rather than freezing.
"""

from __future__ import annotations

import hashlib

from .icu import extract_placeholders, extract_plural_categories

__all__ = ["src_hash", "structure_signature", "structure_payload", "SIGNATURE_VERSION"]

#: Bump when :func:`structure_payload` changes shape. Consumers migrate with
#: ``llm-localizator migrate-state``; see ADR-11.
SIGNATURE_VERSION = 2

_NO_PLURAL = "-"


def src_hash(s: str) -> str:
    """Fingerprint of the source string's *content*.

    A mismatch against the recorded value means the source text was edited and
    the translation is stale. **Frozen** — see the module docstring.
    """
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def structure_payload(s: str) -> str:
    """The canonical serialisation hashed by :func:`structure_signature`.

    Deliberately not JSON. Version 1 used ``json.dumps(..., sort_keys=True)``,
    whose output depends on separator whitespace (``", "``, ``": "``) and on
    quoting every list item — details a reimplementation in another language has
    to reproduce exactly, with nothing to catch it when it doesn't. Bridge's Go
    port got both wrong while carrying a comment claiming parity, and the
    resulting hash mismatch silently corrupted the shared state file.

    So the format is now a flat, delimiter-joined string::

        ph=done,n,total|plural=few,one,other
        ph=name|plural=-
        ph=|plural=-

    Sorted lists, comma-separated, sections joined with ``|``, ``-`` for absent.
    No whitespace, no quoting, no escaping rules. Five lines in any language, and
    nothing about it can drift by accident.

    (Placeholder and selector names are ICU identifiers or ``=N`` selectors, so
    they cannot themselves contain ``,`` or ``|``.)
    """
    placeholders = ",".join(sorted(extract_placeholders(s)))
    selectors = extract_plural_categories(s)
    plural = ",".join(sorted(selectors)) if selectors else _NO_PLURAL
    return f"ph={placeholders}|plural={plural}"


def structure_signature(s: str) -> str:
    """Fingerprint of the source string's ICU *shape*: placeholders + plural selectors.

    Detects structural change independently of wording change, so a policy layer
    can distinguish "reworded, the translation is probably still serviceable"
    from "the placeholders changed, the translation is now actively wrong".
    """
    return hashlib.sha256(structure_payload(s).encode("utf-8")).hexdigest()[:12]
