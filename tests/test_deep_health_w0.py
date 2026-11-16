"""Characterization tests for Deep health Wave 0 fixes."""

from __future__ import annotations

from llm_localizator.core.icu import extract_placeholders
from llm_localizator.core.validate import validate_translation
from llm_localizator.pipeline.candidates import validate_candidate
from llm_localizator.projects.accounts import STATUS_APPROVED, UserRecord
from llm_localizator.render.html_preview import preview_html
from llm_localizator.web.auth import Actor, resolve_locales


def test_icu_typed_args_are_placeholders() -> None:
    names = extract_placeholders("Total: {amount, number} EUR on {d, date, short}")
    assert "amount" in names
    assert "d" in names
    ok, reason = validate_translation(
        "Total: {amount, number} EUR", "Gesamt: EUR", "de", {},
    )
    assert not ok
    assert "placeholder" in reason.lower() or "amount" in reason.lower()


def test_review_path_rejects_foreign_script() -> None:
    text, reason = validate_candidate(
        "Save file", "Датei speichern", "de", {},
    )
    assert text is None
    assert reason and "script" in reason.lower()


def test_preview_html_blocks_xss_payloads() -> None:
    for payload in (
        "<svg/onload=alert(1)>",
        "<a href=javascript:alert(1)>x</a>",
        '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    ):
        out = preview_html(payload)
        assert "onload" not in out.lower()
        assert "javascript:" not in out.lower()
        assert "srcdoc" not in out.lower()
        assert "<script" not in out.lower()


def test_resolve_locales_empty_means_allowed_only() -> None:
    user = UserRecord(
        id="u1",
        username="tr",
        password_hash="x",
        role="Translator",
        status=STATUS_APPROVED,
        locales=["pl"],
    )
    actor = Actor(kind="user", role="Translator", user=user)
    locs, err = resolve_locales(actor, None, ["pl", "de", "cs"])
    assert err is None
    assert locs == ["pl"]
    locs2, err2 = resolve_locales(actor, ["de"], ["pl", "de"])
    assert locs2 == []
    assert err2 and "de" in err2
