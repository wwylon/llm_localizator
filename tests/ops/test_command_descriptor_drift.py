"""CommandDescriptor stays the single source for path/submit/stream/read-only."""

from __future__ import annotations

from llm_localizator.ops.command_descriptor import (
    COMMANDS,
    read_only_ops,
    streamable_ops,
    submit_ops,
)
from llm_localizator.ops.dispatch_cmds import STREAMABLE
from llm_localizator.ops.dispatch_util import _PATH_BODY_KEYS, _READ_ONLY_OPS
from llm_localizator.ops.manifest import _SUBMIT


def test_descriptor_path_keys_subset_of_dispatch() -> None:
    for cmd in COMMANDS:
        if not cmd.path_keys:
            continue
        key = cmd.name.replace("-", "_")
        declared = _PATH_BODY_KEYS.get(key) or _PATH_BODY_KEYS.get(cmd.name)
        assert declared is not None, f"{cmd.name}: path_keys set but missing from _PATH_BODY_KEYS"
        for pk in cmd.path_keys:
            assert pk in declared, f"{cmd.name}: {pk} not in dispatch path keys {declared}"


def test_path_body_keys_have_descriptors() -> None:
    known = {c.name.replace("-", "_") for c in COMMANDS}
    known |= {c.name for c in COMMANDS}
    for key in _PATH_BODY_KEYS:
        assert key in known, f"{key}: add CommandDescriptor path_keys"


def test_read_only_ops_from_descriptors() -> None:
    assert _READ_ONLY_OPS == read_only_ops()


def test_submit_ops_from_descriptors() -> None:
    assert _SUBMIT == submit_ops()


def test_streamable_ops_from_descriptors() -> None:
    assert STREAMABLE == streamable_ops()
    for name in ("translate", "improve", "review", "rescore", "documents", "bakeoff"):
        assert name in STREAMABLE
        assert f"run_{name}" in STREAMABLE
