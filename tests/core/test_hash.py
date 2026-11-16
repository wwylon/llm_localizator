"""Source and structure fingerprints.

Ported from bridge's TestHashing. These algorithms are frozen (ADR-7): the
hard-coded digests below are the contract with every existing ``.state`` file.
"""

from __future__ import annotations

import pytest

from llm_localizator.core.hash import (
    SIGNATURE_VERSION,
    src_hash,
    structure_payload,
    structure_signature,
)


def test_src_hash_stable() -> None:
    assert src_hash("Hello") == src_hash("Hello")


def test_src_hash_changes_with_content() -> None:
    assert src_hash("Hello") != src_hash("Hello ")


def test_src_hash_is_twelve_hex_chars() -> None:
    h = src_hash("anything")
    assert len(h) == 12
    assert all(c in "0123456789abcdef" for c in h)


def test_src_hash_frozen_value() -> None:
    """Guards the state-file contract against an accidental algorithm change."""
    assert src_hash("Claim") == "4ca41db02825"


def test_structure_signature_stable_across_wording_change() -> None:
    a = "You won {n, plural, one {# trick} other {# tricks}}"
    b = "You took {n, plural, one {# trick} other {# tricks}}"
    assert structure_signature(a) == structure_signature(b)


def test_structure_signature_changes_with_placeholder_set() -> None:
    assert structure_signature("Hi {name}") != structure_signature("Hi {name} and {other}")


def test_structure_signature_changes_with_plural_categories() -> None:
    a = "{n, plural, one {# trick} other {# tricks}}"
    b = "{n, plural, one {# trick} few {# tricks} other {# tricks}}"
    assert structure_signature(a) != structure_signature(b)


def test_structure_signature_distinguishes_plural_from_plain() -> None:
    assert structure_signature("{n}") != structure_signature("{n, plural, other {# x}}")


# ---- the canonical payload (ADR-11) ----------------------------------------
#
# These pin the *serialisation*, not just the hash, because the whole point of
# version 2 is that a second implementation can reproduce it exactly. A test on
# the hash alone would not say what went wrong.

@pytest.mark.parametrize("text,expected", [
    ("Hello", "ph=|plural=-"),
    ("", "ph=|plural=-"),
    ("Hello {name}", "ph=name|plural=-"),
    ("{done} of {total} complete", "ph=done,total|plural=-"),
    ("{total} then {done}", "ph=done,total|plural=-"),
    ("{n, plural, one {# trick} other {# tricks}}", "ph=n|plural=one,other"),
    ("{n, plural, =0 {none} one {# x} other {# y}}", "ph=n|plural==0,one,other"),
    ("{name} won {n, plural, one {# trick} other {# tricks}}",
     "ph=n,name|plural=one,other"),
])
def test_canonical_payload_shape(text: str, expected: str) -> None:
    assert structure_payload(text) == expected


def test_payload_has_no_whitespace_or_quoting() -> None:
    """Version 1 hashed json.dumps output, whose separators and quoting a second
    implementation had to reproduce exactly -- and Go did not. Version 2 removes
    every such detail."""
    payload = structure_payload("{name} and {n, plural, one {#} other {#}}")
    assert " " not in payload
    assert '"' not in payload
    assert "'" not in payload
    assert ":" not in payload


def test_payload_is_order_independent() -> None:
    assert structure_payload("{a} {b}") == structure_payload("{b} {a}")


def test_signature_version_is_declared() -> None:
    assert SIGNATURE_VERSION == 2
