from pathlib import Path

from llm_localizator.projects.config import load_config


def test_scan_directive_aliases_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(
        "\n".join([
            "[project]",
            'name = "scan-aliases"',
            'source_locale = "en"',
            "",
            "[catalog]",
            'format = "json-nested"',
            'path = "messages/{locale}/{namespace}.json"',
            "",
            "[locales]",
            'targets = ["pl"]',
            "",
            "[locales.models]",
            'default = "testmodel"',
            "",
            "[provider]",
            'kind = "null"',
            "",
            "[scan]",
            "directive_aliases = false",
            "",
        ]),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.scan_directive_aliases is False
