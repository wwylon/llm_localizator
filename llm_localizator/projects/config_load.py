"""Parse ``.llm-localize.toml`` into :class:`ProjectConfig`.

Extracted from ``config.py`` so the dataclass surface stays readable.
Public entry point remains ``projects.config.load_config``.
"""

from __future__ import annotations

import re
import tomllib
import warnings
from pathlib import Path

from .config import (
    ConfigError,
    LocaleRole,
    NamedProvider,
    PLACE_POLICIES,
    ProjectConfig,
    ProviderConfig,
    STYLE_PRESETS,
    _named_from_provider,
    _register_wording,
)
from .qa_config import parse_qa
from .config_load_sections import (
    parse_bridge as _parse_bridge,
    parse_budget as _parse_budget,
    parse_collections as _parse_collections,
    parse_workflows as _parse_workflows,
)


def _approach(translate: dict, path: Path) -> str:
    from .config import APPROACH_IDS

    value = str(translate.get("approach", "") or "").strip()
    if value and value not in APPROACH_IDS:
        raise ConfigError(
            f"{path}: [translate] approach must be one of {', '.join(APPROACH_IDS)}, got {value!r}")
    return value

def _as_path(root: Path, value: object) -> Path | None:
    if not value:
        return None
    p = Path(str(value))
    return p if p.is_absolute() else (root / p)


def _sidecar_path(data_base: Path, value: object, default_leaf: str | None = None) -> Path | None:
    """Resolve an engine-sidecar path against ``data_base`` (ADR-112).

    Absolute overrides win. Relative overrides and defaults sit under the
    project's data root (engine home or consumer root).
    """
    if value in (None, ""):
        return (data_base / default_leaf) if default_leaf else None
    p = Path(str(value))
    return p if p.is_absolute() else (data_base / p)


def _qa_locales(web: dict, path: Path) -> list[str]:
    """ADR-110: opt-in QA marker locales for the review UI picker / URL prefix."""
    from ..web.ui_locale_path import KNOWN_QA_LOCALES

    raw = web.get("qa_locales", [])
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: [web] qa_locales must be an array of locale codes")
    out: list[str] = []
    for item in raw:
        code = str(item).strip()
        if not code:
            continue
        if code not in KNOWN_QA_LOCALES:
            known = ", ".join(sorted(KNOWN_QA_LOCALES))
            raise ConfigError(
                f"{path}: [web] qa_locales entry {code!r} is not a known QA "
                f"marker ({known})"
            )
        if code not in out:
            out.append(code)
    return out


def _org_glossary(org: dict) -> list[Path]:
    if not org["use"]:
        return []
    from .registry import org_paths
    return [org_paths()["glossary"]]


def _org_tm(org: dict) -> list[Path]:
    if not org["use"]:
        return []
    from .registry import org_paths
    return [org_paths()["tm"]]


def _org_write(org: dict) -> Path | None:
    if not (org["use"] and org["contribute"]):
        return None
    from .registry import org_paths
    return org_paths()["tm"]


def _parse_git_host(raw: object, path: Path) -> dict:
    """``[git_host]``: opt-in pull requests for catalogue changes (C-015, ADR-101)."""
    base = {"enabled": False, "kind": "github", "remote": "origin", "base": "main", "branch_prefix": "l10n/"}
    if not raw:
        return base
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [git_host] must be a table")
    _reject_unknown("git_host", raw, {"enabled", "kind", "remote", "base", "branch_prefix"}, path)
    out = dict(base)
    out["enabled"] = bool(raw.get("enabled"))
    for name in ("kind", "remote", "base", "branch_prefix"):
        if name in raw:
            value = str(raw[name]).strip()
            if not value or any(c.isspace() for c in value) or value.startswith("-"):
                raise ConfigError(f"{path}: [git_host] {name} must be a single word without a leading dash")
            out[name] = value
    if out["kind"] != "github":
        raise ConfigError(f"{path}: [git_host] kind must be github")
    return out


def _parse_org(raw: object, path: Path) -> dict:
    """``[org] use`` / ``contribute``; both default off (C-036)."""
    if not raw:
        return {"use": False, "contribute": False}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [org] must be a table")
    _reject_unknown("org", raw, {"use", "contribute"}, path)
    use, contribute = bool(raw.get("use")), bool(raw.get("contribute"))
    if contribute and not use:
        raise ConfigError(f"{path}: [org] contribute needs use = true")
    return {"use": use, "contribute": contribute}


def _shared_paths(root: Path, value: object) -> list[Path]:
    if not value:
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[Path] = []
    for item in raw:
        path = _as_path(root, item)
        if path is not None:
            out.append(path)
    return out


def _parse_style_presets(raw: object, path: Path) -> dict[str, str]:
    """``[prompt.style_presets]`` locale -> preset name. Absent table is empty."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [prompt.style_presets] must be a table")
    return {
        str(loc): _choice(f"[prompt.style_presets] {loc}", val, tuple(STYLE_PRESETS), path)
        for loc, val in raw.items()
    }


def _require_prompt_family(value: str, path: Path, label: str) -> str:
    from ..pipeline.prompts import PROMPT_FAMILIES

    name = (value or "").strip()
    if name not in PROMPT_FAMILIES:
        raise ConfigError(
            f"{path}: {label} must be one of {', '.join(sorted(PROMPT_FAMILIES))}"
            f" (got {value!r})"
        )
    return name


def _require_locale_prompt_families(raw: dict, path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in raw.items():
        out[str(key)] = _require_prompt_family(
            str(val), path, f"[locales.prompt_family] {key}",
        )
    return out


def _reject_unknown(section: str, values: object, known: set[str], path: Path) -> None:
    if not isinstance(values, dict):
        raise ConfigError(f"{path}: [{section}] must be a table")
    unknown = set(values) - known
    if unknown:
        raise ConfigError(
            f"{path}: unknown [{section}] field(s): {', '.join(sorted(unknown))}"
        )


def _string_list(label: str, raw: object, path: Path, section: str = "locales") -> list[str]:
    """Arrays of strings. A bare string is an error, not a list of its characters (``t_functions = "tr"``)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: [{section}] {label} must be an array of strings")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                f"{path}: [{section}] {label} entry {item!r} must be a non-empty string"
            )
        out.append(item)
    return out


def _bool(label: str, raw: object, default: bool, path: Path, section: str) -> bool:
    """A TOML boolean. ``"false"`` (a string) is an error, not True."""
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ConfigError(f"{path}: [{section}] {label} must be true or false, not {raw!r}")
    return raw


def _string_models(raw: object, path: Path) -> dict[str, str]:
    """``[locales.models]`` values must be strings. The error names the key."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [locales.models] must be a table")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(
                f"{path}: [locales.models] {key!r} must be a non-empty string"
            )
        out[str(key)] = value.strip()
    return out


def _check_model_roster(models: dict[str, str], targets: list[str], path: Path) -> None:
    """Fail when several models have no default. Unknown keys warn, they do not fail."""
    distinct = {value for key, value in models.items() if key != "default"}
    if len(distinct) > 1 and "default" not in models:
        raise ConfigError(
            f"{path}: [locales.models] has more than one model and no default"
        )
    unknown = sorted(key for key in models if key != "default" and key not in targets)
    if unknown:
        warnings.warn(
            f"{path}: [locales.models] not a target or default: {', '.join(unknown)}",
            UserWarning,
            stacklevel=2,
        )


def _parse_locale_styles(raw: object, path: Path) -> dict[str, tuple[str, str]]:
    """``[prompt.styles.<locale>]`` register and notes. Absent table is empty."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [prompt.styles] must be a table")
    out: dict[str, tuple[str, str]] = {}
    for loc, table in raw.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: [prompt.styles.{loc}] must be a table")
        unknown = sorted(set(table) - {"register", "notes"})
        if unknown:
            raise ConfigError(
                f"{path}: [prompt.styles.{loc}] unknown keys: {', '.join(unknown)}"
            )
        reg = table.get("register", "")
        if reg not in ("", "informal", "formal"):
            raise ConfigError(
                f"{path}: [prompt.styles.{loc}] register must be informal or formal"
            )
        notes = table.get("notes", "")
        if not isinstance(notes, str):
            raise ConfigError(f"{path}: [prompt.styles.{loc}] notes must be a string")
        notes = notes.strip()
        if len(notes) > 500:
            raise ConfigError(
                f"{path}: [prompt.styles.{loc}] notes must be at most 500 characters"
            )
        out[str(loc)] = (str(reg) if reg else "", notes)
    return out


def _bounded_text(label: str, value: object, limit: int, path: Path) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: {label} must be a string")
    value = value.strip()
    if len(value) > limit:
        raise ConfigError(f"{path}: {label} must be at most {limit} characters")
    return value


def _is_loopback_url(url: str) -> bool:
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(url if "//" in url else f"//{url}").hostname or "").strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_local_only(cfg: "ProjectConfig", path: Path) -> None:
    """``[privacy] local_only`` (C-023, ADR-69): nothing may leave this machine."""
    from ..catalog.cloud_cost import CLOUD_KINDS

    if cfg.allow_cloud:
        raise ConfigError(
            f"{path}: [privacy] local_only = true contradicts allow_cloud = true; set one"
        )
    endpoints = [("[provider]", cfg.provider.kind, cfg.provider.url)]
    endpoints += [
        (f"[providers.{pid}]", entry.kind, entry.url) for pid, entry in cfg.providers.items()
    ]
    for label, kind, url in endpoints:
        kind = (kind or "").strip().lower()
        if kind in CLOUD_KINDS:
            raise ConfigError(
                f"{path}: {label} uses cloud provider {kind!r}, which [privacy] local_only forbids"
            )
        if kind in ("ollama",) and url and not _is_loopback_url(url):
            raise ConfigError(
                f"{path}: {label} url {url!r} is not on this machine; [privacy] local_only "
                "allows only localhost endpoints"
            )
    if cfg.notify_webhook and not _is_loopback_url(cfg.notify_webhook):
        raise ConfigError(
            f"{path}: [notify] webhook leaves this machine; [privacy] local_only forbids it"
        )


def _parse_exclude(table: object, path: Path) -> tuple[tuple[str, ...], tuple[re.Pattern[str], ...]]:
    """``[exclude]``: ``keys`` globs and ``source_regex`` patterns (ADR-71)."""
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [exclude] must be a table")
    _reject_unknown("exclude", table, {"keys", "source_regex"}, path)
    out: dict[str, list[str]] = {}
    for name in ("keys", "source_regex"):
        raw = table.get(name, [])
        if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
            raise ConfigError(f"{path}: [exclude] {name} must be a list of non-empty strings")
        if len(raw) > 200:
            raise ConfigError(f"{path}: [exclude] {name} has more than 200 entries")
        out[name] = raw
    patterns: list[re.Pattern[str]] = []
    for text in out["source_regex"]:
        try:
            patterns.append(re.compile(text))
        except re.error as exc:
            raise ConfigError(f"{path}: [exclude] source_regex {text!r} is not a valid regex: {exc}") from exc
    return tuple(out["keys"]), tuple(patterns)


LOCKED_CHECKS = frozenset({"V02", "V03", "V27", "V39"})  # placeholder / plural / HTML / escape
_SEVERITY_VALUES = frozenset({"off", "warning", "error"})


def _parse_validate(table: object, path: Path) -> dict[str, str]:
    """``[validate.severity]``: per-check severity override (ADR-72)."""
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [validate] must be a table")
    _reject_unknown("validate", table, {"severity"}, path)
    sev = table.get("severity", {})
    if not isinstance(sev, dict):
        raise ConfigError(f"{path}: [validate.severity] must be a table")
    out: dict[str, str] = {}
    for code, value in sev.items():
        cid = str(code).upper()
        if not re.fullmatch(r"V\d{2}", cid):
            raise ConfigError(f"{path}: [validate.severity] {code!r} is not a check id like V13")
        if cid in LOCKED_CHECKS:
            raise ConfigError(
                f"{path}: [validate.severity] {cid} protects placeholders, plurals, markup or escapes and cannot be changed"
            )
        if value not in _SEVERITY_VALUES:
            raise ConfigError(f"{path}: [validate.severity] {cid} must be off, warning or error")
        out[cid] = value
    return out


def _parse_voice(voice: dict, prompt: dict, path: Path) -> dict[str, str]:
    """``[voice]`` (C-001, ADR-68): description / audience / tone for the prompt.

    ``description`` and ``audience`` are the ADR-60 fields; ``[voice]`` is the
    preferred home, ``[prompt]`` stays valid. Setting one field in both is an error.
    """
    if not isinstance(voice, dict):
        raise ConfigError(f"{path}: [voice] must be a table")
    _reject_unknown("voice", voice, {"description", "audience", "tone"}, path)
    limits = {"description": 2000, "audience": 300}
    out: dict[str, str] = {}
    for name, limit in limits.items():
        if voice.get(name) and prompt.get(name):
            raise ConfigError(
                f"{path}: {name} is set in both [voice] and [prompt]; keep it in [voice]"
            )
        section = "voice" if name in voice else "prompt"
        source = voice if name in voice else prompt
        out[name] = _bounded_text(f"[{section}] {name}", source.get(name, ""), limit, path)
    out["tone"] = _bounded_text("[voice] tone", voice.get("tone", ""), 300, path)
    return out


def _choice(label: str, value: object, allowed: tuple[str, ...], path: Path) -> str:
    if value not in allowed:
        raise ConfigError(f"{path}: {label} must be one of {', '.join(allowed)}")
    return str(value)


def _parse_model_prompts(raw: object, path: Path) -> dict[str, tuple[str, bool]]:
    """``[prompt.models."<model>"]`` ``text`` and ``localize`` (ADR-60)."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [prompt.models] must be a table")
    out: dict[str, tuple[str, bool]] = {}
    for model, table in raw.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: [prompt.models.{model!r}] must be a table")
        _reject_unknown(f"prompt.models.{model}", table, {"text", "localize"}, path)
        text = _bounded_text(f"[prompt.models.{model!r}] text", table.get("text", ""), 1000, path)
        localize = table.get("localize", False)
        if not isinstance(localize, bool):
            raise ConfigError(f"{path}: [prompt.models.{model!r}] localize must be true or false")
        out[str(model)] = (text, localize)
    return out


_DEFAULT_PROVIDER_OPTIONS = {"temperature": 0.1, "top_p": 0.9, "num_gpu": 99}


def _merge_provider_options(*layers: dict | None) -> dict:
    """Merge provider option tables left→right; defaults fill missing keys.

    A TOML snippet like ``options = { top_p = 0.9 }`` must not drop
    ``num_gpu`` / ``temperature`` — those keep full GPU offload and low
    sampling noise for translation.
    """
    out = dict(_DEFAULT_PROVIDER_OPTIONS)
    for layer in layers:
        if isinstance(layer, dict):
            out.update(layer)
    return out


def _provider_config_from_raw(provider_raw: dict) -> ProviderConfig:
    raw = dict(provider_raw or {})
    if "options" in raw:
        raw["options"] = _merge_provider_options(raw.get("options"))
    return ProviderConfig(**raw) if raw else ProviderConfig()


def _parse_providers(raw: dict, provider_raw: dict, path: Path):
    providers_raw = raw.get("providers", {})
    named_providers: dict[str, NamedProvider] = {}
    if providers_raw:
        if not isinstance(providers_raw, dict):
            raise ConfigError(f"{path}: [providers] must be a table")
        _PROVIDER_FIELDS = set(ProviderConfig.__dataclass_fields__) | {"name"}
        for pid, table in providers_raw.items():
            if not isinstance(table, dict):
                raise ConfigError(f"{path}: [providers.{pid}] must be a table")
            _reject_unknown(f"providers.{pid}", table, _PROVIDER_FIELDS, path)
            merged = ProviderConfig()
            for key in ProviderConfig.__dataclass_fields__:
                if key in provider_raw and key != "options":
                    setattr(merged, key, provider_raw[key])
                if key in table and key != "options":
                    setattr(merged, key, table[key])
            merged.options = _merge_provider_options(
                provider_raw.get("options") if isinstance(provider_raw, dict) else None,
                table.get("options"),
            )
            named_providers[str(pid)] = NamedProvider(
                id=str(pid),
                name=str(table.get("name") or pid),
                kind=merged.kind or "ollama",
                url=merged.url or "http://localhost:11434",
                keep_alive=merged.keep_alive,
                options=dict(merged.options or {}),
                timeout_batch_s=merged.timeout_batch_s,
                timeout_single_s=merged.timeout_single_s,
                timeout_shorten_s=merged.timeout_shorten_s,
                model_path=merged.model_path or "",
                api_key_env=merged.api_key_env or "",
            )
    legacy_provider = _provider_config_from_raw(provider_raw)
    if "default" not in named_providers:
        named_providers["default"] = _named_from_provider(legacy_provider)
    synced_provider = named_providers["default"].as_provider_config()

    return named_providers, synced_provider


def _parse_roles(locales: dict, path: Path) -> dict[str, LocaleRole]:
    roles_raw = locales.get("roles", {})
    if roles_raw and not isinstance(roles_raw, dict):
        raise ConfigError(f"{path}: [locales.roles] must be a table")
    parsed_roles: dict[str, LocaleRole] = {}
    for loc, role_table in dict(roles_raw or {}).items():
        if not isinstance(role_table, dict):
            raise ConfigError(f"{path}: [locales.roles.{loc}] must be a table")
        _reject_unknown(
            f"locales.roles.{loc}",
            role_table,
            {"primary", "secondary", "judge", "prefer_secondary"},
            path,
        )
        parsed_roles[str(loc)] = LocaleRole(
            primary=(str(role_table["primary"]) if role_table.get("primary") else None),
            secondary=(
                str(role_table["secondary"]) if role_table.get("secondary") else None
            ),
            judge=(str(role_table["judge"]) if role_table.get("judge") else None),
            prefer_secondary=bool(role_table.get("prefer_secondary", False)),
        )
    return parsed_roles


#: Known keys per top-level section; anything else is a config error (M3: data, not a wall of calls).
_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "project": frozenset({"data_home", "display_name", "name", "source_locale"}),
    "catalog": frozenset({"format", "namespaces", "path", "skip_keys", "skip_namespaces", "source_branch", "standard"}),
    "locales": frozenset({"asap", "fallbacks", "frozen", "length_sensitive", "models", "pivots", "prompt_family", "providers", "roles", "targets"}),
    "prompt": frozenset({"audience", "catalogue_semantic", "context_dir", "description", "domain", "examples_file", "family", "glossary", "glossary_conflict", "glossary_domains", "glossary_shared", "localize", "models", "register", "style_preset", "style_presets", "styles", "tm_dir", "tm_semantic", "tm_shared", "tm_write"}),
    "state": frozenset({"dir", "flags", "history", "scores"}),
    "scan": frozenset({"adapter", "content_globs", "directive_aliases", "exclude", "out_dir", "server_dirs", "src_dirs", "surfaces", "t_functions", "unskip", "unused_allow"}),
    "documents": frozenset({"dir", "model", "state_dir"}),
    "quality": frozenset({"band_approve", "band_flag", "band_retranslate", "bt_batch_size", "bt_cloud_batch_size", "bt_workers", "catalogue_semantic", "defer_scoring", "high_risk_patterns", "improve_limit", "improve_model", "improve_multi_sample", "improve_reject_cooldown_hours", "improve_skip_rejected", "judge_model", "judge_risky", "length_sensitive", "multi_sample", "score_model", "score_provider", "threshold", "thresholds", "tiers", "tm_semantic", "vision_model", "write_floor"}),
    "budget": frozenset({"cloud_batch", "mode", "monthly_usd", "output_expansion", "rates", "thinking_tokens"}),
    "gather": frozenset({"auto_stub"}),
    "translate": frozenset({"approach", "batch_size", "cloud_batch_size", "enabled", "history_compact_every", "max_consecutive_rejects", "min_keys", "short_batch", "soft_retry"}),
}


def _parse_policy_sections(raw: dict, web: dict, path: Path) -> dict:
    """``[tasks]``, ``[delivery]``, ``[ownership]``, ``[review]``, ``[apply]``, ``[source_policy]``, ``[places]``,
    ``[permissions]``, ``[privacy]``, ``[notify]`` (and the ``[web]`` key check) as ProjectConfig keyword arguments."""
    privacy = raw.get("privacy", {})
    tasks_cfg = raw.get("tasks", {})
    _reject_unknown("tasks", tasks_cfg, {"contribute_in_tasks_only"}, path)
    delivery = raw.get("delivery", {})
    _reject_unknown("delivery", delivery, {"require"}, path)
    delivery_require = str(delivery.get("require", "none")).strip().lower()
    if delivery_require not in ("none", "verified", "reviewed"):
        raise ConfigError(f"{path}: [delivery] require must be none, verified or reviewed")
    notify = raw.get("notify", {})
    ownership = raw.get("ownership", {})
    if not isinstance(ownership, dict) or not all(isinstance(v, str) for v in ownership.values()):
        raise ConfigError(f"{path}: [ownership] must be a table of pattern = \"assignee\"")
    review_cfg = raw.get("review", {})
    _reject_unknown("review", review_cfg, {"escalate_after_days", "sample_percent"}, path)
    sample_percent = int(review_cfg.get("sample_percent", 100))
    if not 0 <= sample_percent <= 100:
        raise ConfigError(f"{path}: [review] sample_percent must be between 0 and 100")
    apply_cfg = raw.get("apply", {})
    _reject_unknown("apply", apply_cfg, {"mode"}, path)
    apply_mode = str(apply_cfg.get("mode", "manual")).strip().lower()
    if apply_mode not in ("manual", "request", "auto"):
        raise ConfigError(f"{path}: [apply] mode must be manual, request or auto, got {apply_mode!r}")
    policy = raw.get("source_policy", {})
    _reject_unknown("source_policy", policy, {"source_edits", "decisions_in", "target_branch"}, path)
    source_edits = str(policy.get("source_edits", "patch")).strip().lower()
    if source_edits not in ("never", "patch", "agent-branch"):
        raise ConfigError(f"{path}: [source_policy] source_edits must be never, patch or agent-branch")
    decisions_in = str(policy.get("decisions_in", "state")).strip().lower()
    if decisions_in not in ("state", "code"):
        raise ConfigError(f"{path}: [source_policy] decisions_in must be state or code")
    places, places_default = _parse_places(raw.get("places", {}), path)
    if web:
        _reject_unknown(
            "web", web, {"overlay_edit", "docs_url", "profile", "qa_locales", "runtime_path"}, path,
        )
    if privacy:
        _reject_unknown("privacy", privacy, {"allow_cloud", "local_only"}, path)
    if notify:
        _reject_unknown("notify", notify, {"webhook", "format"}, path)
    permission_matrix = _parse_permissions(raw.get("permissions", {}), path)
    notify_webhook = str(notify.get("webhook", "") or "").strip()
    if notify_webhook:
        from ..ops.notify import validate_webhook_url

        bad = validate_webhook_url(notify_webhook)
        if bad is not None:
            raise ConfigError(f"{path}: [notify] webhook: {bad}")
    notify_format = str(notify.get("format", "json") or "json").strip().lower()
    from ..ops.notify import NOTIFY_FORMATS

    if notify_format not in NOTIFY_FORMATS:
        raise ConfigError(f"{path}: [notify] format must be one of {', '.join(NOTIFY_FORMATS)}")
    return {
        "permission_matrix": permission_matrix,
        "notify_webhook": notify_webhook,
        "notify_format": notify_format,
        "ownership": {str(k): str(v) for k, v in ownership.items()},
        "review_escalate_after_days": max(0, int(review_cfg.get("escalate_after_days", 0))),
        "review_sample_percent": sample_percent,
        "apply_mode": apply_mode,
        "source_edits": source_edits,
        "decisions_in": decisions_in,
        "places": places,
        "places_default": places_default,
        "target_branch": str(policy.get("target_branch", "l10n/auto")).strip() or "l10n/auto",
        "allow_cloud": bool(privacy.get("allow_cloud", False)),
        "local_only": bool(privacy.get("local_only", False)),
        "tasks_only": bool(tasks_cfg.get("contribute_in_tasks_only", False)),
        "delivery_require": delivery_require,
    }


def _parse_places(places_raw: dict, path: Path) -> tuple[dict[str, str], str]:
    places: dict[str, str] = {}
    places_default = "auto"
    for pk, pv in places_raw.items():
        if pk == "default":
            places_default = str(pv).strip().lower()
            continue
        if not isinstance(pv, dict):
            raise ConfigError(f"{path}: [places.{pk}] must be a table with policy = ...")
        _reject_unknown(f"places.{pk}", pv, {"policy"}, path)
        places[str(pk)] = str(pv.get("policy", "")).strip().lower()
    for pol in [places_default, *places.values()]:
        if pol not in PLACE_POLICIES:
            raise ConfigError(f"{path}: [places] policy must be one of {', '.join(PLACE_POLICIES)}, got {pol!r}")
    return places, places_default


def _parse_permissions(permissions_raw: object, path: Path) -> dict[str, list[bool]]:
    permission_matrix: dict[str, list[bool]] = {}
    if permissions_raw:
        if not isinstance(permissions_raw, dict):
            raise ConfigError(f"{path}: [permissions] must be a table")
        for op_name, flags in permissions_raw.items():
            if not isinstance(flags, list) or len(flags) != 4:
                raise ConfigError(
                    f"{path}: [permissions].{op_name} must be an array of 4 booleans"
                )
            permission_matrix[str(op_name)] = [bool(x) for x in flags]
    return permission_matrix


def _high_risk_patterns(quality: dict, path: Path) -> list[str] | None:
    high_risk_raw = quality.get("high_risk_patterns")
    if high_risk_raw is None:
        return None
    if not isinstance(high_risk_raw, list):
        raise ConfigError(f"{path}: [quality] high_risk_patterns must be an array")
    return [str(p) for p in high_risk_raw]


def _glossary_domains(prompt: dict, path: Path) -> dict[str, list[str]]:
    domains_raw = prompt.get("glossary_domains", {})
    if domains_raw and not isinstance(domains_raw, dict):
        raise ConfigError(f"{path}: [prompt] glossary_domains must be a table")
    glossary_domains: dict[str, list[str]] = {}
    for ns, val in dict(domains_raw or {}).items():
        if isinstance(val, str):
            glossary_domains[str(ns)] = [val]
        elif isinstance(val, list):
            glossary_domains[str(ns)] = [str(v) for v in val if str(v).strip()]
        else:
            raise ConfigError(
                f"{path}: [prompt.glossary_domains] {ns!r} must be a string or array"
            )
    return glossary_domains


def _scan_kwargs(scan: dict, data_base: Path, engine_scan_default: str | None, path: Path) -> dict:
    """``[scan]`` as ProjectConfig keyword arguments."""
    return {
        "scan_adapter": scan.get("adapter"),
        "scan_src_dirs": _string_list("src_dirs", scan.get("src_dirs"), path, "scan"),
        "scan_server_dirs": _string_list("server_dirs", scan.get("server_dirs"), path, "scan"),
        "scan_exclude": _string_list("exclude", scan.get("exclude"), path, "scan"),
        "scan_unskip": _string_list("unskip", scan.get("unskip"), path, "scan"),
        "scan_t_functions": _string_list("t_functions", scan.get("t_functions"), path, "scan"),
        "scan_content_globs": _string_list("content_globs", scan.get("content_globs"), path, "scan"),
        "scan_directive_aliases": _bool("directive_aliases", scan.get("directive_aliases"), True, path, "scan"),
        "scan_unused_allow": _string_list("unused_allow", scan.get("unused_allow"), path, "scan"),
        "scan_surfaces": _scan_surfaces(scan.get("surfaces"), path),
        "scan_out_dir": _sidecar_path(data_base, scan.get("out_dir"), engine_scan_default),
    }


_SURFACE_MODES = ("fix", "report", "ignore")


def _scan_surfaces(raw: object, path: Path) -> dict[str, dict]:
    """``[scan.surfaces.<name>]`` tables: ``paths`` (globs) and ``mode``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [scan.surfaces] must be a table of tables")
    out: dict[str, dict] = {}
    for name, row in raw.items():
        if not isinstance(row, dict):
            raise ConfigError(f"{path}: [scan.surfaces.{name}] must be a table")
        _reject_unknown(f"scan.surfaces.{name}", row, {"paths", "mode"}, path)
        mode = str(row.get("mode", "fix"))
        if mode not in _SURFACE_MODES:
            raise ConfigError(
                f"{path}: [scan.surfaces.{name}] mode must be one of {', '.join(_SURFACE_MODES)}, got {mode!r}")
        paths = _string_list("paths", row.get("paths"), path, f"scan.surfaces.{name}")
        if not paths:
            raise ConfigError(f"{path}: [scan.surfaces.{name}] needs paths = [...]")
        out[str(name)] = {"paths": paths, "mode": mode}
    return out


def _quality_translate_kwargs(quality: dict, translate: dict, path: Path) -> dict:
    """``[quality]`` and ``[translate]`` as ProjectConfig keyword arguments."""
    return {
        "quality_threshold": float(quality.get("threshold", 0.55)),
        "quality_thresholds": _locale_thresholds(quality.get("thresholds"), path),
        "quality_tiers": _content_tiers(quality.get("tiers"), path),
        "band_approve": float(quality.get("band_approve", 0.95)),
        "band_flag": float(quality.get("band_flag", 0.90)),
        "band_retranslate": float(quality.get("band_retranslate", 0.80)),
        "write_floor": (float(quality["write_floor"]) if quality.get("write_floor") is not None else None),
        "judge_risky": bool(quality.get("judge_risky", True)),
        "improve_model": quality.get("improve_model"),
        "score_model": quality.get("score_model"),
        "score_provider": (str(quality["score_provider"]).strip() or None) if quality.get("score_provider") else None,
        "judge_model": quality.get("judge_model"),
        "defer_scoring": (
            bool(quality["defer_scoring"]) if quality.get("defer_scoring") is not None else None
        ),
        "bt_batch_size": max(1, int(quality.get("bt_batch_size", 5))),
        "bt_cloud_batch_size": max(0, int(quality.get("bt_cloud_batch_size", 0))),
        "bt_workers": max(1, int(quality.get("bt_workers", 4))),
        "vision_model": quality.get("vision_model"),
        "improve_limit": int(quality.get("improve_limit", 50)),
        "improve_skip_rejected": bool(quality.get("improve_skip_rejected", True)),
        "improve_reject_cooldown_hours": max(0, int(quality.get("improve_reject_cooldown_hours", 168))),
        "translate_batch_size": int(translate.get("batch_size", 10)),
        "translate_cloud_batch_size": max(1, int(translate.get("cloud_batch_size", 50))),
        "translate_short_batch": bool(translate.get("short_batch", False)),
        "history_compact_every": max(1, int(translate.get("history_compact_every", 10))),
        "translate_enabled": bool(translate.get("enabled", True)),
        "translate_min_keys": max(0, int(translate.get("min_keys", 50))),
        "translate_soft_retry": bool(translate.get("soft_retry", True)),
        "translate_approach": _approach(translate, path),
        "translate_max_consecutive_rejects": max(0, int(translate.get("max_consecutive_rejects", 10))),
        "multi_sample": max(1, int(quality.get("multi_sample", 1))),
        "improve_multi_sample": (
            max(1, int(quality["improve_multi_sample"])) if quality.get("improve_multi_sample") is not None else None
        ),
    }


def load_config(path: str | Path, *, engine_override: str | None = None) -> ProjectConfig:
    """Parse a ``.llm-localize.toml`` into a :class:`ProjectConfig`.

    ``engine_override`` (or ``LLM_LOCALIZE_ENGINE``) applies an engine for one run on top of the project's keys.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"no config file at {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    raw, engine_id, overridden = _apply_engine(raw, path, engine_override)
    root = path.parent
    project = raw.get("project", {})
    org = _parse_org(raw.get("org", {}), path)
    git_host = _parse_git_host(raw.get("git_host", {}), path)
    if not project.get("name"):
        raise ConfigError(f"{path}: [project] name is required")

    catalog = raw.get("catalog", {})
    locales = raw.get("locales", {})
    provider_raw = raw.get("provider", {})
    prompt = raw.get("prompt", {})
    voice = _parse_voice(raw.get("voice", {}), prompt, path)
    severity_overrides = _parse_validate(raw.get("validate", {}), path)
    exclude_keys, exclude_source = _parse_exclude(raw.get("exclude", {}), path)
    state = raw.get("state", {})
    scan = raw.get("scan", {})
    documents = raw.get("documents", {})
    parsed_collections = _parse_collections(raw, path)
    quality = raw.get("quality", {})
    budget = raw.get("budget", {})
    gather = raw.get("gather", {})

    translate = raw.get("translate", {})
    visual = raw.get("visual", {})

    unknown_sections = set(raw) - {
        "project", "catalog", "locales", "provider", "providers", "prompt", "state",
        "scan", "documents", "collections", "quality", "budget", "gather", "translate",
        "visual", "web", "privacy", "delivery", "permissions", "notify", "workflows",
        "ownership", "review", "apply", "source_policy", "places", "bridge", "voice", "exclude", "validate", "tasks", "org", "git_host", "qa", "engine",
    }
    if unknown_sections:
        raise ConfigError(
            f"{path}: unknown top-level section(s): {', '.join(sorted(unknown_sections))}"
        )

    for section, known in _KNOWN_KEYS.items():
        _reject_unknown(section, raw.get(section, {}), set(known), path)
    rate_rows, budget_mode, output_expansion, thinking_tokens = _parse_budget(budget, path)
    if visual:
        _reject_unknown("visual", visual, {"findings_path"}, path)
    web = raw.get("web", {})
    policy_kwargs = _parse_policy_sections(raw, web, path)
    workflows = _parse_workflows(raw, path)

    _reject_unknown("provider", provider_raw, set(ProviderConfig.__dataclass_fields__), path)

    named_providers, synced_provider = _parse_providers(raw, provider_raw, path)

    parsed_roles = _parse_roles(locales, path)

    high_risk_patterns = _high_risk_patterns(quality, path)
    glossary_domains = _glossary_domains(prompt, path)

    targets = _string_list("targets", locales.get("targets", []), path)
    frozen = _string_list("frozen", locales.get("frozen", []), path)
    asap = _string_list("asap", locales.get("asap", []), path)
    models = _string_models(locales.get("models", {}), path)
    _check_model_roster(models, targets, path)

    data_home = _choice(
        "[project] data_home",
        project.get("data_home", "engine"),
        ("engine", "project"),
        path,
    )
    project_name = str(project["name"])
    if data_home == "project":
        data_base = root
    else:
        from .registry import registry_home

        data_base = registry_home() / "data" / project_name

    # Engine sidecars (ADR-112). Product paths below still use ``root``.
    engine_scan_default = ".usage" if data_home == "engine" else None
    engine_doc_state = "documents-state" if data_home == "engine" else None

    cfg = ProjectConfig(
        root=root,
        name=project_name,
        source_locale=project.get("source_locale", "en"),
        data_home=data_home,
        catalog_format=catalog.get("format", "json-nested"),
        catalog_standard=str(catalog.get("standard") or "icu"),
        catalog_path=catalog.get("path", "messages/{locale}/{namespace}.json"),
        namespaces=catalog.get("namespaces", "*"),
        skip_keys=set(catalog.get("skip_keys", [])),
        exclude_keys=exclude_keys,
        severity_overrides=severity_overrides,
        exclude_source=exclude_source,
        skip_namespaces=set(catalog.get("skip_namespaces", [])),
        source_branch=str(catalog.get("source_branch", "main")),
        targets=targets,
        frozen=frozen,
        asap=asap,
        pivots=dict(locales.get("pivots", {})),
        fallbacks={
            str(loc): str(ref)
            for loc, ref in dict(locales.get("fallbacks") or {}).items()
        },
        models=models,
        roles=parsed_roles,
        provider=synced_provider,
        providers=named_providers,
        domain=prompt.get("domain", "a software application"),
        glossary_path=_as_path(root, prompt.get("glossary")),
        glossary_shared=_shared_paths(root, prompt.get("glossary_shared")) + _org_glossary(org),
        glossary_domains=glossary_domains,
        context_dir=_as_path(root, prompt.get("context_dir")),
        examples_file=_as_path(root, prompt.get("examples_file")),
        tm_dir=_sidecar_path(data_base, prompt.get("tm_dir"), ".llm-tm"),
        tm_shared=(_shared_paths(root, prompt.get("tm_shared")) or [None])[0],
        tm_shared_more=_shared_paths(root, prompt.get("tm_shared"))[1:] + _org_tm(org),
        tm_write=_as_path(root, prompt.get("tm_write")) or _org_write(org),
        org_use=org["use"],
        org_contribute=org["contribute"],
        git_host=git_host,
        register=str(prompt.get("register", "informal")),
        register_set="register" in prompt,
        prompt_family=_require_prompt_family(
            str(prompt.get("family", "chat") or "chat"), path, "[prompt] family",
        ),
        locale_prompt_families=_require_locale_prompt_families(
            dict(locales.get("prompt_family", {})), path,
        ),
        locale_styles=_parse_locale_styles(prompt.get("styles"), path),
        display_name=_bounded_text("[project] display_name", project.get("display_name", ""), 120, path),
        description=voice["description"],
        audience=voice["audience"],
        tone=voice["tone"],
        style_preset=(
            _choice("[prompt] style_preset", prompt["style_preset"], tuple(STYLE_PRESETS), path)
            if prompt.get("style_preset") else ""
        ),
        locale_style_presets=_parse_style_presets(prompt.get("style_presets"), path),
        prompt_localize=_choice("[prompt] localize", prompt.get("localize", "source"), ("source", "target", "per-model"), path),
        model_prompts=_parse_model_prompts(prompt.get("models"), path),
        glossary_conflict=_choice("[prompt] glossary_conflict", prompt.get("glossary_conflict", "own"), ("own", "shared", "flag"), path),
        **_parse_bridge(raw.get("bridge"), path),
        state_dir=_sidecar_path(data_base, state.get("dir"), ".llm-state"),
        flags_path=_sidecar_path(
            data_base,
            state.get("flags"),
            ".llm-flags.jsonl" if data_home == "engine" else None,
        ),
        history_dir=_sidecar_path(data_base, state.get("history"), ".llm-history"),
        scores_dir=_sidecar_path(data_base, state.get("scores"), ".llm-scores"),
        **_scan_kwargs(scan, data_base, engine_scan_default, path),
        documents_dir=_as_path(root, documents.get("dir")),
        documents_state_dir=_sidecar_path(data_base, documents.get("state_dir"), engine_doc_state),
        documents_model=documents.get("model"),
        collections=parsed_collections,
        **_quality_translate_kwargs(quality, translate, path),
        high_risk_patterns=high_risk_patterns,
        tm_semantic=bool(prompt.get("tm_semantic", quality.get("tm_semantic", False))),
        catalogue_semantic=bool(
            prompt.get("catalogue_semantic", quality.get("catalogue_semantic", False)),
        ),
        visual_findings_path=_as_path(root, visual.get("findings_path")),
        length_sensitive=list(
            locales.get("length_sensitive", quality.get("length_sensitive", ["de"]))
        ),
        budget_monthly_usd=float(budget.get("monthly_usd", 0.0)),
        budget_mode=budget_mode,
        budget_output_expansion=output_expansion,
        budget_thinking_tokens=thinking_tokens,
        budget_rates={str(k): dict(v) for k, v in dict(rate_rows).items()},
        budget_cloud_batch=bool(budget.get("cloud_batch", True)),
        gather_auto_stub=bool(gather.get("auto_stub", False)),
        overlay_edit=bool(web.get("overlay_edit", False)),
        qa_locales=_qa_locales(web, path),
        docs_url=str(web.get("docs_url", "") or "").rstrip("/"),
        web_profile=bool(web.get("profile", False)),
        web_runtime_path=str(web.get("runtime_path", "") or "").strip(),
        qa=parse_qa(raw.get("qa"), path, project=project_name,
                    locales=[*targets, *frozen]),
        **policy_kwargs,
        workflows=workflows,
        locale_providers={
            str(k): str(v)
            for k, v in dict(locales.get("providers", {})).items()
        },
        config_path=path,
    )
    cfg.engine_id = engine_id
    cfg.engine_override = engine_id if overridden else None
    _validate_config(cfg, path)
    return cfg


def layer_over(raw: dict, engine) -> dict:
    """``raw`` with the engine's settings on top (one-run override): engine keys replace the project's."""
    from copy import deepcopy

    merged = deepcopy(raw)
    for path_, key, value in _engine_rows(engine.config):
        table = merged
        for part in path_:
            table = table.setdefault(part, {})
        table[key] = deepcopy(value)
    merged.pop("engine", None)
    return merged


def _engine_rows(table: dict, path_: tuple = ()):
    for key, value in table.items():
        if isinstance(value, dict):
            yield from _engine_rows(value, (*path_, key))
        else:
            yield path_, key, value


def _apply_engine(raw: dict, path: Path, engine_override: str | None = None) -> tuple[dict, str | None, bool]:
    """``[engine] id`` layers that engine's settings under the project's own keys (ADR-156)."""
    import os

    override = (engine_override or os.environ.get("LLM_LOCALIZE_ENGINE") or "").strip()
    if override:
        # --engine for one run: the engine wins over the project keys it sets (per-locale overrides stay).
        from ..engines import EngineError, get_engine, layer

        try:
            engine = get_engine(override)
        except EngineError as exc:
            raise ConfigError(f"--engine: {exc}") from exc
        return layer_over(raw, engine), override, True
    section = raw.get("engine")
    if section is None:
        return raw, None, False
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: [engine] must be a table")
    _reject_unknown("engine", section, {"id"}, path)
    engine_id = str(section.get("id") or "").strip()
    if not engine_id:
        raise ConfigError(f"{path}: [engine] id is required")
    from ..engines import EngineError, get_engine, layer

    try:
        engine = get_engine(engine_id)
    except EngineError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return layer(raw, engine), engine_id, False


def _validate_config(cfg: ProjectConfig, path: Path) -> None:
    """Cross-section rules checked once the whole config is parsed (formats, locale sets, pivots, fallbacks)."""
    if cfg.local_only:
        _check_local_only(cfg, path)
    from ..providers.preflight import model_fit_errors

    misfits = model_fit_errors(cfg)
    if misfits:
        raise ConfigError(f"{path}: model does not fit its provider:\n  " + "\n  ".join(misfits))

    # Validate the format name here rather than at first use, so a typo fails
    # immediately with the list of alternatives instead of deep inside a run.
    from ..catalog import KNOWN_FORMATS

    if cfg.catalog_format not in KNOWN_FORMATS:
        raise ConfigError(
            f"{path}: unknown [catalog] format {cfg.catalog_format!r}. "
            f"Known formats: {', '.join(KNOWN_FORMATS)}"
        )
    from ..catalog import resolve_format
    from ..core.languages import standard_allowed, standard_ids

    resolved_format = resolve_format(cfg.catalog_format)
    if not standard_allowed(resolved_format, cfg.catalog_standard):
        raise ConfigError(
            f"{path}: [catalog] standard {cfg.catalog_standard!r} is not allowed "
            f"for format {cfg.catalog_format!r}. "
            f"Known standards: {', '.join(standard_ids())}"
        )

    if "{locale}" not in cfg.catalog_path:
        raise ConfigError(f"{path}: [catalog] path must contain a {{locale}} placeholder")
    if cfg.source_locale in cfg.targets:
        raise ConfigError(
            f"{path}: source locale {cfg.source_locale!r} must not also be a target"
        )
    unknown_frozen = [loc for loc in cfg.frozen if loc not in cfg.targets]
    if unknown_frozen:
        raise ConfigError(
            f"{path}: [locales] frozen must be a subset of targets; "
            f"unknown: {', '.join(unknown_frozen)}"
        )
    unknown_asap = [loc for loc in cfg.asap if loc not in cfg.targets]
    if unknown_asap:
        raise ConfigError(
            f"{path}: [locales] asap must be a subset of targets; "
            f"unknown: {', '.join(unknown_asap)}"
        )
    both = sorted(set(cfg.asap) & set(cfg.frozen))
    if both:
        raise ConfigError(
            f"{path}: [locales] asap and frozen are mutually exclusive; "
            f"overlap: {', '.join(both)}"
        )
    if cfg.frozen and not cfg.active_targets():
        raise ConfigError(
            f"{path}: [locales] frozen covers every target; leave at least one active"
        )
    for variant, reference in cfg.pivots.items():
        if reference not in cfg.targets and reference != cfg.source_locale:
            raise ConfigError(
                f"{path}: pivot {variant!r} references {reference!r}, "
                "which is neither a target locale nor the source locale"
            )
    if cfg.bridge_mode != "none":
        if cfg.bridge_locale != cfg.source_locale and cfg.bridge_locale not in cfg.targets:
            raise ConfigError(
                f"{path}: [bridge] locale {cfg.bridge_locale!r} must be a target "
                "locale (or the source locale)"
            )
        if not cfg.bridge_store and cfg.bridge_locale != cfg.source_locale:
            raise ConfigError(
                f"{path}: [bridge] store = false is only valid when the bridge "
                "locale is the source locale; a target locale is always stored"
            )
        if cfg.bridge_locale in cfg.pivots:
            raise ConfigError(
                f"{path}: bridge locale {cfg.bridge_locale!r} cannot itself have a pivot"
            )
    for variant, reference in cfg.fallbacks.items():
        if variant not in cfg.targets:
            raise ConfigError(
                f"{path}: fallback {variant!r} is not a target locale"
            )
        if reference == variant:
            raise ConfigError(
                f"{path}: fallback {variant!r} cannot point at itself"
            )
        if reference not in cfg.targets and reference != cfg.source_locale:
            raise ConfigError(
                f"{path}: fallback {variant!r} references {reference!r}, "
                "which is neither a target locale nor the source locale"
            )
    for start in cfg.fallbacks:
        walked: set[str] = set()
        current = start
        while current in cfg.fallbacks:
            if current in walked:
                raise ConfigError(
                    f"{path}: [locales.fallbacks] cycle includes {start!r}"
                )
            walked.add(current)
            current = cfg.fallbacks[current]
    unknown_roles = [loc for loc in cfg.roles if loc not in cfg.targets]
    if unknown_roles:
        raise ConfigError(
            f"{path}: [locales.roles] keys must be target locales; "
            f"unknown: {', '.join(sorted(unknown_roles))}"
        )
    unknown_thresholds = [loc for loc in cfg.quality_thresholds if loc not in cfg.targets]
    if unknown_thresholds:
        raise ConfigError(
            f"{path}: [quality.thresholds] keys must be target locales; "
            f"unknown: {', '.join(sorted(unknown_thresholds))}"
        )
    if cfg.glossary_path is not None and cfg.glossary_path.exists():
        from .context import load_glossary

        try:
            load_glossary(cfg.glossary_path)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"{path}: glossary {cfg.glossary_path}: {exc}") from exc


def _locale_thresholds(raw, path) -> dict[str, float]:
    """Parse ``[quality.thresholds]``: locale -> a cut between 0 and 1."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [quality.thresholds] must be a table of locale = number")
    out: dict[str, float] = {}
    for locale, value in raw.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ConfigError(
                f"{path}: [quality.thresholds] {locale} must be a number between 0 and 1"
            ) from None
        if not 0.0 <= number <= 1.0:
            raise ConfigError(
                f"{path}: [quality.thresholds] {locale} = {value} is outside 0..1"
            )
        out[str(locale)] = number
    return out


TIERS = ("human", "review", "auto")


def _content_tiers(raw, path) -> dict[str, str]:
    """Parse ``[quality.tiers]``: namespace / key glob -> a tier."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [quality.tiers] must be a table of pattern = tier")
    out: dict[str, str] = {}
    for pattern, tier in raw.items():
        if tier not in TIERS:
            raise ConfigError(
                f"{path}: [quality.tiers] {pattern!r} = {tier!r} must be one of {', '.join(TIERS)}"
            )
        out[str(pattern)] = tier
    return out

