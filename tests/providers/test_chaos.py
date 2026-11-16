"""ChaosProvider argument checks."""

import pytest

from llm_localizator.providers import ChaosProvider


def test_wrong_term_fault_needs_wrong_terms() -> None:
    with pytest.raises(ValueError, match="wrong_terms"):
        ChaosProvider(faults={"wrong_term": 1.0})


def test_wrong_term_fault_substitutes() -> None:
    p = ChaosProvider(lambda s: "Zapisz plik", faults={"wrong_term": 1.0},
                      wrong_terms={"plik": "dokument"})
    assert p._apply("Save file") == "Zapisz dokument"
