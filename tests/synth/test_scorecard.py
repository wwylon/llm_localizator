"""The detector scorecard: every seeded defect is noticed, hard ones are refused on import,
and a clean project produces no findings at all (precision)."""

from __future__ import annotations

import json

import pytest

from .factory import build_project
from .scorecard import RATCHET_FILE, all_findings, compute, findings_by_key, import_outcome
from .specs import DEFECTS


@pytest.fixture(scope="module")
def dirty(tmp_path_factory):
    return build_project(tmp_path_factory.mktemp("dirty"), defects=DEFECTS)


def test_clean_project_has_no_findings_and_no_duplicates(tmp_path) -> None:
    findings = all_findings(build_project(tmp_path))
    assert findings == [], "\n".join(f"{f.check} {f.locale} {f.namespace}.{f.key}: {f.message}" for f in findings)


def test_no_finding_is_reported_twice(dirty) -> None:
    from .scorecard import all_findings as run

    rows = [(f.check, f.locale, f.namespace, f.key, f.message) for f in run(dirty)]
    assert len(rows) == len(set(rows))


@pytest.mark.parametrize("defect", DEFECTS, ids=lambda d: d.id)
def test_validate_notices_every_seeded_defect(dirty, defect) -> None:
    got = findings_by_key(dirty).get((defect.locale, defect.namespace, defect.key), set())
    assert set(defect.expect) <= got, f"{defect.id}: expected {defect.expect}, validate reported {sorted(got)}"


@pytest.mark.parametrize("defect", [d for d in DEFECTS if d.hard], ids=lambda d: d.id)
def test_import_refuses_hard_defects(tmp_path, defect) -> None:
    assert import_outcome(tmp_path, defect) == "rejected", f"{defect.id} was accepted by import"


def test_ratchet_never_gets_worse(tmp_path) -> None:
    now = compute(tmp_path)
    assert now["detected"] == now["defects"], f"missed: {now['missed']}"
    assert now["hard_rejected_on_import"] == now["hard_defects"], f"not rejected: {now['not_rejected']}"
    if not RATCHET_FILE.exists():
        pytest.skip("scorecard.json not recorded yet")
    recorded = json.loads(RATCHET_FILE.read_text(encoding="utf-8"))
    assert now["defects"] >= recorded["defects"], "a seeded defect was removed"
    assert now["detected"] >= recorded["detected"]
    assert now["hard_rejected_on_import"] >= recorded["hard_rejected_on_import"]
    assert now["clean_findings"] <= recorded["clean_findings"]
