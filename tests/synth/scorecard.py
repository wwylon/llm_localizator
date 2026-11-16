"""Measure how well the detectors and gates notice the seeded defects.

Used by ``test_scorecard.py`` (assertions and the ratchet) and by ``scripts/audit_catalogue.py
--synth`` (a printed table), so both report the same numbers.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.pipeline.validate import run_validation

from .factory import SynthProject, build_project
from .specs import DEFECTS, Defect

RATCHET_FILE = Path(__file__).with_name("scorecard.json")


def findings_by_key(project: SynthProject) -> dict[tuple[str, str, str], set[str]]:
    cfg = project.config()
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    report = run_validation(cfg, catalog, locales=cfg.targets, check_semantic=True)
    out: dict[tuple[str, str, str], set[str]] = {}
    for f in report.findings:
        out.setdefault((f.locale, f.namespace, f.key), set()).add(f.check)
    return out


def all_findings(project: SynthProject) -> list:
    cfg = project.config()
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    return run_validation(cfg, catalog, locales=cfg.targets, check_semantic=True).findings


def import_outcome(root: Path, defect: Defect) -> str:
    """Import the defective value into a clean project: ``rejected`` or ``accepted``."""
    project = build_project(root)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["namespace", "key", "en", defect.locale])
    from .specs import SOURCE

    writer.writerow([defect.namespace, defect.key, SOURCE[defect.namespace][defect.key], defect.value])
    out = dispatch_op(project.config(), "import", {
        "text": buf.getvalue(), "format": "csv", "locales": [defect.locale],
    }, actor_role="Admin")
    data = out.get("data") or out
    return "rejected" if int(data.get("rejected") or 0) else "accepted"


def compute(tmp_path: Path) -> dict:
    """The numbers the ratchet tracks."""
    clean = build_project(tmp_path / "clean")
    dirty = build_project(tmp_path / "dirty", defects=DEFECTS)
    seen = findings_by_key(dirty)
    hits = {d.id: set(d.expect) <= seen.get((d.locale, d.namespace, d.key), set()) for d in DEFECTS}
    hard = [d for d in DEFECTS if d.hard]
    rejected = {d.id: import_outcome(tmp_path / f"imp-{d.id}", d) == "rejected" for d in hard}
    clean_findings = all_findings(clean)
    return {
        "defects": len(DEFECTS),
        "detected": sum(hits.values()),
        "hard_defects": len(hard),
        "hard_rejected_on_import": sum(rejected.values()),
        "clean_findings": len(clean_findings),
        "missed": sorted(k for k, v in hits.items() if not v),
        "not_rejected": sorted(k for k, v in rejected.items() if not v),
    }
