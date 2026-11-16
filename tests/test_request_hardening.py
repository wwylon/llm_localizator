"""Small request-handling hardening: header injection, non-ASCII tokens."""

from __future__ import annotations

from llm_localizator.web.auth import secrets_equal
from llm_localizator.web.server_logic import _safe_filename


def test_safe_filename_strips_header_breakers() -> None:
    evil = "a" + chr(34) + "b" + chr(13) + chr(10) + "Set-Cookie: x;/.." + chr(92) + "y.csv"
    out = _safe_filename(evil)
    assert not any(c in out for c in (chr(34), chr(13), chr(10), ";", "/", chr(92)))
    assert _safe_filename("") == "download"
    assert _safe_filename("ok.csv") == "ok.csv"


def test_secrets_equal_handles_non_ascii_without_raising() -> None:
    assert secrets_equal("tok", "tok")
    assert not secrets_equal("tök", "tok")
    assert secrets_equal("tök", "tök")
