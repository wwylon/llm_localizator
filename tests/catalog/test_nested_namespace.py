"""Hierarchical namespaces are real directories, not a dot in the key."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog import JsonNestedCatalog
from llm_localizator.catalog.json_nested import flatten_messages, unflatten_messages
from llm_localizator.catalog.state import state_key


def test_nested_namespace_is_a_directory_and_round_trips(tmp_path: Path) -> None:
    catalog = JsonNestedCatalog(tmp_path, "messages/{locale}/{namespace}.json", "en")
    catalog.save("en", "admin/users", {"signIn": "Sign in"})
    catalog.save("en", "auth", {"title": "Auth"})

    nested = tmp_path / "messages" / "en" / "admin" / "users.json"
    assert nested.is_file()
    assert (tmp_path / "messages" / "en" / "admin").is_dir()
    assert (tmp_path / "messages" / "en" / "auth.json").is_file()
    assert catalog.namespaces() == ["admin/users", "auth"]
    assert catalog.load("en", "admin/users") == {"signIn": "Sign in"}
    assert catalog.load("en", "auth") == {"title": "Auth"}
    assert state_key("admin/users", "signIn") == "admin/users.signIn"
    ns, key = state_key("admin/users", "signIn").split(".", 1)
    assert (ns, key) == ("admin/users", "signIn")


def test_unflatten_raises_when_scalar_and_nested_share_a_path() -> None:
    with pytest.raises(ValueError, match="collides with scalar key 'a'"):
        unflatten_messages({"a": "A", "a.b": "B"})
    with pytest.raises(ValueError, match="collides with nested key 'a.b'"):
        unflatten_messages({"a.b": "B", "a": "A"})
    flat = {"tactics.claim": "Claim", "top": "Top"}
    assert flatten_messages(unflatten_messages(flat)) == flat


def test_unflatten_rejects_keys_deeper_than_32() -> None:
    key = ".".join(f"p{i}" for i in range(33))
    with pytest.raises(ValueError, match="nesting depth"):
        unflatten_messages({key: "x"})
    shallow = ".".join(f"p{i}" for i in range(32))
    assert unflatten_messages({shallow: "x"})
