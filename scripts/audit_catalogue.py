"""Read-only defect audit of a project's translations.

    python scripts/audit_catalogue.py --project my-app --config path/to/.llm-localize.toml
    python scripts/audit_catalogue.py --synth --defects        # the seeded synthetic project

Prints, per defect class and locale, how many translations carry it, which model and channel
wrote them and when, plus a few samples. Nothing is written. The classes are the same ones the
synthetic scorecard (tests/synth) seeds, so a real project and a synthetic one give comparable
tables, and a class that shows up here but not in the scorecard is the next test to write.

Classes: hard (a translate/import gate would refuse it now): ``backslash`` ``placeholder``
``plural`` ``forbidden-term`` ``html`` ``literal`` ``foreign-script`` ``other-hard``;
soft: ``latin-leftover`` ``english-fragment`` ``glossary-drift``; and ``identical`` (source
echoed back, usually plain backlog).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_localizator.catalog import build_catalog  # noqa: E402
from llm_localizator.catalog.provenance import provider_of  # noqa: E402
from llm_localizator.catalog.state import StateStore  # noqa: E402
from llm_localizator.core.script_checks import foreign_script_hard_gate, latin_leftover_issues  # noqa: E402
from llm_localizator.core.standards import get_standard  # noqa: E402
from llm_localizator.core.validate import (  # noqa: E402
    check_untranslated_fragments,
    classify_failure,
    glossary_violations,
    validate_translation,
)
from llm_localizator.projects import GlossaryCache, resolve  # noqa: E402

HARD = ("backslash", "placeholder", "plural", "forbidden-term", "html", "literal",
        "foreign-script", "other-hard")
SOFT = ("latin-leftover", "english-fragment", "glossary-drift", "identical")
_BY_CODE = {"V39": "backslash", "V02": "placeholder", "V03": "plural", "V04": "forbidden-term",
            "V27": "html", "V32": "literal"}


def classify(source: str, text: str, locale: str, glossary: dict, standard) -> list[str]:
    """Every defect class one translation carries (empty when it is clean)."""
    classes: list[str] = []
    ok, reason = validate_translation(source, text, locale, glossary, standard=standard)
    if not ok:
        classes.append(_BY_CODE.get(classify_failure(reason), "other-hard"))
    if foreign_script_hard_gate(text, locale):
        classes.append("foreign-script")
    if latin_leftover_issues(source, text, locale):
        classes.append("latin-leftover")
    if check_untranslated_fragments(text, locale):
        classes.append("english-fragment")
    if any(not p.blocking for p in glossary_violations(source, text, glossary, locale)):
        classes.append("glossary-drift")
    if text.strip() == source.strip() and len(source.split()) >= 2 and any(c.isalpha() for c in source):
        classes.append("identical")
    return classes


def audit(cfg) -> list[dict]:
    """One row per (locale, namespace, key, class)."""
    catalog = build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)
    state = StateStore(cfg.state_root())
    glossary_cache = GlossaryCache(
        cfg.glossary_path, shared=list(getattr(cfg, "glossary_shared", []) or []),
    )
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    rows: list[dict] = []
    for ns in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, ns)
        glossary = glossary_cache.get(cfg.glossary_domains_for(ns))
        for locale in cfg.targets:
            target = catalog.load(locale, ns)
            for key, src in source.items():
                text = target.get(key)
                if not isinstance(src, str) or not isinstance(text, str) or cfg.is_skipped(ns, key):
                    continue
                entry = state.entry(locale, ns, key) or {}
                for cls in classify(src, text, locale, glossary, standard):
                    rows.append({
                        "locale": locale, "namespace": ns, "key": key, "class": cls,
                        "model": entry.get("model") or "", "provider": provider_of(entry) if entry else "",
                        "status": entry.get("status") or "", "date": str(entry.get("translated_at") or "")[:10],
                        "text": text[:80],
                    })
    return rows


def _table(rows: list[dict], locales: list[str], samples: int) -> list[str]:
    lines = [f"{'class':<16}" + "".join(f"{loc:>7}" for loc in locales) + "   writers (model/channel, top 3)"]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_class[row["class"]].append(row)
    for cls in (*HARD, *SOFT):
        found = by_class.get(cls, [])
        if not found:
            continue
        counts = Counter(r["locale"] for r in found)
        writers = Counter(f"{r['model'] or '?'}/{r['provider'] or '?'}" for r in found).most_common(3)
        lines.append(
            f"{cls:<16}" + "".join(f"{counts.get(loc, 0):>7}" for loc in locales)
            + "   " + ", ".join(f"{name} x{n}" for name, n in writers)
        )
        for row in found[:samples]:
            lines.append(f"    {row['locale']} {row['namespace']}.{row['key']}: {row['text']!r}")
    if len(lines) == 1:
        lines.append("no defects found")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--synth", action="store_true", help="Audit the synthetic project instead")
    parser.add_argument("--defects", action="store_true", help="With --synth: seed the bridge defects")
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--json", type=Path, default=None, help="Write every row to this file")
    args = parser.parse_args(argv)

    if args.synth:
        import tempfile

        from tests.synth.factory import build_project
        from tests.synth.specs import DEFECTS

        tmp = Path(tempfile.mkdtemp(prefix="synth-"))
        cfg = build_project(tmp, defects=DEFECTS if args.defects else None).config()
        print(f"synthetic project at {tmp}")
    else:
        cfg = resolve(args.project, args.config)
    rows = audit(cfg)
    locales = list(cfg.targets)
    print("\n".join(_table(rows, locales, args.samples)))
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
