"""Shipped browser runtime and the consumer key check (plan Part C, C5; ADR-118).

* :func:`op_runtime` installs, updates or checks the consumer's copy of
  ``llm_localizator/web_runtime/i18n.js`` at ``[web] runtime_path``. The copy is
  ours (version header); ``i18n.config.js`` next to it is the consumer's and is
  written once from a template, never overwritten.
* :func:`op_check_keys` is the no-LLM wiring check a consumer runs from its own
  tests: every literal key used through ``i18n.t('…')`` / ``data-i18n*`` under
  ``[scan] src_dirs`` exists in the source catalogue, unused keys are listed, and
  each QA marker locale (en-XX) still matches what ``pseudo`` would write now.

Exit codes are CI-friendly: 0 clean, 1 findings (drift, missing keys, stale
en-XX; unused keys only with ``strict``), 2 configuration error.
"""

from __future__ import annotations

from pathlib import Path

from ..catalog import catalog_for
from ..catalog.io import atomic_write_json
from ..core.source_quality import pseudo_text
from ..core.standards import get_standard
from ..projects import ProjectConfig
from ..scan.locate import source_files
from ..scan.usage_calls import ECOSYSTEM_SUFFIXES, KeyUsage, collect_ecosystem_usage, collect_key_usage
from ..web_runtime import CONFIG_TEMPLATE, RUNTIME_FILE, runtime_version, shipped_version
from .types import OpResult

__all__ = ["op_runtime", "op_check_keys", "RUNTIME_ACTIONS", "KEY_FILE_SUFFIXES"]

RUNTIME_ACTIONS = ("install", "update", "check")

KEY_FILE_SUFFIXES = (
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".html", ".htm", ".py", ".jinja", ".jinja2", ".j2", ".hbs", ".ejs",
) + ECOSYSTEM_SUFFIXES

_DEFAULT_PSEUDO_FACTOR = 1.4


def _result(command: str, ok: bool, code: int, summary: str, lines=None, data=None) -> OpResult:
    return OpResult(ok=ok, exit_code=code, command=command, summary=summary,
                    lines=list(lines or []), data=dict(data or {}))


# --------------------------------------------------------------------- runtime


def runtime_target(cfg: ProjectConfig, override: str | None = None) -> Path | None:
    """The consumer's i18n.js path, or ``None`` when no runtime path is configured."""
    raw = (override or getattr(cfg, "web_runtime_path", "") or "").strip()
    if not raw:
        return None
    root = Path(cfg.root).resolve()
    path = (root / raw).resolve()
    if path.suffix.lower() != ".js":
        path = path / RUNTIME_FILE.name
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"runtime path {raw!r} is outside the project root") from exc
    return path


def _rel(cfg: ProjectConfig, path: Path) -> str:
    try:
        return path.relative_to(Path(cfg.root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _config_text(cfg: ProjectConfig) -> str:
    locales: list[str] = []
    for code in [cfg.source_locale, *cfg.targets, *getattr(cfg, "frozen", [])]:
        if code and code not in locales:
            locales.append(code)
    text = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    return (text.replace("__PROJECT__", cfg.name)
            .replace("__LOCALES__", "[" + ", ".join(f"'{c}'" for c in locales) + "]"))


def op_runtime(
    cfg: ProjectConfig, action: str, *, force: bool = False, path: str | None = None,
) -> OpResult:
    """``install`` / ``update`` / ``check`` the consumer copy of the shipped runtime."""
    command = f"runtime {action}"
    if action not in RUNTIME_ACTIONS:
        return _result(command, False, 2, f"unknown action {action!r} ({'|'.join(RUNTIME_ACTIONS)})")
    try:
        target = runtime_target(cfg, path)
    except ValueError as exc:
        return _result(command, False, 2, str(exc))
    if target is None:
        return _result(command, False, 2,
                       "no runtime path: set [web] runtime_path in .llm-localize.toml or pass --path")
    shipped = RUNTIME_FILE.read_bytes()
    version = shipped_version()
    rel = _rel(cfg, target)
    data = {"path": rel, "shipped": version, "installed": None, "state": "missing"}
    current = target.read_bytes() if target.is_file() else None
    if current is not None:
        data["installed"] = runtime_version(current.decode("utf-8", errors="replace"))
        if data["installed"] is None:
            data["state"] = "foreign"
        # git autocrlf may check either copy out with CRLF; that is not an edit.
        elif current.replace(b"\r\n", b"\n") == shipped.replace(b"\r\n", b"\n"):
            data["state"] = "current"
        elif data["installed"] == version:
            data["state"] = "modified"
        else:
            data["state"] = "outdated"
    state = data["state"]
    config_path = target.parent / CONFIG_TEMPLATE.name
    data["config"] = _rel(cfg, config_path) if config_path.is_file() else None

    if action == "check":
        messages = {
            "current": f"{rel}: runtime v{version}, up to date",
            "missing": f"{rel}: runtime not installed (llm-localizator runtime install {cfg.name})",
            "foreign": f"{rel}: not an llm-localizator runtime (no version header)",
            "modified": f"{rel}: runtime v{version} edited locally; runtime update restores it",
            "outdated": f"{rel}: runtime v{data['installed']} installed, v{version} shipped "
                        "(llm-localizator runtime update)",
        }
        lines = [] if data["config"] else [f"warning: no {CONFIG_TEMPLATE.name} next to the runtime"]
        return _result(command, state == "current", 0 if state == "current" else 1,
                       messages[state], lines, data)

    if state == "foreign" and not force:
        return _result(command, False, 1,
                       f"{rel} exists and is not an llm-localizator runtime; pass --force to replace it",
                       data=data)
    if action == "update" and state == "missing":
        return _result(command, False, 1,
                       f"{rel}: runtime not installed; run llm-localizator runtime install {cfg.name}",
                       data=data)
    lines: list[str] = []
    if state == "current":
        summary = f"{rel}: runtime v{version} already up to date"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(shipped)
        before = f"v{data['installed']}" if data["installed"] else state
        summary = f"{rel}: runtime v{version} written (was {before})"
        data["state"] = "current"
        data["installed"] = version
    if action == "install" and not config_path.exists():
        config_path.write_text(_config_text(cfg), encoding="utf-8")
        data["config"] = _rel(cfg, config_path)
        lines.append(f"{data['config']}: config template written; load it before i18n.js")
    return _result(command, True, 0, summary, lines, data)


# ------------------------------------------------------------------ check-keys

# Key extraction and the source walker live in scan/ (usage_calls, locate; ADR-120).


def _collect_usage(cfg: ProjectConfig) -> tuple[KeyUsage, int]:
    usage = KeyUsage()
    files = 0
    root = Path(cfg.root)
    for path in source_files(cfg, KEY_FILE_SUFFIXES):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if runtime_version(text) is not None or path.name == CONFIG_TEMPLATE.name:
            continue  # the runtime's own doc examples are not usage
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        files += 1
        if path.suffix.lower() in ECOSYSTEM_SUFFIXES:
            collect_ecosystem_usage(text, rel, path.suffix, usage)
        else:
            collect_key_usage(text, rel, usage)
    return usage, files


def _qa_findings(cfg: ProjectConfig, catalog, namespaces, source: dict[str, str]) -> list[dict]:
    configured = list(getattr(cfg, "qa_locales", []) or [])
    standard = get_standard(getattr(cfg, "catalog_standard", None))
    out: list[dict] = []
    for qa in configured or ["en-XX"]:
        merged: dict[str, str] = {}
        for ns in namespaces:
            for key, value in catalog.load(qa, ns).items():
                merged[f"{ns}.{key}" if ns else key] = value
        if not merged:
            if configured:
                out.append({"locale": qa, "state": "missing", "missing": len(source), "extra": 0,
                            "changed": 0})
            continue
        style = "xxxx" if qa.upper().endswith("-XX") else "accents"
        missing = sorted(set(source) - set(merged))
        extra = sorted(set(merged) - set(source))
        changed = sorted(
            key for key in set(source) & set(merged)
            if isinstance(source[key], str) and merged[key] != pseudo_text(
                source[key], standard.tokens(source[key]),
                length_factor=_DEFAULT_PSEUDO_FACTOR, style=style)
        )
        state = "stale" if (missing or extra or changed) else "current"
        out.append({"locale": qa, "state": state, "missing": len(missing), "extra": len(extra),
                    "changed": len(changed), "examples": (missing + changed)[:5]})
    return out


def _write_roles(cfg: ProjectConfig, roles: dict[str, str]) -> None:
    """Key -> UI role, read by translate prompts (ADR-129). Engine data home only."""
    import json

    try:
        out = Path(cfg.data_root()) / "usage" / "roles.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, dict(sorted(roles.items())), indent=1)
    except OSError:
        pass


def load_roles(cfg: ProjectConfig) -> dict[str, str]:
    import json

    try:
        data = json.loads((Path(cfg.data_root()) / "usage" / "roles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def op_check_keys(cfg: ProjectConfig, *, strict: bool = False, qa: bool = True) -> OpResult:
    """Literal keys used in source vs the source catalogue, plus QA-locale staleness."""
    command = "check-keys"
    if not cfg.scan_src_dirs:
        return _result(command, False, 2, "no [scan] src_dirs configured; nothing to check")
    catalog = catalog_for(cfg)
    namespaces = cfg.namespaces_for(catalog)
    source: dict[str, str] = {}
    for ns in namespaces:
        for key, value in catalog.load(cfg.source_locale, ns).items():
            source[f"{ns}.{key}" if ns else key] = value
    usage, files = _collect_usage(cfg)
    _write_roles(cfg, usage.roles)
    tails = {k: [k.split(".", i)[-1] for i in range(0, k.count(".") + 1)] for k in source}
    known_tails = {t for ts in tails.values() for t in ts}
    # Keys from the per-ecosystem collector (R.string.x, NSLocalizedString, l10n.x) are bare names: a catalogue
    # namespace in front of them (``strings.x``) does not make them missing.
    missing = {k: v for k, v in usage.keys.items()
               if k not in source and not (k in usage.eco and k in known_tails)}
    unused = sorted(
        k for k in source
        if not usage.covers(k) and not any(t in usage.eco for t in tails[k])
    )
    qa_rows = _qa_findings(cfg, catalog, namespaces, source) if qa else []
    stale = [row for row in qa_rows if row["state"] != "current"]

    lines: list[str] = []
    for key in sorted(missing):
        sites = missing[key]
        more = f" (+{len(sites) - 3} more)" if len(sites) > 3 else ""
        lines.append(f"missing\t{key}\t{', '.join(sites[:3])}{more}")
    for key in unused:
        lines.append(f"unused\t{key}")
    for row in stale:
        lines.append(f"stale\t{row['locale']}\t{row['missing']} missing, {row['extra']} extra, "
                     f"{row['changed']} changed (llm-localizator pseudo {cfg.name} --locale {row['locale']})")
    if usage.dynamic:
        lines.append(f"info\t{len(usage.dynamic)} dynamic key site(s) not checked, e.g. "
                     + ", ".join(usage.dynamic[:3]))

    parts = [f"{len(usage.keys)} keys used in {files} files"]
    if missing:
        parts.append(f"{len(missing)} missing from the source catalogue")
    if unused:
        parts.append(f"{len(unused)} unused")
    for row in stale:
        parts.append(f"{row['locale']} {row['state']}")
    failed = bool(missing or stale or (strict and unused))
    return _result(
        command, not failed, 1 if failed else 0, ", ".join(parts), lines,
        {
            "files": files,
            "used": len(usage.keys),
            "missing": {k: v for k, v in sorted(missing.items())},
            "unused": unused,
            "dynamic_prefixes": sorted(usage.prefixes),
            "dynamic_sites": usage.dynamic,
            "qa": qa_rows,
        },
    )
