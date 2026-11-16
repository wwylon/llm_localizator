"""V25 suspicious digraph checks."""

from llm_localizator.core.quality import check_suspicious_digraphs


def test_polish_garble_flagged() -> None:
    msg = check_suspicious_digraphs("ąćęń junk", "pl")
    assert msg is not None
    assert "ą" in msg or "suspicious" in msg


def test_polish_pangram_clean() -> None:
    assert check_suspicious_digraphs("Zażółć gęślą jaźń", "pl") is None


def test_chinese_not_digraph_check() -> None:
    # Empty denylist for zh — V21 handles script bleed.
    assert check_suspicious_digraphs("你好", "zh") is None


def test_german_suspicious() -> None:
    assert check_suspicious_digraphs("äötest", "de") is not None
    assert check_suspicious_digraphs("Größe", "de") is None
