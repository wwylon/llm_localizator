"""Measure V13 and V14 so their defaults can be changed on evidence, not a guess.

    python scripts/measure_validation.py --project my-app --locales pl,ar --sample 50 --out v13.csv

Prints, per locale: the V13 hit count, the V14 firing rate (the fraction of checked keys the
display-width expansion band flags), and writes a random sample of V13 hits to a CSV with an
empty ``verdict`` column. Label each row ``ok`` (a real miss) or ``fp`` (a false positive),
then re-run with ``--labelled v13.csv`` to get the false-positive rate.

Gates (plan-validation.md): V13 becomes blocking when the labelled false-positive rate is
under 5%; V14 becomes default-on when it fires on under 10% of keys. This script never
changes a default.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

from llm_localizator.catalog import build_catalog
from llm_localizator.pipeline.validate import run_validation
from llm_localizator.projects import resolve

V13_GATE = 0.05
V14_GATE = 0.10


def measure(cfg, catalog, locales: list[str]) -> dict:
    """Counts per locale from one validation run with the expansion band on."""
    report = run_validation(cfg, catalog, locales=locales, check_expansion=True)
    checked = max(1, report.checked_keys)
    out: dict[str, dict] = {}
    for locale in locales:
        rows = [f for f in report.findings if f.locale == locale]
        v13 = [f for f in rows if f.check == "V13"]
        v14 = [f for f in rows if f.check == "V14"]
        out[locale] = {
            "checked": checked,
            "v13": len(v13),
            "v14": len(v14),
            "v14_rate": len(v14) / checked,
            "v14_short": sum(1 for f in v14 if "short" in f.message),
            "terms": Counter(_term(f.message) for f in v13).most_common(5),
            "v13_findings": v13,
        }
    return out


def _term(message: str) -> str:
    marker = "glossary term '"
    if marker in message:
        return message.split(marker, 1)[1].split("'", 1)[0]
    return "?"


def write_sample(stats: dict, path: Path, size: int, seed: int = 0) -> int:
    rows = [
        (loc, f) for loc, data in stats.items() for f in data["v13_findings"]
    ]
    random.Random(seed).shuffle(rows)
    picked = rows[:size]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["locale", "namespace", "key", "message", "verdict"])
        for loc, f in picked:
            writer.writerow([loc, f.namespace, f.key, f.message, ""])
    return len(picked)


def false_positive_rate(path: Path) -> tuple[float | None, int]:
    """Share of labelled rows marked ``fp`` and how many rows were labelled."""
    with path.open(encoding="utf-8", newline="") as handle:
        verdicts = [row["verdict"].strip().lower() for row in csv.DictReader(handle)]
    labelled = [v for v in verdicts if v in {"ok", "fp"}]
    if not labelled:
        return None, 0
    return labelled.count("fp") / len(labelled), len(labelled)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--locales", default=None, help="Comma list (default: all targets)")
    parser.add_argument("--sample", type=int, default=50, help="V13 hits to write for labelling")
    parser.add_argument("--out", type=Path, default=None, help="CSV for the labelling sample")
    parser.add_argument("--labelled", type=Path, default=None, help="A labelled CSV to score")
    args = parser.parse_args(argv)

    cfg = resolve(args.project, args.config)
    locales = [p for p in (args.locales or "").split(",") if p] or list(cfg.targets)
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    stats = measure(cfg, catalog, locales)
    for locale, data in stats.items():
        print(
            f"{locale}: V13 {data['v13']}  V14 {data['v14']} "
            f"({data['v14_rate']:.1%} of {data['checked']} keys, {data['v14_short']} 'too short')"
        )
        if data["terms"]:
            print("  V13 terms: " + ", ".join(f"{t} x{n}" for t, n in data["terms"]))
    worst = max((d["v14_rate"] for d in stats.values()), default=0.0)
    print(f"V14 gate: {'PASS' if worst < V14_GATE else 'FAIL'} (worst {worst:.1%}, need < {V14_GATE:.0%})")
    if args.out:
        print(f"wrote {write_sample(stats, args.out, args.sample)} V13 row(s) to {args.out}")
    if args.labelled:
        rate, n = false_positive_rate(args.labelled)
        if rate is None:
            print("V13 gate: no labelled rows yet")
        else:
            print(f"V13 gate: {'PASS' if rate < V13_GATE else 'FAIL'} "
                  f"(false-positive rate {rate:.1%} over {n} rows, need < {V13_GATE:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
