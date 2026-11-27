"""Named TOML section parsers for :mod:`config_load` (keeps the facade smaller)."""

from __future__ import annotations

from pathlib import Path

from .config import ConfigError


def reject_unknown(section: str, values: object, known: set[str], path: Path) -> None:
    if not isinstance(values, dict):
        return
    bad = set(values) - known
    if bad:
        raise ConfigError(
            f"{path}: unknown key(s) in [{section}]: {', '.join(sorted(bad))}"
        )


def choice(label: str, value: object, allowed: tuple[str, ...], path: Path) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise ConfigError(
            f"{path}: {label} must be one of {', '.join(allowed)}, not {text!r}"
        )
    return text


def parse_bridge(raw: object, path: Path) -> dict:
    """``[bridge]`` mode, locale, model, store (ADR-60)."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [bridge] must be a table")
    reject_unknown("bridge", raw, {"mode", "locale", "model", "store"}, path)
    mode = choice("[bridge] mode", raw.get("mode", "none"), ("none", "en", "custom"), path)
    locale = str(raw.get("locale") or ("en" if mode == "en" else ""))
    store = raw.get("store", True)
    if not isinstance(store, bool):
        raise ConfigError(f"{path}: [bridge] store must be true or false")
    if mode == "custom" and not locale:
        raise ConfigError(f"{path}: [bridge] mode custom needs a locale")
    return {
        "bridge_mode": mode,
        "bridge_locale": locale if mode != "none" else "",
        "bridge_model": str(raw.get("model") or ""),
        "bridge_store": store,
    }


def parse_collections(raw: dict, path: Path) -> dict[str, dict]:
    collections_raw = raw.get("collections", {})
    if collections_raw and not isinstance(collections_raw, dict):
        raise ConfigError(f"{path}: [collections] must be a table of named roots")
    parsed_collections: dict[str, dict] = {}
    for coll_name, spec in dict(collections_raw or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: [collections.{coll_name}] must be a table")
        reject_unknown(
            f"collections.{coll_name}", spec, {"dir", "format", "kind"}, path,
        )
        kind = spec.get("kind")
        if kind not in (None, "remote"):
            raise ConfigError(
                f"{path}: [collections.{coll_name}] kind must be \"remote\" when set"
            )
        if kind == "remote" or spec.get("format") == "remote":
            if spec.get("dir"):
                raise ConfigError(
                    f"{path}: [collections.{coll_name}] remote collection has no dir"
                )
            parsed_collections[str(coll_name)] = {
                "kind": "remote", "dir": None, "format": "remote",
            }
        else:
            parsed_collections[str(coll_name)] = {
                "dir": spec.get("dir"),
                "format": spec.get("format") or "markdown",
                "kind": None,
            }
    return parsed_collections


def parse_budget(budget: dict, path: Path) -> tuple[dict, str, float, int]:
    rate_rows = budget.get("rates") or {}
    if rate_rows and not isinstance(rate_rows, dict):
        raise ConfigError(f"{path}: [budget.rates] must be a table")
    rate_fields = {
        "input", "output", "long_input", "long_output", "long_after_tokens",
        "usd_per_million_chars", "thinking",
    }
    for model_name, row in dict(rate_rows).items():
        if not isinstance(row, dict):
            raise ConfigError(f"{path}: [budget.rates.{model_name}] must be a table")
        reject_unknown(f"budget.rates.{model_name}", row, rate_fields, path)
    budget_mode = str(budget.get("mode", "on_request") or "on_request").strip().lower()
    if budget_mode not in {"on_request", "dynamic"}:
        raise ConfigError(
            f"{path}: [budget] mode must be \"on_request\" or \"dynamic\", not {budget_mode!r}"
        )
    output_expansion = float(budget.get("output_expansion", 2.0))
    if output_expansion <= 0:
        raise ConfigError(f"{path}: [budget] output_expansion must be > 0")
    thinking_tokens = int(budget.get("thinking_tokens", 1024))
    if thinking_tokens < 0:
        raise ConfigError(f"{path}: [budget] thinking_tokens must be >= 0")
    return rate_rows, budget_mode, output_expansion, thinking_tokens


def parse_workflows(raw: dict, path: Path) -> dict[str, dict]:
    workflows_raw = raw.get("workflows", {})
    workflows: dict[str, dict] = {}
    if workflows_raw:
        if not isinstance(workflows_raw, dict):
            raise ConfigError(f"{path}: [workflows] must be a table")
        from ..core.workflow_rules import normalize_workflow

        for wf_name, wf_table in workflows_raw.items():
            if not isinstance(wf_table, dict):
                raise ConfigError(f"{path}: [workflows.{wf_name}] must be a table")
            try:
                workflows[str(wf_name)] = normalize_workflow(
                    wf_table, f"[workflows.{wf_name}]",
                )
            except ValueError as exc:
                raise ConfigError(f"{path}: {exc}") from None

    return workflows
