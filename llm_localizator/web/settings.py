"""Round-trip ``.llm-localize.toml`` without rebuilding it from the dataclass."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tomlkit

from ..catalog import canonical_formats
from ..ops.permissions import DEFAULT_MATRIX, OPERATIONS, ROLES
from ..projects.config import NamedProvider, ProjectConfig
from .config_write import write_config_atomically

BIND_HOST = "127.0.0.1"

_OP_CATEGORIES = {
    "validate": "Analysis",
    "status": "Analysis",
    "estimate-cost": "Analysis",
    "scan": "Analysis",
    "discover": "Analysis",
    "agent-backlog": "Analysis",
    "adopt": "Analysis",
    "review-risk": "Analysis",
    "glossary-learn": "Analysis",
    "cycle": "Delivery",
    "normalize": "Data",
    "report": "Analysis",
    "sync": "Analysis",
    "translate": "LLM",
    "improve": "LLM",
    "review": "LLM",
    "rescore": "LLM",
    "bakeoff": "LLM",
    "export": "Data",
    "import": "Data",
    "migrate-state": "Data",
    "push-strings": "Delivery",
    "workflow": "Delivery",
    "term-report": "Delivery",
    "release-freeze": "Delivery",
    "release-diff": "Delivery",
    "doctor": "Maintenance",
    "guide": "Maintenance",
}


def _endpoint_host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path
    return host.rstrip("/")


def _pipeline_view(cfg: ProjectConfig) -> dict[str, Any]:
    """Effective provider and model per pipeline role, plus the user-owned cloud settings (read-only, ADR-156)."""
    from ..pipeline.scoring import judge_model_for, score_model_for, score_provider_kind

    project_kind = cfg.provider.kind or "ollama"
    active = cfg.active_targets()
    first = active[0] if active else ""
    roles = [
        {"role": "translate", "provider": cfg.provider_kind_for(first) if first else project_kind,
         "model": cfg.model_for(first)},
        {"role": "score", "provider": score_provider_kind(cfg) or project_kind, "model": score_model_for(cfg)},
        {"role": "improve", "provider": project_kind, "model": cfg.improve_model or cfg.model_for("")},
        {"role": "judge", "provider": project_kind, "model": judge_model_for(cfg, first) or ""},
    ]
    overrides = [
        {"locale": loc, "provider": cfg.provider_kind_for(loc), "model": cfg.model_for(loc)}
        for loc in cfg.targets if cfg.model_for(loc) != cfg.model_for(first) or cfg.provider_kind_for(loc) != roles[0]["provider"]
    ]
    return {
        "engine": cfg.engine_id, "roles": roles, "localeOverrides": overrides,
        "threshold": float(cfg.quality_threshold),
        "allowCloud": bool(cfg.allow_cloud), "localOnly": bool(getattr(cfg, "local_only", False)),
        "budgetUsd": float(getattr(cfg, "budget_monthly_usd", 0) or 0),
        "budgetMode": getattr(cfg, "budget_mode", "on_request") or "on_request",
    }


def _role_for_locale(cfg: ProjectConfig, locale: str) -> str:
    role = cfg.roles.get(locale)
    has_primary = bool(role and role.primary) or bool(cfg.models.get(locale))
    has_judge = bool(role and role.judge)
    if has_primary and has_judge:
        return "both"
    if has_judge and not has_primary:
        return "judge"
    return "translator"


def _assignment_model(cfg: ProjectConfig, locale: str) -> str:
    role = cfg.roles.get(locale)
    if role and role.primary:
        return role.primary
    if cfg.models.get(locale):
        return cfg.models[locale]
    if cfg.models.get("default"):
        return cfg.models["default"]
    return cfg.model_for(locale)


def settings_view(
    cfg: ProjectConfig,
    *,
    port: int,
    coverage: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Settings payload for the Admin System settings page. Token is not included."""
    providers_list: list[dict[str, Any]] = []
    registry = cfg.providers or {}
    if not registry:
        registry = {
            "default": NamedProvider(
                id="default",
                name="Default",
                kind=cfg.provider.kind or "ollama",
                url=cfg.provider.url,
                model_path=cfg.provider.model_path or "",
            )
        }
    for pid, entry in sorted(registry.items(), key=lambda item: (item[0] != "default", item[0])):
        providers_list.append({
            "id": entry.id,
            "name": entry.display_name(),
            "kind": entry.kind or "ollama",
            "endpoint": _endpoint_host(entry.url),
            "url": entry.url,
            "modelPath": entry.model_path or "",
            "models": [],
            "status": "unknown",
        })

    locale_assignments = []
    for loc in cfg.targets:
        entry = cfg.provider_entry_for(loc)
        locale_assignments.append({
            "locale": loc,
            "providerId": entry.id,
            "model": _assignment_model(cfg, loc),
            "role": _role_for_locale(cfg, loc),
        })

    # Backward-compatible kind map for older clients / analysis pages.
    kind_map = {
        "default": cfg.provider.kind or "ollama",
        **{loc: cfg.provider_kind_for(loc) for loc in cfg.targets},
    }

    return {
        "ok": True,
        "name": cfg.name,
        "sourceLocale": cfg.source_locale,
        "targets": list(cfg.targets),
        "frozen": list(cfg.frozen),
        "asap": list(getattr(cfg, "asap", []) or []),
        "fallbacks": dict(cfg.fallbacks),
        "providers": kind_map,
        "providersDetailed": providers_list,
        "localeAssignments": locale_assignments,
        "quality": {
            "threshold": float(cfg.quality_threshold),
            "judgeModel": cfg.judge_model,
        },
        "pipeline": _pipeline_view(cfg),
        "coverage": dict(coverage or {}),
        "project": {
            "name": cfg.name,
            "sourceLocale": cfg.source_locale,
            "catalogFormat": cfg.catalog_format,
            "catalogPath": cfg.catalog_path,
            "skipKeys": sorted(cfg.skip_keys),
        },
        "catalogFormats": canonical_formats(),
        "web": {
            "bind": BIND_HOST,
            "port": port,
            "overlayEdit": bool(cfg.overlay_edit),
        },
        "overlayEdit": bool(cfg.overlay_edit),
        "bind": BIND_HOST,
        "port": port,
        "paths": {
            "root": str(cfg.root),
            "config": str(cfg.config_path or ""),
            "catalog": cfg.catalog_path,
            "dataHome": cfg.data_home,
            "dataRoot": str(cfg.data_root()),
            "state": str(cfg.state_root()),
        },
        "permissionMeta": {
            "operations": list(OPERATIONS),
            "roles": list(ROLES),
            "categories": {op: _OP_CATEGORIES.get(op, "Other") for op in OPERATIONS},
            "defaults": {op: list(DEFAULT_MATRIX[op]) for op in OPERATIONS},
        },
    }


def _locales_table(doc: Any) -> Any:
    locales = doc.get("locales")
    if not isinstance(locales, dict):
        return None
    return locales


def _string_array(values: list) -> Any:
    arr = tomlkit.array()
    for item in values:
        arr.append(str(item))
    return arr


def _apply_locales_arrays(
    doc: Any,
    locales: Any,
    frozen: list | None,
    asap: list | None,
    fallbacks: dict | None,
) -> str | None:
    if frozen is not None:
        locales["frozen"] = _string_array(list(frozen))
    if asap is not None:
        locales["asap"] = _string_array(list(asap))
    if fallbacks is not None:
        if not isinstance(fallbacks, dict):
            return "fallbacks must be an object"
        table = tomlkit.table()
        for loc, ref in fallbacks.items():
            target = str(ref or "").strip()
            if target:
                table[str(loc)] = target
        locales["fallbacks"] = table
    return None


def _apply_overlay_edit(doc: Any, overlay_edit: bool) -> None:
    web = doc.get("web")
    if not isinstance(web, dict):
        web = tomlkit.table()
        doc["web"] = web
    web["overlay_edit"] = bool(overlay_edit)


def _apply_quality(
    doc: Any,
    quality: dict,
    cfg: Any,
    allow_model_writes: bool,
) -> str | None:
    if not isinstance(quality, dict):
        return "quality must be an object"
    qtable = doc.get("quality")
    if not isinstance(qtable, dict):
        qtable = tomlkit.table()
        doc["quality"] = qtable
    if "threshold" in quality:
        try:
            qtable["threshold"] = float(quality["threshold"])
        except (TypeError, ValueError):
            return "quality.threshold must be a number"
    if "judgeModel" in quality or "judge_model" in quality:
        if not allow_model_writes and not _bakeoff_allows_model_write(cfg):
            return (
                "Changing judge_model requires a bakeoff Winner (ADR-12). "
                "Run Model evaluation first, or pass allow_model_writes after confirm."
            )
        judge = quality.get("judgeModel", quality.get("judge_model"))
        if judge is None or str(judge).strip() == "":
            if "judge_model" in qtable:
                del qtable["judge_model"]
        else:
            qtable["judge_model"] = str(judge).strip()
    return None


def _apply_providers(doc: Any, providers: list) -> str | None:
    if not isinstance(providers, list):
        return "providers must be an array"
    if not providers:
        return "at least one provider is required"
    ptable = tomlkit.table()
    default_kind = None
    default_url = None
    default_model_path = None
    for row in providers:
        if not isinstance(row, dict):
            return "each provider must be an object"
        pid = str(row.get("id") or "").strip()
        if not pid:
            return "provider id is required"
        kind = str(row.get("kind") or "ollama").strip().lower()
        url = str(row.get("url") or "").strip()
        if not url and kind == "ollama":
            url = "http://127.0.0.1:11434"
        entry = tomlkit.table()
        entry["name"] = str(row.get("name") or pid)
        entry["kind"] = kind
        if url:
            entry["url"] = url
        model_path = str(row.get("modelPath") or row.get("model_path") or "").strip()
        if model_path:
            entry["model_path"] = model_path
        ptable[pid] = entry
        if pid == "default":
            default_kind = kind
            default_url = url
            default_model_path = model_path
    doc["providers"] = ptable
    # Keep legacy [provider] in sync with default.
    prov = doc.get("provider")
    if not isinstance(prov, dict):
        prov = tomlkit.table()
        doc["provider"] = prov
    if default_kind:
        prov["kind"] = default_kind
    if default_url:
        prov["url"] = default_url
    if default_model_path is not None:
        if default_model_path:
            prov["model_path"] = default_model_path
        elif "model_path" in prov:
            del prov["model_path"]
    return None


def _apply_locale_assignments(
    doc: Any,
    locales: Any,
    locale_assignments: list,
    cfg: Any,
    allow_model_writes: bool,
) -> str | None:
    if not isinstance(locale_assignments, list):
        return "locale_assignments must be an array"
    wants_model = False
    prov_map = tomlkit.table()
    models_table = locales.get("models")
    if not isinstance(models_table, dict):
        models_table = tomlkit.table()
        locales["models"] = models_table
    roles_table = locales.get("roles")
    if not isinstance(roles_table, dict):
        roles_table = tomlkit.table()
        locales["roles"] = roles_table
    for row in locale_assignments:
        if not isinstance(row, dict):
            return "each locale assignment must be an object"
        loc = str(row.get("locale") or "").strip()
        if not loc:
            continue
        provider_id = str(row.get("providerId") or row.get("provider_id") or "").strip()
        if provider_id:
            prov_map[loc] = provider_id
        model = row.get("model")
        role = str(row.get("role") or "translator").strip().lower()
        if model is not None and str(model).strip():
            model_s = str(model).strip()
            # Only a real change needs ADR-12 evidence: re-saving the table as it stands is not a model swap.
            if loc == "default":
                unchanged = model_s == str((getattr(cfg, "models", None) or {}).get("default") or "")
            else:
                unchanged = model_s == _assignment_model(cfg, loc) and role == _role_for_locale(cfg, loc)
            if not unchanged:
                wants_model = True
            if role != "judge":
                # A judge-only row must not pin the translator too: _role_for_locale reads models[loc] as a primary,
                # so the row came back as "both" after a save.
                models_table[loc] = model_s
            if loc == "default":
                # The table's synthetic default row maps to [locales.models] default only, never roles.default.
                continue
            role_row = roles_table.get(loc)
            if not isinstance(role_row, dict):
                role_row = tomlkit.table()
                roles_table[loc] = role_row
            if role == "judge":
                role_row["judge"] = model_s
                if "primary" in role_row:
                    del role_row["primary"]
            elif role == "both":
                role_row["primary"] = model_s
                role_row["judge"] = model_s
            else:
                role_row["primary"] = model_s
                if "judge" in role_row:
                    del role_row["judge"]
    if prov_map:
        locales["providers"] = prov_map
    if wants_model and not allow_model_writes and not _bakeoff_allows_model_write(cfg):
        return (
            "Changing locale models requires a bakeoff Winner (ADR-12). "
            "Confirm in the UI or use Model evaluation."
        )
    return None


def _apply_project(doc: Any, project: dict, path: Any) -> str | None:
    if not isinstance(project, dict):
        return "project must be an object"
    proj = doc.get("project")
    if not isinstance(proj, dict):
        return f"{path}: [project] table is missing"
    if "name" in project and str(project["name"]).strip():
        proj["name"] = str(project["name"]).strip()
    if "sourceLocale" in project or "source_locale" in project:
        src = project.get("sourceLocale", project.get("source_locale"))
        if src is not None and str(src).strip():
            proj["source_locale"] = str(src).strip()
    cat = doc.get("catalog")
    if not isinstance(cat, dict):
        cat = tomlkit.table()
        doc["catalog"] = cat
    if "catalogFormat" in project or "catalog_format" in project:
        fmt = project.get("catalogFormat", project.get("catalog_format"))
        if fmt is not None and str(fmt).strip():
            cat["format"] = str(fmt).strip()
    if "catalogPath" in project or "catalog_path" in project:
        cpath = project.get("catalogPath", project.get("catalog_path"))
        if cpath is not None and str(cpath).strip():
            cat["path"] = str(cpath).strip()
    if "skipKeys" in project or "skip_keys" in project:
        keys = project.get("skipKeys", project.get("skip_keys"))
        if keys is None:
            keys = []
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        if not isinstance(keys, list):
            return "skipKeys must be a list or comma-separated string"
        cat["skip_keys"] = _string_array([str(k) for k in keys])
    return None


def _write_permission_matrix(doc: Any, permission_matrix: dict) -> str | None:
    table = tomlkit.table()
    for op in OPERATIONS:
        flags = permission_matrix.get(op)
        if flags is None:
            flags = list(DEFAULT_MATRIX[op])
        if not isinstance(flags, (list, tuple)) or len(flags) != 4:
            return f"permission row {op!r} must have 4 booleans"
        merged = [bool(x) for x in flags]
        if op == "translate":
            merged[2] = False
        merged[0] = True
        arr = tomlkit.array()
        for item in merged:
            arr.append(item)
        table[op] = arr
    doc["permissions"] = table
    return None


def _bakeoff_allows_model_write(cfg: ProjectConfig) -> bool:
    """True when a bakeoff REPORT.md has a fresh Winners note (ADR-12).

    Freshness: Winner/Winners section must mention a date within the last
    ~45 days (monthly recheck + buffer). Stale reports still document history
    but do not unlock model writes.
    """
    from datetime import date, timedelta
    import re

    cutoff = date.today() - timedelta(days=45)
    date_re = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

    def _fresh(text: str, cutoff=cutoff) -> bool:
        if "Winner" not in text and "Winners" not in text:
            return False
        for match in date_re.finditer(text):
            try:
                stamped = date(
                    int(match.group(1)), int(match.group(2)), int(match.group(3)),
                )
            except ValueError:
                continue
            if stamped >= cutoff:
                return True
        return False

    try:
        from .model_eval import model_eval_view

        view = model_eval_view()
        if view.get("has_winner") and _fresh(str(view.get("reportText") or view.get("report") or "")):
            return True
        # Fall through to on-disk reports when the view only sets the flag.
    except Exception:
        pass
    for base in (
        cfg.root / "experiments" / "quality_bakeoff",
        cfg.root.parent / "experiments" / "quality_bakeoff",
        Path(__file__).resolve().parents[2] / "experiments" / "quality_bakeoff",
    ):
        for name, check in (("REPORT.md", _fresh), ("WAIVERS.md", _fresh_waiver)):
            path = base / name
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if check(text, cutoff):
                    return True
    return False


def _fresh_waiver(text: str, cutoff) -> bool:
    """A user-approved ADR-12 waiver line (``- 2026-11-14 claude-haiku-5-5: … (ADR-155)``) dated after ``cutoff``.

    Waivers stand in for a bakeoff Winner when the user switches models on smaller evidence (cloud smoke plus
    scorer calibration). They expire like a Winner, so the monthly recheck still happens.
    """
    from datetime import date
    import re

    for match in re.finditer(r"^- (20\d{2})-(\d{2})-(\d{2}) \S+: .*\(ADR-\d+\)", text, re.MULTILINE):
        try:
            stamped = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if stamped >= cutoff:
            return True
    return False


def save_settings(
    cfg: ProjectConfig,
    *,
    frozen: list | None = None,
    asap: list | None = None,
    overlay_edit: bool | None = None,
    permission_matrix: dict | None = None,
    reset_permissions: bool = False,
    fallbacks: dict | None = None,
    quality: dict | None = None,
    providers: list | None = None,
    locale_assignments: list | None = None,
    project: dict | None = None,
    allow_model_writes: bool = False,
) -> dict[str, Any]:
    """Mutate the parsed document. Replace the file only after ``load_config`` accepts it."""
    path = cfg.config_path
    if path is None:
        return {"ok": False, "error": "config path is not set"}
    original = path.read_text(encoding="utf-8")
    doc = tomlkit.parse(original)

    needs_locales = frozen is not None or asap is not None or fallbacks is not None or locale_assignments is not None
    if needs_locales:
        locales = _locales_table(doc)
        if locales is None:
            return {"ok": False, "error": f"{path}: [locales] table is missing"}

    if frozen is not None or asap is not None or fallbacks is not None:
        err = _apply_locales_arrays(doc, locales, frozen, asap, fallbacks)
        if err:
            return {"ok": False, "error": err}

    if overlay_edit is not None:
        _apply_overlay_edit(doc, overlay_edit)

    if reset_permissions:
        permission_matrix = {op: list(DEFAULT_MATRIX[op]) for op in OPERATIONS}
    if permission_matrix is not None:
        err = _write_permission_matrix(doc, permission_matrix)
        if err:
            return {"ok": False, "error": err}

    if quality is not None:
        err = _apply_quality(doc, quality, cfg, allow_model_writes)
        if err:
            return {"ok": False, "error": err}

    if providers is not None:
        err = _apply_providers(doc, providers)
        if err:
            return {"ok": False, "error": err}

    if locale_assignments is not None:
        err = _apply_locale_assignments(doc, locales, locale_assignments, cfg, allow_model_writes)
        if err:
            return {"ok": False, "error": err}

    if project is not None:
        err = _apply_project(doc, project, path)
        if err:
            return {"ok": False, "error": err}

    new_text = tomlkit.dumps(doc)
    err = write_config_atomically(path, new_text)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True}


# Soft: return cache as-is. Soft→hard: return stale and refresh in background.
# Hard: wait for a fresh probe (Ollama /api/tags is often ~1–2s).
_PROBE_SOFT_TTL_S = 60.0
_PROBE_HARD_TTL_S = 300.0
_PROBE_TTL_S = _PROBE_SOFT_TTL_S  # alias for older tests
_PROVIDER_STATUS_CACHE: dict[tuple, tuple[float, dict[str, dict[str, Any]]]] = {}
_PROVIDER_STATUS_LOCK = threading.Lock()
_PROVIDER_STATUS_REFRESHING: set[tuple] = set()
_PROVIDER_STATUS_EVENTS: dict[tuple, threading.Event] = {}

# Shared by /api/models and provider-status — one /api/tags probe per host.
_OLLAMA_TAGS_CACHE: dict[str, tuple[float, list[str], str | None]] = {}
_OLLAMA_TAGS_LOCK = threading.Lock()
_OLLAMA_TAGS_REFRESHING: set[str] = set()
_OLLAMA_TAGS_EVENTS: dict[str, threading.Event] = {}


def _ollama_tags_uncached(base: str) -> tuple[list[str], str | None]:
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        return models, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [], str(exc) or "Ollama not running"


def _refresh_ollama_tags(base: str) -> None:
    models, err = _ollama_tags_uncached(base)
    with _OLLAMA_TAGS_LOCK:
        _OLLAMA_TAGS_CACHE[base] = (time.monotonic(), models, err)
        done = _OLLAMA_TAGS_EVENTS.pop(base, None)
        _OLLAMA_TAGS_REFRESHING.discard(base)
    if done is not None:
        done.set()


def fetch_ollama_tags(base: str) -> tuple[list[str], str | None]:
    """``(models, error)`` for one Ollama host. Soft-cached 60s; SWR to 5 min.

    Shared by ``/api/models`` and ``provider_status_payload`` so a Settings
    load does not pay for ``/api/tags`` twice.
    """
    base = (base or "http://127.0.0.1:11434").rstrip("/")
    now = time.monotonic()
    with _OLLAMA_TAGS_LOCK:
        hit = _OLLAMA_TAGS_CACHE.get(base)
        if hit is not None:
            age = now - hit[0]
            if age < _PROBE_SOFT_TTL_S:
                return list(hit[1]), hit[2]
            if age < _PROBE_HARD_TTL_S:
                if base not in _OLLAMA_TAGS_REFRESHING:
                    _OLLAMA_TAGS_REFRESHING.add(base)
                    threading.Thread(
                        target=_refresh_ollama_tags,
                        args=(base,),
                        daemon=True,
                        name="ollama-tags-refresh",
                    ).start()
                return list(hit[1]), hit[2]

    wait_on: threading.Event | None = None
    lead = False
    with _OLLAMA_TAGS_LOCK:
        hit = _OLLAMA_TAGS_CACHE.get(base)
        if hit is not None and time.monotonic() - hit[0] < _PROBE_SOFT_TTL_S:
            return list(hit[1]), hit[2]
        if base in _OLLAMA_TAGS_REFRESHING:
            if hit is not None:
                return list(hit[1]), hit[2]
            wait_on = _OLLAMA_TAGS_EVENTS.setdefault(base, threading.Event())
        else:
            lead = True
            _OLLAMA_TAGS_REFRESHING.add(base)
            wait_on = threading.Event()
            _OLLAMA_TAGS_EVENTS[base] = wait_on

    if not lead:
        if wait_on is not None:
            wait_on.wait(timeout=4.0)
        with _OLLAMA_TAGS_LOCK:
            hit = _OLLAMA_TAGS_CACHE.get(base)
        if hit is not None:
            return list(hit[1]), hit[2]
        return [], "Ollama not running"

    try:
        models, err = _ollama_tags_uncached(base)
        with _OLLAMA_TAGS_LOCK:
            _OLLAMA_TAGS_CACHE[base] = (time.monotonic(), models, err)
            done = _OLLAMA_TAGS_EVENTS.pop(base, None)
        if done is not None:
            done.set()
        return models, err
    finally:
        with _OLLAMA_TAGS_LOCK:
            _OLLAMA_TAGS_REFRESHING.discard(base)
            done = _OLLAMA_TAGS_EVENTS.pop(base, None)
        if done is not None:
            done.set()


def _probe_provider(entry: NamedProvider, *, allow_cloud: bool) -> dict[str, Any]:
    """Status of one named provider. Short timeouts; never a paid call."""
    import os
    from pathlib import Path

    kind = (entry.kind or "ollama").lower()
    if kind == "ollama":
        base = (entry.url or "http://127.0.0.1:11434").rstrip("/")
        models, err = fetch_ollama_tags(base)
        if err is None:
            return {"status": "online", "models": models}
        return {"status": "offline", "models": [], "reason": "unreachable"}
    if kind in {"openai", "anthropic", "deepseek", "deepl", "openai_compat"}:
        from ..providers.keys import candidate_vars, key_source

        env_map = {
            "openai_compat": "OPENAI_COMPAT_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "deepl": "DEEPL_AUTH_KEY",
        }
        key_env = getattr(entry, "api_key_env", "") or None
        key = "x" if key_source(env_map.get(kind, ""), key_env) else ""
        # Never a paid call: "online" means usable (cloud allowed and a key set), and the reason says which is missing.
        if not allow_cloud:
            return {"status": "offline", "models": [], "reason": "cloud_off"}
        if not key.strip():
            return {"status": "offline", "models": [], "reason": "no_key",
                    "envVar": env_map.get(kind, ""),
                    "envVars": candidate_vars(env_map.get(kind, ""), key_env)}
        return {"status": "online", "models": []}
    if kind == "ctranslate2":
        mp = Path(entry.model_path) if entry.model_path else None
        if mp and mp.exists():
            return {"status": "online", "models": [entry.model_path]}
        return {"status": "offline", "models": [], "reason": "missing_path"}
    return {"status": "unknown", "models": []}


def _probe_all(
    registry: dict[str, NamedProvider],
    *,
    allow_cloud: bool,
) -> dict[str, dict[str, Any]]:
    def probe(entry: NamedProvider) -> dict[str, Any]:
        return _probe_provider(entry, allow_cloud=allow_cloud)

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(registry)))) as pool:
        futures = {pid: pool.submit(probe, entry) for pid, entry in registry.items()}
        return {pid: fut.result() for pid, fut in futures.items()}


def _health_meta(cfg: ProjectConfig | None = None) -> dict[str, Any]:
    return {
        "residency": {
            "policy": "switch",
            "module": "llm_localizator.providers.residency",
            "note": (
                "Only one Ollama/CT2 model should be resident; "
                "switch() stops then ensure_ready."
            ),
        },
        "breaker": {
            "translate_max_consecutive_rejects": int(
                getattr(cfg, "translate_max_consecutive_rejects", 10) or 0
            ) if cfg is not None else 10,
            "icu_skips_abort": False,
            "batch_provider_error_fallback": "none",
        },
    }


def _cache_copy(
    statuses: dict[str, dict[str, Any]],
    cfg: ProjectConfig | None = None,
) -> dict[str, Any]:
    out = {"ok": True, "statuses": {k: dict(v) for k, v in statuses.items()}}
    out.update(_health_meta(cfg))
    return out


def _refresh_provider_status(
    cache_key: tuple,
    registry: dict[str, NamedProvider],
    *,
    allow_cloud: bool,
) -> None:
    try:
        statuses = _probe_all(registry, allow_cloud=allow_cloud)
        with _PROVIDER_STATUS_LOCK:
            _PROVIDER_STATUS_CACHE[cache_key] = (time.monotonic(), statuses)
            done = _PROVIDER_STATUS_EVENTS.pop(cache_key, None)
        if done is not None:
            done.set()
    finally:
        with _PROVIDER_STATUS_LOCK:
            _PROVIDER_STATUS_REFRESHING.discard(cache_key)
            done = _PROVIDER_STATUS_EVENTS.pop(cache_key, None)
        if done is not None:
            done.set()


def provider_status_payload(cfg: ProjectConfig) -> dict[str, Any]:
    """Probe named providers. Hermetic-safe: short timeouts, no paid cloud calls.

    Uses stale-while-revalidate: a warm cache answers instantly; after the soft
    TTL a background thread refreshes while callers still get the last probe.
    Concurrent cold callers wait on one probe instead of stacking Ollama calls.
    """

    registry = cfg.providers or {
        "default": NamedProvider(
            id="default",
            name="Default",
            kind=cfg.provider.kind or "ollama",
            url=cfg.provider.url,
        )
    }
    allow = bool(getattr(cfg, "allow_cloud", False))
    cache_key = (
        str(cfg.root), allow,
        tuple((pid, e.kind, e.url, e.model_path) for pid, e in registry.items()),
    )
    now = time.monotonic()
    with _PROVIDER_STATUS_LOCK:
        hit = _PROVIDER_STATUS_CACHE.get(cache_key)
        if hit is not None:
            age = now - hit[0]
            if age < _PROBE_SOFT_TTL_S:
                return _cache_copy(hit[1], cfg)
            if age < _PROBE_HARD_TTL_S:
                if cache_key not in _PROVIDER_STATUS_REFRESHING:
                    _PROVIDER_STATUS_REFRESHING.add(cache_key)
                    threading.Thread(
                        target=_refresh_provider_status,
                        args=(cache_key, dict(registry)),
                        kwargs={"allow_cloud": allow},
                        daemon=True,
                        name="provider-status-refresh",
                    ).start()
                return _cache_copy(hit[1], cfg)

    # Cold / hard-expired: single-flight — one probe, others wait on its Event.
    wait_on: threading.Event | None = None
    lead = False
    with _PROVIDER_STATUS_LOCK:
        hit = _PROVIDER_STATUS_CACHE.get(cache_key)
        if hit is not None and time.monotonic() - hit[0] < _PROBE_SOFT_TTL_S:
            return _cache_copy(hit[1], cfg)
        if cache_key in _PROVIDER_STATUS_REFRESHING:
            if hit is not None:
                return _cache_copy(hit[1], cfg)
            wait_on = _PROVIDER_STATUS_EVENTS.get(cache_key)
            if wait_on is None:
                wait_on = threading.Event()
                _PROVIDER_STATUS_EVENTS[cache_key] = wait_on
        else:
            lead = True
            _PROVIDER_STATUS_REFRESHING.add(cache_key)
            wait_on = threading.Event()
            _PROVIDER_STATUS_EVENTS[cache_key] = wait_on

    if not lead:
        if wait_on is not None:
            wait_on.wait(timeout=4.0)
        with _PROVIDER_STATUS_LOCK:
            hit = _PROVIDER_STATUS_CACHE.get(cache_key)
        if hit is not None:
            return _cache_copy(hit[1], cfg)
        out = {"ok": True, "statuses": {}}
        out.update(_health_meta(cfg))
        return out

    try:
        statuses = _probe_all(registry, allow_cloud=allow)
        with _PROVIDER_STATUS_LOCK:
            _PROVIDER_STATUS_CACHE[cache_key] = (time.monotonic(), statuses)
            done = _PROVIDER_STATUS_EVENTS.pop(cache_key, None)
        if done is not None:
            done.set()
        return _cache_copy(statuses, cfg)
    finally:
        with _PROVIDER_STATUS_LOCK:
            _PROVIDER_STATUS_REFRESHING.discard(cache_key)
            done = _PROVIDER_STATUS_EVENTS.pop(cache_key, None)
        if done is not None:
            done.set()
