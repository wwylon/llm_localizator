"""Hermetic smoke: every Ops-visible command through ``dispatch_op``.

Guards against carousel commands that raise or return ``unknown operation``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest, dispatch_op
from llm_localizator.ops.manifest import _OPS_EXCLUDED, _roles_for
from llm_localizator.ops.permissions import (
    DEFAULT_MATRIX,
    OPERATIONS,
    ROLE_DEVELOPER,
    ROLE_SUPERVISOR,
)

from tests.conftest import setup_project


# Dispatch-only ops used by Settings / dedicated APIs (not always in carousel).
_DISPATCH_ONLY = ("push-strings", "workflow")

# Ops exercised here via body dict only (no *Request parity entry required).
_BODY_DICT_ONLY = frozenset({
    "discover",
    "doctor",
    "guide",
    "term-report",
    "release-freeze",
    "release-diff",
    "acknowledge-flush",
    "impact",
    "glossary-propose",
    "push-strings",
    "workflow",
})


def _safe_body(name: str, tmp: Path) -> dict:
    """Minimal safe body for hermetic dispatch smoke."""
    llmish = {
        "dry_run": True,
        "locales": ["pl"],
    }
    by_name: dict[str, dict] = {
        "validate": {},
        "status": {},
        "scan": {},
        "discover": {},
        "estimate-cost": {"locales": ["pl"]},
        "agent-backlog": {},
        "agent-hardcoded": {"dry_run": True},
        "ingest-visual": {"dry_run": True, "path": str(tmp / "missing-findings.json")},
        "adopt": {"dry_run": True},
        "sync": {"dry_run": True, "locales": ["pl"]},
        "term-report": {},
        "release-diff": {},
        "release-freeze": {},
        "translate": dict(llmish),
        "improve": dict(llmish),
        "review": dict(llmish),
        "rescore": dict(llmish),
        "bakeoff": {"dry_run": True, "corpus": "builtin"},
        "documents": dict(llmish),
        "export": {"format": "csv", "locales": ["pl"], "dry_run": True},
        "import": {
            "dry_run": True,
            "text": "namespace,key,en,pl\napp,a,A,B\n",
            "format": "csv",
        },
        "migrate-state": {"dry_run": True},
        "doctor": {"skip_ollama": True},
        "hardcoded-hunt": {"skip_crawl": True},  # dispatch only; a real crawl took 7 min
        "guide": {"skip_provider": True},
        "init": {"directory": str(tmp), "no_register": True},
        "analytics": {},
        "metrics": {},
        "suggest": {},
        "draft": {"action": "list"},
        "source-diff": {"namespace": "ns", "key": "k"},
        "open-pr": {"action": "status"},
        "screenshot-link": {"action": "list"},
        "task": {"action": "list"},
        "discuss": {"action": "list"},
        "flag-source": {"namespace": "app", "key": "a", "note": "typo"},
        "source-review-queue": {},
        "bulk-clear": {"stale_to_source": True, "dry_run": True},
        "find-replace": {"locale": "pl", "find": "a", "dry_run": True},
        "rename-placeholder": {"old": "a", "new": "b", "dry_run": True},
        "scan-decide": {"action": "status"},
        "concordance": {"query": "Hello", "locale": "pl"},
        "tm-export": {"locale": "pl"},
        "org": {},
        "tm-import": {
            "locale": "pl",
            "tmx": (
                '<?xml version="1.0"?>'
                '<tmx version="1.4"><header srclang="en"/>'
                "<body></body></tmx>"
            ),
            "dry_run": True,
        },
        "glossary-export": {},
        "glossary-import": {
            "path": str(tmp / "missing-glossary.csv"),
            "dry_run": True,
        },
        "glossary-propose": {},
        "hard-keys": {"dry_run": True},
        "impact": {},
        "pseudo": {},
        "acknowledge-flush": {},
        "run-translate": dict(llmish),
        "run-improve": dict(llmish),
        "run-review": dict(llmish),
        "run-rescore": dict(llmish),
        "run-bakeoff": {"dry_run": True, "corpus": "builtin"},
        "run-documents": dict(llmish),
        "run-agent-hardcoded": {"dry_run": True},
        "run-sync": {"dry_run": True, "locales": ["pl"]},
        "push-strings": {
            "namespace": "app",
            "strings": {"k": "v"},
            "dry_run": True,
        },
        "workflow": {"route_only": True, "dry_run": True, "locales": ["pl"]},
    }
    return by_name.get(name, {"dry_run": True})


def _ops_universe() -> list[str]:
    manifest = build_commands_manifest(build_parser())["commands"]
    names = sorted(manifest)
    for extra in _DISPATCH_ONLY:
        if extra not in names:
            names.append(extra)
    return names


@pytest.fixture
def ops_project(project_root, make_config):
    setup_project(project_root, {"a": "A"}, existing={"a": "B"})
    cfg = make_config(project_root)
    return project_root, cfg


@pytest.mark.parametrize("command", _ops_universe())
def test_dispatch_op_smoke(ops_project, command: str) -> None:
    root, cfg = ops_project
    body = _safe_body(command, root)
    out = dispatch_op(cfg, command, body, actor_role="Admin")
    assert isinstance(out, dict)
    err = str(out.get("error") or "")
    assert "unknown operation" not in err, f"{command}: {err}"
    # Prefer success when the fixture allows; otherwise a stable non-unknown error.
    if out.get("ok") is not True:
        assert out.get("ok") is False
        assert err or out.get("summary"), f"{command}: failed without summary/error"


def test_manifest_excludes_non_http_ops() -> None:
    manifest = build_commands_manifest(build_parser())["commands"]
    for name in ("mcp", "add-locale", "web", "watch", "check", "workflow"):
        assert name not in manifest
    assert _OPS_EXCLUDED == frozenset({"web", "mcp", "add-locale", "watch", "check", "workflow", "quality",
                                         "runtime", "check-keys", "approach", "localize-project",
                                         "help", "skill", "set", "onboard",
                                         "context-propose", "context-note", "server-copy",
                                         "import-review"})


def test_manifest_covers_cli_except_excluded() -> None:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    manifest = build_commands_manifest(parser)["commands"]
    missing = []
    for name in sub.choices:
        if name in _OPS_EXCLUDED:
            continue
        if name not in manifest:
            missing.append(name)
    assert not missing, f"CLI commands missing from ops manifest: {missing}"


def test_run_translate_matches_translate_dry_run(ops_project) -> None:
    _, cfg = ops_project
    body = {"dry_run": True, "locales": ["pl"]}
    base = dispatch_op(cfg, "translate", body, actor_role="Admin")
    alias = dispatch_op(cfg, "run-translate", body, actor_role="Admin")
    assert "unknown operation" not in str(base.get("error") or "")
    assert "unknown operation" not in str(alias.get("error") or "")
    assert base.get("ok") is True
    assert alias.get("ok") is True


def test_doctor_and_analytics_hermetic(ops_project) -> None:
    _, cfg = ops_project
    doctor = dispatch_op(cfg, "doctor", {"skip_ollama": True}, actor_role="Admin")
    assert doctor.get("ok") is True
    assert doctor.get("data", {}).get("checks")
    analytics = dispatch_op(cfg, "analytics", {}, actor_role="Admin")
    assert analytics.get("ok") is True
    assert "runs" in analytics.get("data", {}) or analytics.get("summary")


def test_body_dict_only_ops_are_in_smoke_universe() -> None:
    """Document ops with no *Request parity entry; still covered by smoke."""
    universe = set(_ops_universe())
    missing = sorted(_BODY_DICT_ONLY - universe)
    assert not missing, f"body-dict-only ops not in smoke universe: {missing}"


def test_permissions_matrix_includes_new_ops() -> None:
    for op in ("documents", "agent-hardcoded", "ingest-visual"):
        assert op in DEFAULT_MATRIX
        assert op in OPERATIONS
    assert ROLE_SUPERVISOR in _roles_for("documents")
    assert ROLE_DEVELOPER in _roles_for("agent-hardcoded")
    assert ROLE_DEVELOPER in _roles_for("ingest-visual")
    manifest = build_commands_manifest(build_parser())["commands"]
    assert ROLE_SUPERVISOR in manifest["documents"]["roles"]
    assert ROLE_DEVELOPER in manifest["agent-hardcoded"]["roles"]
    assert ROLE_DEVELOPER in manifest["ingest-visual"]["roles"]
