"""`[qa]` parsing (plan Part C, C7; ADR-119)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects import load_config
from llm_localizator.projects.config import ConfigError

BASE = """[project]
name = "demo"
source_locale = "en"
[catalog]
format = "json-flat"
path = "locales/{locale}.json"
[locales]
targets = ["pl", "zh", "ar"]
frozen = ["zh", "ar"]
"""


def _load(tmp_path: Path, qa: str):
    (tmp_path / "locales").mkdir(exist_ok=True)
    (tmp_path / "locales" / "en.json").write_text("{}", encoding="utf-8")
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text(BASE + qa, encoding="utf-8")
    return load_config(toml)


def test_no_qa_section_means_none(tmp_path: Path) -> None:
    assert _load(tmp_path, "").qa is None


def test_full_qa_section(tmp_path: Path) -> None:
    qa = _load(tmp_path, """
[qa]
start = ["uv", "run", "app", "web"]
base_url = "http://127.0.0.1:7474/"
pages = ["/", "/library"]
locale_mode = "path"
qa_locale = "en-XX"
ready_timeout = 20
[qa.clicks]
"/" = ["#tab-a", "#tab-b"]
""").qa
    assert qa.base_url == "http://127.0.0.1:7474"
    assert qa.start == ["uv", "run", "app", "web"]
    assert qa.pages == ["/", "/library"]
    assert qa.locale_mode == "path"
    assert qa.clicks == {"/": ["#tab-a", "#tab-b"]}
    assert qa.ready_timeout == 20
    # Layout locales default to ar/zh among the project's locales.
    assert qa.layout_locales == ["ar", "zh"]
    assert qa.as_dict()["query_param"] == "lang"


def test_defaults(tmp_path: Path) -> None:
    qa = _load(tmp_path, '[qa]\nbase_url = "http://localhost:8000"\n').qa
    assert qa.pages == ["/"] and qa.locale_mode == "query" and qa.start == []
    assert qa.qa_locale == "en-XX" and qa.query_param == "lang"


@pytest.mark.parametrize("body, message", [
    ('base_url = "localhost:8000"', "base_url"),
    ('base_url = "http://x"\nlocale_mode = "cookie"', "locale_mode"),
    ('base_url = "http://x"\nlocale_mode = "storage"', "storage_key"),
    ('base_url = "http://x"\npages = ["http://evil/"]', "paths under base_url"),
    ('base_url = "http://x"\npages = [""]', "pages"),
    ('base_url = "http://x"\nstart = [1]', "start"),
    ('base_url = "http://x"\nbogus = 1', "unknown [qa]"),
    ('base_url = "http://x"\n[qa.clicks]\n"/other" = ["#a"]', "not listed"),
    ('base_url = "http://x"\nready_timeout = "soon"', "ready_timeout"),
])
def test_invalid_qa_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
        _load(tmp_path, "[qa]\n" + body + "\n")


def test_storage_mode_with_key(tmp_path: Path) -> None:
    qa = _load(tmp_path, '[qa]\nbase_url = "http://x"\nlocale_mode = "storage"\n'
                         'storage_key = "tq_lang"\nlayout_locales = []\n').qa
    assert qa.storage_key == "tq_lang" and qa.layout_locales == []


def test_wait_for_per_page(tmp_path: Path) -> None:
    qa = _load(tmp_path, """
[qa]
base_url = "http://127.0.0.1:7474"
pages = ["/", "/k"]
[qa.wait_for]
"/k" = "#results li"
""").qa
    assert qa.wait_for == {"/k": "#results li"}
    assert qa.as_dict()["wait_for"] == {"/k": "#results li"}


def test_wait_for_unknown_page_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="wait_for"):
        _load(tmp_path, """
[qa]
base_url = "http://127.0.0.1:7474"
pages = ["/"]
[qa.wait_for]
"/nope" = "#x"
""")
