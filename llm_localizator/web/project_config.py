"""Project prompt/glossary settings — known TOML keys only (W-07)."""

from __future__ import annotations

from typing import Any

import tomlkit

from ..core.cldr import language_name
from ..pipeline.prompts import PROMPT_FAMILIES
from ..projects.config import ConfigError, ProjectConfig, load_config
from ..projects.context import effective_glossary_for, glossary_conflicts
from ..projects.registry import load_registry
from .config_write import write_config_atomically

__all__ = [
    "project_config_view",
    "save_project_config",
]


def _display_path(cfg: ProjectConfig, path) -> str:
    if path is None:
        return ""
    if cfg.root is not None:
        try:
            return path.relative_to(cfg.root).as_posix()
        except ValueError:
            return str(path)
    return str(path)


def _prompt_table(doc):
    prompt = doc.get("prompt")
    if not isinstance(prompt, dict):
        prompt = tomlkit.table()
        doc["prompt"] = prompt
    return prompt


def _voice_or_prompt_table(doc, key: str):
    """``[voice]`` owns description / audience / tone once it holds one (C-001);
    otherwise those two stay in ``[prompt]``. Writing both would be a load error."""
    if key in ("description", "audience", "tone"):
        voice = doc.get("voice")
        if key == "tone" or (isinstance(voice, dict) and key in voice):
            if not isinstance(voice, dict):
                voice = tomlkit.table()
                doc["voice"] = voice
            return voice
    return _prompt_table(doc)


def _term_count(path) -> int:
    try:
        return len(effective_glossary_for(path).get("terms") or {})
    except Exception:  # unreadable glossary: show zero rather than fail the page
        return 0


def _attachable(cfg: ProjectConfig) -> list[dict[str, Any]]:
    """Other registered projects that own a glossary (ADR-42: attach is read-only)."""
    out: list[dict[str, Any]] = []
    own = cfg.config_path.resolve() if cfg.config_path else None
    try:
        entries = load_registry()
    except ConfigError:
        return out
    for name, entry in sorted(entries.items()):
        try:
            if own is not None and entry.config_path.resolve() == own:
                continue
            other = load_config(entry.config_path)
        except Exception:
            continue
        if other.glossary_path is None or not other.glossary_path.exists():
            continue
        out.append({
            "name": name,
            "path": _display_path(cfg, other.glossary_path),
            "terms": _term_count(other.glossary_path),
        })
    return out


def project_config_view(cfg: ProjectConfig) -> dict[str, Any]:
    glossary = _display_path(cfg, cfg.glossary_path)
    rows = []
    if cfg.glossary_path is not None:
        rows.append({
            "kind": "own", "name": cfg.name or "project", "path": glossary,
            "terms": _term_count(cfg.glossary_path),
        })
    for path in cfg.glossary_shared:
        rows.append({
            "kind": "shared", "name": path.parent.name or path.name,
            "path": _display_path(cfg, path), "terms": _term_count(path),
        })
    conflicts = (
        glossary_conflicts(cfg.glossary_path, list(cfg.glossary_shared))
        if cfg.glossary_shared else []
    )
    return {
        "projectName": cfg.name,
        "displayName": cfg.display_name,
        "description": cfg.description,
        "audience": cfg.audience,
        "tone": cfg.tone,
        "severity": dict(cfg.severity_overrides),
        "exclude": {
            "keys": list(cfg.exclude_keys),
            "sourceRegex": [r.pattern for r in cfg.exclude_source],
        },
        "domain": cfg.domain,
        "sourceLocale": cfg.source_locale,
        "localeNames": {
            loc: language_name(loc) for loc in {cfg.source_locale, "en", *cfg.targets}
        },
        "modelRoster": sorted({m for m in cfg.models.values() if m} | set(cfg.model_prompts)),
        "localize": cfg.prompt_localize,
        "localeNotes": {
            loc: notes for loc, (_reg, notes) in cfg.locale_styles.items() if notes
        },
        "models": {
            model: {"text": text, "localize": localize}
            for model, (text, localize) in cfg.model_prompts.items()
        },
        "bridge": {
            "mode": cfg.bridge_mode, "locale": cfg.bridge_locale,
            "model": cfg.bridge_model, "store": cfg.bridge_store,
        },
        "pivots": dict(cfg.pivots),
        "glossaryRows": rows,
        "attachable": _attachable(cfg),
        "glossaryConflict": cfg.glossary_conflict,
        "conflicts": conflicts,
        "ok": True,
        "family": cfg.prompt_family,
        "localeFamilies": dict(cfg.locale_prompt_families),
        "glossary": glossary,
        "glossaryDomains": {
            ns: list(domains) for ns, domains in cfg.glossary_domains.items()
        },
        "glossaryShared": [_display_path(cfg, path) for path in cfg.glossary_shared],
        "tmShared": ", ".join(_display_path(cfg, p) for p in cfg.tm_shared_all()),
        "tmWrite": _display_path(cfg, cfg.tm_write),
        "families": sorted(PROMPT_FAMILIES),
        "targets": list(cfg.targets),
        # [scan] settings (M6): what the hardcoded-string scanner reads and skips.
        "scan": {
            "adapter": cfg.scan_adapter or "",
            "srcDirs": list(cfg.scan_src_dirs),
            "exclude": list(cfg.scan_exclude),
            "unskip": list(cfg.scan_unskip),
            "tFunctions": list(cfg.scan_t_functions),
            "contentGlobs": list(cfg.scan_content_globs),
            "unusedAllow": list(cfg.scan_unused_allow),
            "directiveAliases": bool(cfg.scan_directive_aliases),
        },
    }


#: Web field → ``[scan]`` key for the list settings.
_SCAN_LISTS = {
    "srcDirs": "src_dirs", "exclude": "exclude", "unskip": "unskip", "tFunctions": "t_functions",
    "contentGlobs": "content_globs", "unusedAllow": "unused_allow",
}


def _apply_scan(doc, scan: dict[str, Any]) -> str | None:
    """Write the ``[scan]`` fields from the web form; return an error message for a malformed value."""
    table = doc.get("scan")
    if not isinstance(table, dict):
        table = tomlkit.table()
        doc["scan"] = table
    for field, key in _SCAN_LISTS.items():
        if field not in scan:
            continue
        raw = scan[field]
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            return f"[scan] {key} must be a list of strings"
        items = [x.strip() for x in raw if x.strip()]
        if items:
            arr = tomlkit.array()
            for item in items:
                arr.append(item)
            table[key] = arr
        elif key in table:
            del table[key]
    if "adapter" in scan:
        text = str(scan.get("adapter") or "").strip()
        if text:
            table["adapter"] = text
        elif "adapter" in table:
            del table["adapter"]
    if "directiveAliases" in scan:
        value = scan["directiveAliases"]
        if not isinstance(value, bool):
            return "[scan] directive_aliases must be true or false"
        if value:
            if "directive_aliases" in table:
                del table["directive_aliases"]  # true is the default
        else:
            table["directive_aliases"] = False
    if not len(table):
        del doc["scan"]
    return None


def save_project_config(
    cfg: ProjectConfig,
    *,
    family: str | None = None,
    locale_families: dict[str, str] | None = None,
    glossary: str | None = None,
    glossary_domains: dict[str, list[str]] | None = None,
    glossary_shared: list[str] | None = None,
    tm_shared: str | None = None,
    tm_write: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    audience: str | None = None,
    tone: str | None = None,
    domain: str | None = None,
    localize: str | None = None,
    glossary_conflict: str | None = None,
    locale_notes: dict[str, str] | None = None,
    models: dict[str, dict[str, Any]] | None = None,
    bridge: dict[str, Any] | None = None,
    pivots: dict[str, str] | None = None,
    source_locale: str | None = None,
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate prompt/glossary fields. Replace the file only after load_config accepts it."""
    path = cfg.config_path
    if path is None:
        return {"ok": False, "error": "config path is not set"}
    original = path.read_text(encoding="utf-8")
    doc = tomlkit.parse(original)

    if family is not None:
        prompt = _prompt_table(doc)
        prompt["family"] = str(family)

    if locale_families is not None:
        locales = doc.get("locales")
        if not isinstance(locales, dict):
            return {"ok": False, "error": f"{path}: [locales] table is missing"}
        table = tomlkit.table()
        for loc, fam in locale_families.items():
            table[str(loc)] = str(fam)
        locales["prompt_family"] = table

    if glossary is not None:
        prompt = _prompt_table(doc)
        text = str(glossary).strip()
        if text:
            prompt["glossary"] = text
        elif "glossary" in prompt:
            del prompt["glossary"]

    if glossary_domains is not None:
        prompt = _prompt_table(doc)
        table = tomlkit.table()
        for ns, domains in glossary_domains.items():
            arr = tomlkit.array()
            for item in domains:
                arr.append(str(item))
            table[str(ns)] = arr
        prompt["glossary_domains"] = table

    if glossary_shared is not None:
        prompt = _prompt_table(doc)
        items = [str(item).strip() for item in glossary_shared if str(item).strip()]
        if items:
            arr = tomlkit.array()
            for item in items:
                arr.append(item)
            prompt["glossary_shared"] = arr
        elif "glossary_shared" in prompt:
            del prompt["glossary_shared"]

    if tm_shared is not None:
        prompt = _prompt_table(doc)
        parts = [p.strip() for p in str(tm_shared).split(",") if p.strip()]
        if len(parts) == 1:
            prompt["tm_shared"] = parts[0]
        elif parts:
            arr = tomlkit.array()
            for item in parts:
                arr.append(item)
            prompt["tm_shared"] = arr
        elif "tm_shared" in prompt:
            del prompt["tm_shared"]

    if tm_write is not None:
        prompt = _prompt_table(doc)
        text = str(tm_write).strip()
        if text:
            prompt["tm_write"] = text
        elif "tm_write" in prompt:
            del prompt["tm_write"]

    def _set_text(table, key: str, value: str | None) -> None:
        text = str(value or "").strip()
        if text:
            table[key] = text
        elif key in table:
            del table[key]

    if source_locale is not None:
        project = doc.get("project")
        if not isinstance(project, dict):
            return {"ok": False, "error": f"{path}: [project] table is missing"}
        _set_text(project, "source_locale", source_locale)

    if display_name is not None:
        project = doc.get("project")
        if not isinstance(project, dict):
            return {"ok": False, "error": f"{path}: [project] table is missing"}
        _set_text(project, "display_name", display_name)

    for key, value in (
        ("description", description), ("audience", audience), ("tone", tone),
        ("domain", domain), ("localize", localize), ("glossary_conflict", glossary_conflict),
    ):
        if value is not None:
            _set_text(_voice_or_prompt_table(doc, key), key, value)

    if locale_notes is not None:
        prompt = _prompt_table(doc)
        styles = prompt.get("styles")
        if not isinstance(styles, dict):
            styles = tomlkit.table(is_super_table=True)
            prompt["styles"] = styles
        wanted = {str(k): str(v).strip() for k, v in locale_notes.items() if str(v).strip()}
        for loc in list(styles):
            if loc not in wanted:
                table = styles[loc]
                if isinstance(table, dict) and "notes" in table:
                    del table["notes"]
                if not table:
                    del styles[loc]
        for loc, note in wanted.items():
            if loc not in styles:
                styles[loc] = tomlkit.table()
            styles[loc]["notes"] = note
        if not styles:
            del prompt["styles"]

    if models is not None:
        prompt = _prompt_table(doc)
        table = tomlkit.table(is_super_table=True)
        for model, data in models.items():
            name = str(model).strip()
            if not name:
                continue
            row = tomlkit.table()
            text = str((data or {}).get("text") or "").strip()
            if text:
                row["text"] = text
            if (data or {}).get("localize"):
                row["localize"] = True
            table[name] = row
        if len(table):
            prompt["models"] = table
        elif "models" in prompt:
            del prompt["models"]

    if bridge is not None:
        mode = str(bridge.get("mode") or "none")
        if mode == "none":
            if "bridge" in doc:
                del doc["bridge"]
        else:
            table = tomlkit.table()
            table["mode"] = mode
            locale = str(bridge.get("locale") or "").strip()
            if mode == "custom" and locale:
                table["locale"] = locale
            model = str(bridge.get("model") or "").strip()
            if model:
                table["model"] = model
            if bridge.get("store") is False:
                table["store"] = False
            doc["bridge"] = table

    if pivots is not None:
        locales = doc.get("locales")
        if not isinstance(locales, dict):
            return {"ok": False, "error": f"{path}: [locales] table is missing"}
        wanted_pivots = {str(k): str(v) for k, v in pivots.items() if k and v}
        if wanted_pivots:
            table = tomlkit.table()
            for loc, ref in wanted_pivots.items():
                table[loc] = ref
            locales["pivots"] = table
        elif "pivots" in locales:
            del locales["pivots"]

    if scan is not None:
        if not isinstance(scan, dict):
            return {"ok": False, "error": "scan must be an object"}
        scan_err = _apply_scan(doc, scan)
        if scan_err:
            return {"ok": False, "error": scan_err}

    new_text = tomlkit.dumps(doc)
    err = write_config_atomically(path, new_text)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True}
