"""Init operation."""

from __future__ import annotations

from pathlib import Path

from ..catalog.base import Catalog
from ..catalog.io import atomic_write_text
from ..projects import CONFIG_FILENAME, ConfigError, load_config, register_project
from ..projects.init_layout import (
    DEFAULT_DOMAIN,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    detect_layout,
    layouts_help,
    render_init_config,
    survey_layout,
)
from ..projects.taskqueue import write_blueprints
from .types import InitRequest, OpResult


def _usage_error(summary: str, *lines: str) -> OpResult:
    return OpResult(
        ok=False, exit_code=64, command="init", summary=summary, lines=list(lines),
    )


def _clean_targets(targets: list[str] | None, source_locale: str) -> list[str]:
    """Trimmed, de-duplicated target codes, without the source language."""
    seen: list[str] = []
    for raw in targets or []:
        code = str(raw).strip()
        if code and code != source_locale and code not in seen:
            seen.append(code)
    return seen


def _merge_config(existing: str, rendered: str, req: InitRequest) -> str:
    """Update only what the request names; every other setting and comment survives."""
    import tomlkit

    doc, fresh = tomlkit.parse(existing), tomlkit.parse(rendered)

    def put(table: str, key: str) -> None:
        if table not in doc:
            doc[table] = tomlkit.table()
        doc[table][key] = fresh[table][key]

    put("catalog", "format")
    put("catalog", "path")
    put("project", "source_locale")
    if req.name or "name" not in doc.get("project", {}):
        put("project", "name")
    if req.targets is not None or "locales" not in doc:
        put("locales", "targets")
    if req.model:
        if "locales" not in doc:
            doc["locales"] = tomlkit.table()
        doc["locales"].setdefault("models", tomlkit.table())["default"] = req.model
    if req.domain:
        put("prompt", "domain")
    if req.provider:
        put("provider", "kind")
    if "scan" not in doc and "scan" in fresh:
        doc["scan"] = fresh["scan"]
    return tomlkit.dumps(doc)


def op_init(req: InitRequest) -> OpResult:
    root = Path(req.directory or Path.cwd()).resolve()
    config_path = root / CONFIG_FILENAME
    lines: list[str] = []

    if config_path.exists() and not req.taskqueue and not req.force:
        return OpResult(
            ok=False,
            exit_code=1,
            command="init",
            summary=f"{CONFIG_FILENAME} already exists",
            lines=[f"{config_path} already exists"],
        )

    if req.catalog_format and not req.catalog_path:
        return _usage_error(
            "format requires path",
            "--format needs --path too, for example:",
            f"  llm-localizator init --format {req.catalog_format} --path 'i18n/{{locale}}.json'",
        )
    if req.catalog_path and not req.catalog_format:
        return _usage_error(
            "path requires format",
            "--path needs --format too (json-flat, json-nested, po, yaml, arb, android-xml), "
            "for example:",
            f"  llm-localizator init --format json-flat --path {req.catalog_path!r}",
        )

    if req.force or not config_path.exists():
        explicit_targets = _clean_targets(req.targets, req.source_locale)
        for code in explicit_targets:
            try:
                Catalog._validate_component(code, "locale")
            except ValueError as exc:
                return _usage_error(f"invalid target locale {code!r}", str(exc))

        if req.catalog_format:
            fmt, template, scanner = req.catalog_format, req.catalog_path, None
            lines.append(f"using {fmt} — {template}")
            namespaces, locales = [], []
        else:
            detected = detect_layout(root, req.source_locale)
            if detected is None:
                return OpResult(
                    ok=False,
                    exit_code=1,
                    command="init",
                    summary="could not detect catalogue layout",
                    lines=[
                        f"No message catalogue for '{req.source_locale}' found under {root}.",
                        "Put your source strings in one of these places, or say where they are.",
                        layouts_help(),
                    ],
                )
            fmt, template, scanner = detected
            namespaces, locales = survey_layout(root, template, fmt, req.source_locale)
            lines.append(f"detected {fmt} — {template}")
            lines.append(
                f"  {len(namespaces)} namespace(s), {len(locales)} existing locale(s)",
            )

        targets = explicit_targets if req.targets is not None else locales
        rendered = render_init_config(
            req.name or root.name, req.source_locale, fmt, template, targets, scanner,
            model=req.model or DEFAULT_MODEL,
            domain=req.domain or DEFAULT_DOMAIN,
            provider=req.provider or DEFAULT_PROVIDER,
        )
        if config_path.exists():
            rendered = _merge_config(config_path.read_text(encoding="utf-8"), rendered, req)
            lines.append("merged into the existing config (comments and other sections kept)")
        atomic_write_text(config_path, rendered)
        lines.append(f"wrote {config_path}")

    if req.approach:
        from .approaches import _write_approach

        _write_approach(config_path, req.approach)
        lines.append(f"approach: {req.approach}")
    cfg = load_config(config_path)

    if not req.no_register:
        try:
            registry = register_project(cfg.name, root)
            lines.append(f"registered '{cfg.name}' in {registry}")
        except ConfigError as exc:
            lines.append(f"NOT registered: {exc}")

    blueprints: list[str] = []
    if req.taskqueue:
        written = write_blueprints(cfg)
        for path in written:
            blueprints.append(str(path))
            lines.append(f"wrote {path}")
        lines.append("run 'tq sync' to register the tasks with the queue.")

    return OpResult(
        ok=True,
        exit_code=0,
        command="init",
        summary=f"initialized {cfg.name}",
        lines=lines,
        data={"project": cfg.name, "configPath": str(config_path), "blueprints": blueprints},
    )
