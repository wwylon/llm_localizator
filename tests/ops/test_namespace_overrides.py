"""Namespace submit override fidelity."""

from __future__ import annotations

from llm_localizator.ops.types import namespace_override_sets


def test_namespace_override_sets_empty_means_all() -> None:
    assert namespace_override_sets(None) == [{}]
    assert namespace_override_sets([]) == [{}]


def test_namespace_override_sets_one_job_for_all_namespaces() -> None:
    assert namespace_override_sets(["app", "nav"]) == [
        {"--namespace": "app,nav"},
    ]
