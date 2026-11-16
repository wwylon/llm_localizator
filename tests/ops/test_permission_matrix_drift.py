"""Every ops registry command must appear in the permission matrix."""

from __future__ import annotations

from llm_localizator.ops.dispatch import _REGISTRY
from llm_localizator.ops.permissions import DEFAULT_MATRIX, OPERATIONS


# Commands handled outside _REGISTRY (init) or aliases that map to another name.
_EXPLICIT_EXTRA = frozenset({"init", "doctor", "guide"})


def test_operations_tuple_matches_default_matrix() -> None:
    assert set(OPERATIONS) == set(DEFAULT_MATRIX)


def test_registry_commands_are_in_permission_matrix() -> None:
    missing: list[str] = []
    for name in _REGISTRY:
        op = name.replace("_", "-")
        if op not in DEFAULT_MATRIX and name not in _EXPLICIT_EXTRA:
            missing.append(op)
    assert missing == [], f"ops missing from DEFAULT_MATRIX: {missing}"
