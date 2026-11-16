"""scripts/measure_validation.py: counts and the labelled false-positive gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.conftest import setup_project

_SPEC = importlib.util.spec_from_file_location(
    "measure_validation", Path(__file__).parent.parent / "scripts" / "measure_validation.py",
)
mv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mv)


def test_measure_counts_v14_per_locale(tmp_path, make_config, make_catalog) -> None:
    setup_project(
        tmp_path,
        {"a": "Please review the pending changes carefully", "b": "Sign in to your account today"},
        existing={"a": "Ok", "b": "Zaloguj sie do swojego konta dzisiaj"},
    )
    cfg = make_config(tmp_path)
    stats = mv.measure(cfg, make_catalog(cfg), ["pl"])
    assert stats["pl"]["v14"] >= 1
    assert 0 < stats["pl"]["v14_rate"] <= 1


def test_sample_csv_round_trips_into_a_false_positive_rate(tmp_path) -> None:
    path = tmp_path / "v13.csv"
    path.write_text(
        "locale,namespace,key,message,verdict\n"
        "pl,app,a,m,ok\npl,app,b,m,fp\npl,app,c,m,ok\npl,app,d,m,\n",
        encoding="utf-8",
    )
    rate, n = mv.false_positive_rate(path)
    assert n == 3 and abs(rate - 1 / 3) < 1e-9


def test_no_labels_gives_no_rate(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("locale,namespace,key,message,verdict\npl,app,a,m,\n", encoding="utf-8")
    assert mv.false_positive_rate(path) == (None, 0)
