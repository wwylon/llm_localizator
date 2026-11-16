"""Build a complete synthetic project on disk: config, glossary, catalogue, state.

    project = build_project(tmp_path)                    # clean gold set
    project = build_project(tmp_path, defects=DEFECTS)   # gold set with seeded defects

Deterministic: nothing here is random. ``load_config`` reads the written toml, so the CLI, the
audit script and the web server can all be pointed at the result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from llm_localizator.catalog.state import StateStore, make_entry
from llm_localizator.projects.config import ProjectConfig, load_config

from .specs import CONTEXT, GLOSSARY, GOLD, LOCALES, SOURCE, Defect

__all__ = ["SynthProject", "build_project", "defect_manifest", "gold_translator"]

_TOML = """\
[project]
name = "synth"
source_locale = "en"
data_home = "project"

[catalog]
format = "json-nested"
path = "messages/{{locale}}/{{namespace}}.json"

[locales]
targets = {targets}

[locales.models]
default = "testmodel"

[provider]
kind = "null"

[translate]
min_keys = 0

[prompt]
domain = "a card-game web application"
glossary = "glossary.json"
context_dir = "context"

[state]
dir = "messages/.state"
"""


@dataclass
class SynthProject:
    root: Path
    config_path: Path
    defects: list[Defect] = field(default_factory=list)

    def config(self) -> ProjectConfig:
        return load_config(self.config_path)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_project(
    root: Path,
    *,
    locales: list[str] | None = None,
    defects: list[Defect] | None = None,
) -> SynthProject:
    """Write the gold catalogue for ``locales`` and replace one value per seeded defect."""
    locales = list(locales or LOCALES)
    root = Path(root)
    for ns, values in SOURCE.items():
        _write(root / "messages" / "en" / f"{ns}.json", values)
    target_values = {loc: {ns: dict(vals) for ns, vals in GOLD[loc].items()} for loc in locales}
    picked = [d for d in (defects or []) if d.locale in target_values]
    for d in picked:
        target_values[d.locale][d.namespace][d.key] = d.value
    for loc, spaces in target_values.items():
        for ns, values in spaces.items():
            _write(root / "messages" / loc / f"{ns}.json", values)
    _write(root / "glossary.json", GLOSSARY)
    for ns, notes in CONTEXT.items():
        _write(root / "context" / f"{ns}.json", notes)
    toml = _TOML.format(targets=json.dumps(locales))
    config_path = root / ".llm-localize.toml"
    config_path.write_text(toml, encoding="utf-8")

    store = StateStore(root / "messages" / ".state")
    by_key = {(d.locale, d.namespace, d.key): d for d in picked}
    for loc, spaces in target_values.items():
        for ns, values in spaces.items():
            for key in values:
                d = by_key.get((loc, ns, key))
                prov = d.provenance if d else {"model": "gold-fixture", "provider": "local", "status": "machine"}
                store.record(loc, ns, key, make_entry(
                    SOURCE[ns][key], prov.get("model", "gold-fixture"), prov.get("status", "machine"),
                    provider=prov.get("provider"), target_value=values[key],
                ))
    store.save_all(locales)
    return SynthProject(root=root, config_path=config_path, defects=picked)


def defect_manifest(project: SynthProject) -> list[dict]:
    """The labelled truth, in the shape ``scripts/audit_catalogue.py`` reports classes."""
    return [
        {"id": d.id, "locale": d.locale, "namespace": d.namespace, "key": d.key,
         "class": d.cls, "expect": list(d.expect), "hard": d.hard}
        for d in project.defects
    ]


def gold_translator(locale: str):
    """``source -> gold translation``, also for the numeric stand-ins the pipeline puts in prompts."""
    from llm_localizator.pipeline.placeholder_mask import mask_bare_placeholders

    table: dict[str, str] = {}
    for ns, values in SOURCE.items():
        for key, src in values.items():
            tr = GOLD[locale][ns][key]
            table[src] = tr
            masked, mapping = mask_bare_placeholders(src)
            if mapping:
                masked_tr = tr
                for token, span in mapping.items():
                    masked_tr = masked_tr.replace(span, token)
                table[masked] = masked_tr
    return lambda source: table.get(source, source)
