"""Content and manifest files: Markdown pages, TOML menus, extension manifests, Info.plist (ADR-145)."""

from __future__ import annotations

import json
from pathlib import Path

from llm_localizator.scan import build_scanner


def _texts(tmp_path: Path, rel: str, body: str) -> set[str]:
    path = tmp_path / "src" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    hits = build_scanner("source", tmp_path, ["src"]).scan().hardcoded
    return {" ".join(h.text.split()) for h in hits}


def test_markdown_front_matter_and_body_under_content(tmp_path: Path) -> None:
    texts = _texts(tmp_path, "content/english/_index.md", (
        '---\ntitle: "Start your Hugo project"\nimage: "/images/a.png"\nbutton:\n  label: "Get Started"\n  link: "/docs"\n---\n'
        "## Why choose us\n\nWe build **fast** sites for [people](https://example.com) every day.\n\n"
        "```js\nconst s = 'not shown to anyone here';\n```\n\n{{< notice >}}\nLorem ipsum dolor sit amet.\n"
    ))
    assert {"Start your Hugo project", "Get Started", "Why choose us"} <= texts
    assert any(t.startswith("We build fast sites for people") for t in texts)
    assert not any("not shown" in t or "Lorem" in t or "/images" in t for t in texts)


def test_project_docs_are_not_content(tmp_path: Path) -> None:
    assert not _texts(tmp_path, "README.md", "# My project\n\nThis project does many useful things for users.\n")
    assert not _texts(tmp_path, "docs/guide.md", "# Guide\n\nRun the installer and follow the steps carefully.\n")


def test_toml_menu_and_vscode_manifest_and_plist(tmp_path: Path) -> None:
    assert "Home" in _texts(tmp_path, "config/_default/menus.en.toml", '[[main]]\nname = "Home"\nurl = "/"\n')
    manifest = {
        "name": "ext", "contributes": {
            "commands": [{"command": "x.run", "title": "Run Code"}, {"command": "x.t", "title": "%x.title%"}],
            "configuration": {"properties": {"x.a": {"description": "Whether to show the output panel", "type": "boolean"}}},
        },
    }
    texts = _texts(tmp_path, "package.json", json.dumps(manifest, indent=2))
    assert {"Run Code", "Whether to show the output panel"} <= texts and "%x.title%" not in texts
    plist = "<dict><key>NSLocationUsageDescription</key><string>Location is only used to show your position.</string></dict>"
    assert any("Location is only used" in t for t in _texts(tmp_path, "Info.plist", plist))
    other = tmp_path / "plain"
    other.mkdir()
    assert not _texts(other, "pkg/package.json", json.dumps({"name": "lib", "description": "A small helper library"}))
