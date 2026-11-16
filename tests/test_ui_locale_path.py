"""ADR-108 URL-prefix UI locale helpers + ADR-110 QA markers."""

from llm_localizator.web.ui_locale_path import (
    BASE_UI_LOCALES,
    needs_locale_redirect,
    prefixed_path,
    split_ui_locale_path,
    ui_locales,
)


def test_split_prefixed_app_path():
    assert split_ui_locale_path("/pl/app/stats/usage") == ("pl", "/app/stats/usage")
    assert split_ui_locale_path("/de/app") == ("de", "/app")
    assert split_ui_locale_path("/fr/login") == ("fr", "/login")
    assert split_ui_locale_path("/en-XX/app/settings") == ("en-XX", "/app/settings")
    assert split_ui_locale_path("/en/app") == ("en", "/app")


def test_bare_path_unchanged():
    assert split_ui_locale_path("/app/settings") == (None, "/app/settings")
    assert split_ui_locale_path("/api/overview") == (None, "/api/overview")


def test_redirect_and_prefix():
    assert needs_locale_redirect("/app")
    assert needs_locale_redirect("/login")
    assert not needs_locale_redirect("/pl/app")
    assert not needs_locale_redirect("/en-XX/app")
    assert not needs_locale_redirect("/api/projects")
    assert prefixed_path("de", "/app/editor") == "/de/app/editor"
    assert prefixed_path("en-XX", "/app") == "/en-XX/app"
    assert prefixed_path("xx", "/app") == "/en/app"


def test_qa_locales_opt_in():
    assert "en-XX" not in ui_locales([])
    assert "en-XX" not in ui_locales(None)
    assert ui_locales([]) == BASE_UI_LOCALES
    on = ui_locales(["en-XX"])
    assert "en-XX" in on
    assert "en" in on
    # Unknown codes are ignored by ui_locales (config_load rejects them).
    assert "zz" not in ui_locales(["zz", "en-XX"])
    assert prefixed_path("en-XX", "/app", allowed=ui_locales([])) == "/en/app"
    assert prefixed_path("en-XX", "/app", allowed=on) == "/en-XX/app"
