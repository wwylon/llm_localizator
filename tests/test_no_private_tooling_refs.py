"""Shipped files must not reference the private portfolio tooling repo.

The public export is the allowlist in ``publish.manifest.yaml`` (private only). In the
public tree the manifest is absent, so the test falls back to the same roots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Built from parts so this file does not match itself.
NEEDLE = "dev" + "kit"
FALLBACK_ALLOW = [
    "llm_localizator/",
    "tests/",
    "docs/",
    "site/",
    "i18n/",
    ".github/",
    ".githooks/",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "llms.txt",
]
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
BINARY_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".zip", ".gz", ".mo"}


def _allow_and_deny() -> tuple[list[str], list[str]]:
    manifest = ROOT / "publish.manifest.yaml"
    if not manifest.is_file():
        return FALLBACK_ALLOW, []
    import yaml

    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return list(data.get("allow") or []), list(data.get("deny") or [])


def _shipped_files() -> list[Path]:
    allow, deny = _allow_and_deny()
    denied = [d.rstrip("/") for d in deny]
    out: list[Path] = []
    for entry in allow:
        base = ROOT / entry.rstrip("/")
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for p in candidates:
            rel = p.relative_to(ROOT).as_posix()
            if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
                continue
            if any(rel == d or rel.startswith(d + "/") for d in denied):
                continue
            if p.suffix.lower() in BINARY_SUFFIXES:
                continue
            out.append(p)
    return out


@pytest.mark.slow
def test_shipped_files_do_not_reference_private_tooling() -> None:
    hits = []
    for p in _shipped_files():
        if p.resolve() == Path(__file__).resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if NEEDLE in text.lower():
            hits.append(p.relative_to(ROOT).as_posix())
    assert not hits, f"shipped files mention {NEEDLE}: {hits}"
