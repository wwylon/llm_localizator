"""Every registered GET route must appear in GET_POLICY (fail-closed drift guard)."""

from __future__ import annotations

from llm_localizator.web.get_policy import GET_POLICY
from llm_localizator.web.server import _Handler


def test_every_get_route_has_a_policy() -> None:
    missing = sorted(path for path in _Handler._GET_ROUTES if path not in GET_POLICY)
    assert not missing, f"GET routes missing from GET_POLICY: {missing}"


def test_get_policy_has_no_orphan_paths() -> None:
    orphans = sorted(path for path in GET_POLICY if path not in _Handler._GET_ROUTES)
    assert not orphans, f"GET_POLICY orphans (no handler): {orphans}"
