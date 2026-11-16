"""scripts/audit_catalogue.py reports the same classes the scorecard seeds."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .factory import build_project
from .specs import DEFECTS

_SPEC = importlib.util.spec_from_file_location(
    "audit_catalogue", Path(__file__).parent.parent.parent / "scripts" / "audit_catalogue.py",
)
audit_catalogue = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_catalogue)

# The scorecard names some classes differently from the audit; this is the whole mapping.
_AUDIT_CLASS = {"wrong-term": "glossary-drift"}


def test_audit_finds_every_seeded_defect_under_its_class(tmp_path) -> None:
    rows = audit_catalogue.audit(build_project(tmp_path, defects=DEFECTS).config())
    seen = {(r["locale"], r["namespace"], r["key"]): set() for r in rows}
    for r in rows:
        seen[(r["locale"], r["namespace"], r["key"])].add(r["class"])
    for d in DEFECTS:
        want = _AUDIT_CLASS.get(d.cls, d.cls)
        assert want in seen.get((d.locale, d.namespace, d.key), set()), (d.id, want)


def test_audit_reports_the_writer_of_each_defect(tmp_path) -> None:
    rows = audit_catalogue.audit(build_project(tmp_path, defects=DEFECTS).config())
    cut = next(r for r in rows if r["class"] == "backslash" and r["locale"] == "pl" and r["key"] == "resetHint")
    assert (cut["model"], cut["provider"]) == ("import", "import")


def test_a_clean_project_audits_clean(tmp_path) -> None:
    assert audit_catalogue.audit(build_project(tmp_path).config()) == []


def test_audit_is_read_only(tmp_path) -> None:
    project = build_project(tmp_path, defects=DEFECTS)
    before = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    audit_catalogue.audit(project.config())
    after = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    assert before == after
