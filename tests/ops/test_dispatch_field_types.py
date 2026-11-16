"""Numeric request fields: blank means the default, garbage is an error result, never a crash (M0, ops #15)."""

from __future__ import annotations

import pytest

from llm_localizator.ops.dispatch_util import FieldError, _int_or, _num_or


def test_blank_fields_take_the_default() -> None:
    assert _int_or({"limit": ""}, "limit", 20) == 20
    assert _int_or({}, "limit", 20) == 20
    assert _num_or({"threshold": None}, "threshold", 0.7) == 0.7


def test_numbers_parse() -> None:
    assert _int_or({"limit": " 12 "}, "limit", 20) == 12
    assert _num_or({"threshold": "0.5"}, "threshold", 0.7) == 0.5


@pytest.mark.parametrize("value", ["abc", "1.5", True])
def test_garbage_is_a_field_error(value) -> None:
    with pytest.raises(FieldError, match="limit"):
        _int_or({"limit": value}, "limit", 20)


def test_dispatch_returns_an_error_result_for_a_bad_field(tmp_path, monkeypatch) -> None:
    from llm_localizator.ops import dispatch

    def boom(cfg, command, body, report=None):
        raise FieldError("limit must be a whole number, not 'abc'")

    monkeypatch.setattr(dispatch, "_dispatch_op_body", boom)
    out = dispatch.dispatch_op(None, "status", {"limit": "abc"}, actor_role="Admin")
    assert out["ok"] is False and out["exit_code"] == 64 and "limit" in out["error"]
