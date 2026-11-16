"""``[scan] content_globs``: declared YAML/Markdown files are read; undeclared ones are not (B7)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner

_OPENAPI = """openapi: 3.0.0
info:
  title: Weather API
  description: >
    City Lookup provides global geolocation
    and city search services.
paths:
  /now:
    get:
      summary: Get real-time weather for a location.
      parameters:
        - name: location
          description: The location to be queried.
"""


def _scan(tmp_path: Path, globs: list[str] | None) -> set[str]:
    api = tmp_path / "src" / "assets" / "openapi"
    api.mkdir(parents=True)
    (api / "weather.yml").write_text(_OPENAPI, encoding="utf-8")
    (tmp_path / "src" / "ci.yml").write_text("name: Build and test\n", encoding="utf-8")
    scanner = build_scanner("source", tmp_path, ["src"], content_globs=globs)
    return {h.text for h in scanner.scan().hardcoded}


def test_declared_yaml_is_read(tmp_path: Path) -> None:
    hits = _scan(tmp_path, ["**/openapi/*.yml"])
    assert "City Lookup provides global geolocation and city search services." in hits
    assert "Get real-time weather for a location." in hits
    assert "The location to be queried." in hits
    assert "Build and test" not in hits      # not declared


def test_yaml_is_off_by_default(tmp_path: Path) -> None:
    assert _scan(tmp_path, None) == set()


def test_bot_resources_markdown_is_content_by_default(tmp_path: Path) -> None:
    tags = tmp_path / "src" / "bot" / "resources" / "tags"
    tags.mkdir(parents=True)
    (tags / "dotenv.md").write_text("---\nembed:\n  title: Using .env files in Python\n---\n"
                                    "While this seems intuitive, it would actually fail.\n", encoding="utf-8")
    hits = {h.text for h in build_scanner("source", tmp_path, ["src"]).scan().hardcoded}
    assert "While this seems intuitive, it would actually fail." in hits
