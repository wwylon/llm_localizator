"""C-028: [validate.severity] overrides."""

from __future__ import annotations

import pytest

from llm_localizator.pipeline.validate import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Finding,
    apply_severity_overrides,
)
from llm_localizator.projects.config import ConfigError, load_config


def _f(check, sev):
    return Finding(check, sev, "de", "app", "k", "msg")


def test_off_drops_and_regrade():
    out = apply_severity_overrides(
        [_f("V13", SEVERITY_WARNING), _f("V06", SEVERITY_WARNING), _f("V01", SEVERITY_ERROR)],
        {"V13": "error", "V06": "off"},
    )
    assert [(f.check, f.severity) for f in out] == [("V13", SEVERITY_ERROR), ("V01", SEVERITY_ERROR)]


def _load(tmp_path, extra):
    nl = chr(10)
    text = nl.join([
        "[project]", 'name = "demo"', 'source_locale = "en"', "",
        "[catalog]", 'format = "json-nested"', 'path = "messages/{locale}/{namespace}.json"', "",
        "[locales]", 'targets = ["de"]', "", "[provider]", 'kind = "null"', "", extra, "",
    ])
    p = tmp_path / ".llm-localize.toml"
    p.write_text(text, encoding="utf-8")
    return load_config(p)


def test_config_parses_and_normalises_case(tmp_path):
    cfg = _load(tmp_path, "[validate.severity]" + chr(10) + 'v13 = "error"')
    assert cfg.severity_overrides == {"V13": "error"}


@pytest.mark.parametrize("line", ['V02 = "off"', 'V27 = "warning"', 'X1 = "off"', 'V13 = "fatal"'])
def test_config_rejects(tmp_path, line):
    with pytest.raises(ConfigError):
        _load(tmp_path, "[validate.severity]" + chr(10) + line)


def test_config_rejects_unknown_validate_key(tmp_path):
    with pytest.raises(ConfigError):
        _load(tmp_path, "[validate]" + chr(10) + "bogus = 1")
