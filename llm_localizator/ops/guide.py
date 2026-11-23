"""Guided setup: an ordered, state-aware checklist from a bare folder to shipped translations.

One engine, two front ends (CLI ``guide`` and the web dashboard card). It reads
state that already exists -- config, catalogue, translation status, validation --
and never changes anything except the optional smoke test, which writes a small
marker file next to the state files.

Web UI localises step titles via ``guide_<id>`` and details via ``detail_key`` +
``detail_vars`` (English ``detail`` stays the CLI / fallback string).
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import catalog_for
from ..catalog.io import read_json
from ..core.cldr import language_name
from ..projects import ProjectConfig
from ..projects.init_layout import detect_layout, layouts_help, survey_layout
from ..providers.ollama import model_installed
from .types import GuideRequest, OpResult

__all__ = [
    "GuideStep", "build_guide", "op_guide", "run_smoke_test", "ollama_state", "SMOKE_FILE",
]

SMOKE_FILE = ".guide.json"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
_SMOKE_TEXT = "Save changes"


@dataclass
class GuideStep:
    id: str
    title: str
    status: str  # "done" | "todo"
    detail: str = ""
    cli: str | None = None
    web: str | None = None
    required: bool = True
    # Catalogue key + ``{var}`` substitutions for the web dashboard (ADR-style).
    detail_key: str = ""
    detail_vars: dict[str, str] = field(default_factory=dict)
    #: Where the packaged guide explains this step, e.g. "human#1" (C2, ADR-136).
    guide_section: str = ""


#: Step id -> section of the packaged guide that explains it (``llm-localizator help``).
GUIDE_SECTIONS = {
    "environment": "human#3", "project": "human#3", "approach": "human#1",
    "languages": "human#2", "model": "human#2", "voice": "human#2",
    "apply-mode": "agent#4", "hardcoded-loop": "agent#4", "translate": "human#3",
    "review": "human#4", "ship": "human#4",
}


def guide_pointer(section: str) -> str:
    """``"human#4"`` -> ``"llm-localizator help human, section 4"``."""
    guide, _, number = section.partition("#")
    return f"llm-localizator help {guide}, section {number}" if number else f"llm-localizator help {guide}"


def _gs(
    step_id: str,
    title: str,
    status: str,
    detail: str,
    *,
    key: str = "",
    params: dict | None = None,
    cli: str | None = None,
    web: str | None = None,
    required: bool = True,
) -> GuideStep:
    raw = {str(k): str(v) for k, v in (params or {}).items()}
    return GuideStep(
        step_id,
        title,
        status,
        detail,
        cli=cli,
        web=web,
        required=required,
        detail_key=key,
        detail_vars=raw,
    )


def ollama_state(url: str) -> tuple[bool, list[str]]:
    """Whether Ollama answers at ``url`` and which models it has. Never raises."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=3) as resp:
            data = json.loads(resp.read())
        return True, [str(m.get("name", "")) for m in data.get("models", [])]
    except Exception:
        return False, []


def _smoke_path(cfg: ProjectConfig) -> Path:
    return cfg.state_root() / SMOKE_FILE


def _read_smoke(cfg: ProjectConfig) -> dict:
    try:
        data = read_json(_smoke_path(cfg))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run_smoke_test(cfg: ProjectConfig, model: str | None = None) -> tuple[bool, str]:
    """Translate one fixed string and remember the result.

    Uses the configured model unless ``model`` names another one to try.
    """
    from ..catalog.io import atomic_write_text
    from ..providers import CompletionRequest, ProviderError, build_provider

    locale = (cfg.active_targets() or cfg.targets or [""])[0]
    if model is None:
        try:
            model = cfg.model_for(locale)
        except ValueError as exc:
            return False, str(exc)
    language = language_name(locale) if locale else "French"
    try:
        provider = build_provider(cfg.provider, kind=cfg.provider_kind_for(locale) if locale else None)
        answer = provider.complete(CompletionRequest(
            prompt=(
                f"Translate this UI string to {language}. "
                f"Output ONLY the translation.\n\n{_SMOKE_TEXT}"
            ),
            model=model,
            timeout_s=120,
            source_texts=[_SMOKE_TEXT],
            target_locale=locale or None,
        ))
    except ProviderError as exc:
        return False, f"{model} did not answer: {exc}"
    ok = bool(answer and answer.strip())
    if ok:
        marker = {
            "model": model,
            "ok": True,
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        path = _smoke_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(marker, indent=2) + "\n")
    return ok, (
        f"{model} answered: {answer.strip()[:60]!r}" if ok else f"{model} returned nothing"
    )


def _step_environment(cfg: ProjectConfig | None, req: GuideRequest) -> GuideStep:
    import shutil

    from ..providers.ollama import OLLAMA_INSTALL_URL, ollama_unreachable_message

    kind = cfg.provider.kind if cfg else "ollama"
    url = (cfg.provider.url if cfg else "") or DEFAULT_OLLAMA_URL
    title = "Prepare your machine"
    if _approach_of(cfg) in ("agent", "human"):
        return _gs(
            "environment", title, "done",
            "No local model needed for this approach.",
            key="guide_env_not_needed",
        )
    if kind == "null":
        return _gs(
            "environment", title, "done",
            "Test provider; nothing to install.",
            key="guide_env_null",
        )
    if kind != "ollama":
        detail = (
            f"Cloud provider '{kind}' is configured "
            "(API key is read from the environment)."
        )
        return _gs(
            "environment", title, "done", detail,
            key="guide_env_cloud", params={"kind": kind},
        )
    if req.skip_provider:
        return _gs(
            "environment", title, "done",
            "Provider check skipped.",
            key="guide_env_skipped",
        )
    up, models = ollama_state(url)
    if up:
        detail = f"Ollama is running at {url} with {len(models)} model(s) installed."
        return _gs(
            "environment", title, "done", detail,
            key="guide_env_ollama_up",
            params={"url": url, "n": len(models)},
        )
    if not shutil.which("ollama"):
        detail = (
            f"Ollama is not installed (needed for local translation). "
            f"Install it from {OLLAMA_INSTALL_URL}, then open a new terminal and run "
            "`ollama serve`."
        )
        return _gs(
            "environment", title, "todo", detail,
            key="guide_env_ollama_missing",
            params={"url": OLLAMA_INSTALL_URL},
            cli=f"# see {OLLAMA_INSTALL_URL}",
        )
    return _gs(
        "environment", title, "todo",
        ollama_unreachable_message(url),
        key="guide_env_ollama_down",
        params={"url": url, "install": OLLAMA_INSTALL_URL},
        cli="ollama serve",
    )


def _catalog_counts(cfg: ProjectConfig) -> tuple[int, int]:
    catalog = catalog_for(cfg)
    namespaces = cfg.namespaces_for(catalog)
    keys = sum(len(catalog.load(cfg.source_locale, ns)) for ns in namespaces)
    return len(namespaces), keys


def _step_project(root: Path, cfg: ProjectConfig | None) -> GuideStep:
    title = "Create the project"
    if cfg is None:
        found = detect_layout(root)
        if found is not None:
            fmt, template, _scanner = found
            namespaces, _locales = survey_layout(root, template, fmt, "en")
            detail = (
                f"Found a {fmt} catalogue ({template}) with {len(namespaces)} namespace(s). "
                "Create the config so llm-localizator can use it."
            )
            return _gs(
                "project", title, "todo", detail,
                key="guide_project_found",
                params={"fmt": fmt, "template": template, "n": len(namespaces)},
                cli="llm-localizator init",
            )
        detail = f"No message catalogue found under {root}.\n{layouts_help()}"
        return _gs(
            "project", title, "todo", detail,
            key="guide_project_none",
            params={"root": str(root), "layouts": layouts_help()},
            cli="llm-localizator init",
        )
    try:
        namespaces, keys = _catalog_counts(cfg)
    except Exception as exc:
        detail = f"Config found but the catalogue could not be read: {exc}"
        return _gs(
            "project", title, "todo", detail,
            key="guide_project_read_fail",
            params={"err": str(exc)},
            cli="llm-localizator doctor",
        )
    if keys == 0:
        detail = (
            f"Config found, but the {cfg.source_locale} catalogue at {cfg.catalog_path} "
            "has no keys. Add your source strings first."
        )
        return _gs(
            "project", title, "todo", detail,
            key="guide_project_empty",
            params={"locale": cfg.source_locale, "path": str(cfg.catalog_path)},
            cli="llm-localizator doctor",
        )
    src_name = language_name(cfg.source_locale)
    detail = (
        f"{cfg.name}: {keys} source key(s) in {namespaces} namespace(s) "
        f"({cfg.catalog_format}, source language {src_name})."
    )
    return _gs(
        "project", title, "done", detail,
        key="guide_project_ok",
        params={
            "name": cfg.name,
            "keys": keys,
            "namespaces": namespaces,
            "fmt": cfg.catalog_format,
            "source": src_name,
        },
    )


def _approach_of(cfg: ProjectConfig | None) -> str:
    return (getattr(cfg, "translate_approach", "") or "") if cfg is not None else ""


def _step_approach(cfg: ProjectConfig | None, req: GuideRequest) -> GuideStep:
    """Show how the project can be localized and record the choice (ADR-123)."""
    from .approaches import APPROACHES, by_id, probe, reason_key, recommend

    title = "Choose how to localize"
    if cfg is None:
        return _gs(
            "approach", title, "todo",
            "Available once the project exists.",
            key="guide_approach_need_project",
        )
    chosen = by_id(_approach_of(cfg))
    if chosen is not None:
        return _gs(
            "approach", title, "done",
            f"{chosen.title} ({chosen.id}). Change it any time with "
            "`llm-localizator approach --set <id>`.",
            key="guide_approach_ok",
            params={"title": chosen.title, "id": chosen.id},
        )
    probes = probe(cfg, skip=bool(req.skip_provider))
    rec, reason = recommend(probes)
    options = "\n".join(f"- {a.id}: {a.title} - {a.words}; {a.cost}." for a in APPROACHES)
    detail = (
        "Pick who writes the translations:\n"
        f"{options}\n"
        f"Recommended here: {rec} ({reason})."
    )
    # The web page localises each option and the reason from catalogue keys
    # (``guide_approach_<id>_title|words|cost``, ``guide_approach_reason_<n>``); the English
    # values ride along as the fallback.
    parts: dict[str, str] = {"approaches": ",".join(a.id for a in APPROACHES)}
    for a in APPROACHES:
        parts[f"approach_{a.id}_title"] = a.title
        parts[f"approach_{a.id}_words"] = a.words
        parts[f"approach_{a.id}_cost"] = a.cost
    return _gs(
        "approach", title, "todo", detail,
        key="guide_approach_pick",
        params={"options": options, "rec": rec, "reason": reason,
                "reason_key": reason_key(reason), **parts},
        cli=f"llm-localizator approach --set {rec}",
    )


def _step_languages(cfg: ProjectConfig | None) -> GuideStep:
    title = "Choose languages"
    if cfg is None:
        return _gs(
            "languages", title, "todo",
            "Available once the project exists.",
            key="guide_langs_need_project",
        )
    if not cfg.targets:
        return _gs(
            "languages", title, "todo",
            "No target languages yet. Add at least one, for example Polish:",
            key="guide_langs_none",
            cli="llm-localizator add-locale --locale pl",
            web="/app",
        )
    names = ", ".join(f"{loc} ({language_name(loc)})" for loc in cfg.targets)
    return _gs(
        "languages", title, "done",
        f"Translating into: {names}.",
        key="guide_langs_ok",
        params={"names": names},
    )


def _step_hardcoded_loop(cfg: ProjectConfig | None) -> GuideStep:
    """Status of the dual-loop hardcoded hunt (static + optional en-XX)."""
    title = "Clear hardcoded UI strings"
    if cfg is None or not cfg.scan_adapter:
        return _gs(
            "hardcoded-loop", title, "done",
            "No scanner configured.",
            key="guide_hardcoded_none",
            required=False,
        )
    from .agent_hardcoded import scan_cache_status

    st = scan_cache_status(cfg)
    counts = st.get("counts") or {}
    high_med = int(counts.get("high") or 0) + int(counts.get("medium") or 0)
    en_xx = st.get("enXx") or {}
    next_rows = st.get("next") or []
    hint = next_rows[0]["cmd"] if next_rows else "llm-localizator agent-hardcoded --split auto --refresh"
    why = next_rows[0].get("why", "") if next_rows else ""
    lagging = bool(en_xx.get("lagging"))
    clear = (
        bool(st.get("cached"))
        and not st.get("stale")
        and high_med == 0
        and not lagging
    )
    if clear:
        return _gs(
            "hardcoded-loop", title, "done",
            "Static high/medium hits are clear and the en-XX marker is not lagging EN.",
            key="guide_hardcoded_ok",
            cli=hint,
            required=False,
        )
    detail = why or "Run the static report, wire source (ADR-32), then re-pseudo en-XX after EN growth."
    return _gs(
        "hardcoded-loop", title, "todo",
        detail,
        key="guide_hardcoded_todo",
        params={"why": detail},
        cli=hint,
        required=False,
    )


def _step_apply_mode(cfg: ProjectConfig | None) -> GuideStep:
    title = "Choose how scan results are applied"
    if cfg is None or not cfg.scan_adapter:
        return _gs(
            "apply-mode", title, "done",
            "No scanner configured, so there is nothing to apply.",
            key="guide_apply_none",
            required=False,
        )
    path = cfg.config_path
    try:
        explicit = bool(path) and "[apply]" in path.read_text(encoding="utf-8")
    except OSError:
        explicit = False
    if explicit:
        return _gs(
            "apply-mode", title, "done",
            f"Accepted scan results are applied in {cfg.apply_mode} mode.",
            key="guide_apply_set",
            params={"mode": cfg.apply_mode},
            required=False,
        )
    return _gs(
        "apply-mode", title, "todo",
        "Decide what accepting a hardcoded string does: manual (you run apply), request "
        "(a review ticket) or auto. Add `[apply] mode = \"manual\"` to .llm-localize.toml, "
        "then list what the scanner found:",
        key="guide_apply_todo",
        cli="llm-localizator agent-hardcoded --format json",
        required=False,
    )


def _step_voice(cfg: ProjectConfig | None) -> GuideStep:
    title = "Describe your product's voice"
    if cfg is None:
        return _gs(
            "voice", title, "done", "No project yet.",
            key="guide_voice_none", required=False,
        )
    if cfg.description or cfg.audience or cfg.tone:
        return _gs(
            "voice", title, "done",
            "Description, audience and tone are added to every translation prompt.",
            key="guide_voice_ok",
            required=False,
        )
    return _gs(
        "voice", title, "todo",
        "Tell the model what the product is and who reads it. Add a `[voice]` table with "
        "`description`, `audience` and `tone` to .llm-localize.toml.",
        key="guide_voice_todo",
        required=False,
    )


def _status_rows(cfg: ProjectConfig, *, catalog=None, status_rows=None):
    from .status import collect

    if catalog is None:
        catalog = catalog_for(cfg)
    if status_rows is None:
        status_rows = collect(cfg, catalog)
    active = set(cfg.active_targets())
    return catalog, [row for row in status_rows if row.locale in active]


def _step_model(
    cfg: ProjectConfig | None,
    req: GuideRequest,
    *,
    rows=None,
) -> GuideStep:
    title = "Pick a model and test it"
    if cfg is None or not cfg.targets:
        return _gs(
            "model", title, "todo",
            "Available once languages are chosen.",
            key="guide_model_need_langs",
        )
    if _approach_of(cfg) in ("agent", "human"):
        return _gs(
            "model", title, "done",
            "No model needed: translations come from your agent or your translators.",
            key="guide_model_not_needed",
        )
    locale = (cfg.active_targets() or cfg.targets)[0]
    try:
        model = cfg.model_for(locale)
    except ValueError as exc:
        return _gs("model", title, "todo", str(exc), key="guide_model_err", params={"err": str(exc)})
    kind = cfg.provider.kind
    if kind == "null":
        return _gs(
            "model", title, "done",
            "Test provider; no model needed.",
            key="guide_model_null",
        )
    if kind == "ollama" and not req.skip_provider:
        up, installed = ollama_state(cfg.provider.url or DEFAULT_OLLAMA_URL)
        if up and not model_installed(model, installed):
            return _gs(
                "model", title, "todo",
                f"Model '{model}' is not installed in Ollama.",
                key="guide_model_missing",
                params={"model": model},
                cli=f"ollama pull {model}",
            )
    try:
        if rows is None:
            _catalog, rows = _status_rows(cfg)
        already_translated = any(row.translated > 0 for row in rows)
    except Exception:
        already_translated = False
    marker = _read_smoke(cfg)
    if already_translated or (marker.get("ok") and marker.get("model") == model):
        return _gs(
            "model", title, "done",
            f"'{model}' works.",
            key="guide_model_ok",
            params={"model": model},
        )
    return _gs(
        "model", title, "todo",
        f"Model '{model}' is set. Run one test translation to confirm it works.",
        key="guide_model_test",
        params={"model": model},
        cli="llm-localizator guide --smoke-test",
    )


def _step_translate(cfg: ProjectConfig | None, *, rows=None) -> GuideStep:
    title = "Translate"
    if cfg is None or not cfg.targets:
        return _gs(
            "translate", title, "todo",
            "Available once languages are chosen.",
            key="guide_tr_need_langs",
        )
    try:
        if rows is None:
            _catalog, rows = _status_rows(cfg)
    except Exception as exc:
        return _gs(
            "translate", title, "todo",
            f"Could not read status: {exc}",
            key="guide_tr_status_fail",
            params={"err": str(exc)},
        )
    pending = sum(row.missing + row.stale for row in rows)
    summary = ", ".join(f"{r.locale} {r.translated}/{r.total}" for r in rows) or "no active languages"
    if rows and pending == 0 and all(r.total for r in rows):
        detail = (
            f"Active languages are fully translated ({summary}). "
            "Frozen targets stay visible in status but are skipped until you pass "
            "`--locales <code>`."
        )
        return _gs(
            "translate", title, "done", detail,
            key="guide_tr_done",
            params={"summary": summary},
        )
    approach = _approach_of(cfg)
    if approach == "agent":
        return _gs(
            "translate", title, "todo",
            f"{pending} string(s) still need translating ({summary}). Ask your agent to fill "
            "them from the backlog, then stamp its edits with `llm-localizator adopt`.",
            key="guide_tr_pending_agent",
            params={"pending": pending, "summary": summary},
            cli="llm-localizator agent-backlog",
        )
    if approach == "human":
        return _gs(
            "translate", title, "todo",
            f"{pending} string(s) still need translating ({summary}). Export them for your "
            "translators, then import the file they return (or translate in the web editor).",
            key="guide_tr_pending_human",
            params={"pending": pending, "summary": summary},
            cli="llm-localizator export --format xlsx",
            web="/app/editor",
        )
    if approach == "cloud" or cfg.provider.kind in ("anthropic", "openai", "deepseek", "deepl", "openai_compat"):
        return _gs(
            "translate", title, "todo",
            f"{pending} string(s) still need translating ({summary}). Check the price with "
            "`llm-localizator estimate-cost` first; the [budget] ceiling stops a run that would exceed it.",
            key="guide_tr_pending_cloud",
            params={"pending": pending, "summary": summary},
            cli="llm-localizator estimate-cost",
        )
    try:
        from ..projects.taskqueue import tq_available
        prefer_queue = tq_available()
    except Exception:
        prefer_queue = False
    translate_cli = (
        "llm-localizator translate"
        if prefer_queue
        else "llm-localizator run-translate"
    )
    if prefer_queue:
        detail = (
            f"{pending} string(s) still need translating ({summary}). "
            "Taskqueue is available — `translate` submits and returns; watch with `tq status`."
        )
        key = "guide_tr_pending_tq"
    else:
        detail = (
            f"{pending} string(s) still need translating ({summary}). "
            "This runs on your machine and can take a while."
        )
        key = "guide_tr_pending_local"
    return _gs(
        "translate", title, "todo", detail,
        key=key,
        params={"pending": pending, "summary": summary},
        cli=translate_cli,
    )


def _step_review(
    cfg: ProjectConfig | None,
    translated: bool,
    *,
    catalog=None,
    skip_validate: bool = False,
) -> GuideStep:
    title = "Review and fix"
    if cfg is None or not translated:
        return _gs(
            "review", title, "todo",
            "Available once translation has run.",
            key="guide_rev_need_tr",
        )
    if skip_validate:
        return _gs(
            "review", title, "todo",
            "Translations exist. Run validate (or open the editor) to check for issues.",
            key="guide_rev_validate_hint",
            cli="llm-localizator validate",
            web="/app/editor",
        )
    from ..pipeline.validate import run_validation

    if catalog is None:
        catalog = catalog_for(cfg)
    report = run_validation(cfg, catalog, locales=cfg.active_targets())
    errors, warnings = len(report.errors), len(report.warnings)
    if errors:
        detail = (
            f"{errors} error(s) and {warnings} warning(s). Fix the errors, or open the "
            "editor to review them."
        )
        return _gs(
            "review", title, "todo", detail,
            key="guide_rev_errors",
            params={"errors": errors, "warnings": warnings},
            cli="llm-localizator validate",
            web="/app/editor",
        )
    if _approach_of(cfg) == "hybrid":
        return _gs(
            "review", title, "todo",
            f"No validation errors ({warnings} warning(s)). Hybrid approach: a reviewer still "
            "checks short and button labels in the editor before you ship.",
            key="guide_rev_hybrid",
            params={"warnings": warnings},
            web="/app/editor",
        )
    return _gs(
        "review", title, "done",
        f"No validation errors ({warnings} warning(s)). Open the editor to spot-check wording.",
        key="guide_rev_ok",
        params={"warnings": warnings},
        web="/app/editor",
    )


def _step_ship(all_done: bool) -> GuideStep:
    return _gs(
        "ship", "Ship and keep current",
        "done" if all_done else "todo",
        "Export the translations back to your app with `llm-localizator export`. When source "
        "strings change, run `llm-localizator sync` to find what needs translating again.",
        key="guide_ship_detail",
        cli="llm-localizator export",
        required=False,
    )


def build_guide(
    root: Path,
    cfg: ProjectConfig | None,
    req: GuideRequest,
    *,
    catalog=None,
    status_rows=None,
) -> list[GuideStep]:
    rows = None
    if cfg is not None and cfg.targets:
        try:
            _catalog, rows = _status_rows(cfg, catalog=catalog, status_rows=status_rows)
        except Exception:
            rows = None
    steps = [
        _step_environment(cfg, req),
        _step_project(root, cfg),
        _step_approach(cfg, req),
        _step_languages(cfg),
        _step_model(cfg, req, rows=rows),
        _step_voice(cfg),
        _step_apply_mode(cfg),
        _step_hardcoded_loop(cfg),
    ]
    translate = _step_translate(cfg, rows=rows)
    steps.append(translate)
    steps.append(_step_review(
        cfg, translate.status == "done", catalog=catalog,
        skip_validate=bool(req.skip_validate),
    ))
    skip_ship = ("apply-mode", "voice", "hardcoded-loop")
    steps.append(_step_ship(all(s.status == "done" for s in steps if s.id not in skip_ship)))
    for step in steps:
        step.guide_section = step.guide_section or GUIDE_SECTIONS.get(step.id, "")
    return steps


def _render(steps: list[GuideStep]) -> list[str]:
    lines: list[str] = []
    for number, step in enumerate(steps, 1):
        mark = "x" if step.status == "done" else " "
        suffix = "" if step.required else " (optional)"
        lines.append(f"[{mark}] {number}. {step.title}{suffix}")
        for row in step.detail.splitlines():
            lines.append(f"      {row}")
        if step.guide_section and step.status != "done":
            lines.append(f"      see: {guide_pointer(step.guide_section)}")
    return lines


def op_guide(
    cfg: ProjectConfig | None,
    req: GuideRequest,
    *,
    catalog=None,
    status_rows=None,
) -> OpResult:
    root = Path(req.directory).resolve() if req.directory else (
        cfg.root if cfg is not None else Path.cwd()
    )
    smoke_line = None
    if req.smoke_test and cfg is not None:
        if cfg.provider.kind not in ("ollama", "null") and not req.yes:
            smoke_line = (
                f"Smoke test skipped: '{cfg.provider.kind}' is a paid cloud provider. "
                "Re-run with --yes to send one short string."
            )
        else:
            _ok, smoke_line = run_smoke_test(cfg)
    steps = build_guide(root, cfg, req, catalog=catalog, status_rows=status_rows)
    required = [s for s in steps if s.required]
    done = sum(1 for s in required if s.status == "done")
    next_step = next((s for s in required if s.status == "todo"), None)
    lines = _render(steps)
    if smoke_line:
        lines.append("")
        lines.append(smoke_line)
    if cfg is not None and getattr(cfg, "source_edits", None):
        lines.append("")
        lines.append(
            f"Source edits: {cfg.source_edits} (decisions in {cfg.decisions_in}); "
            "change with [source_policy] in .llm-localize.toml."
        )
    lines.append("")
    if next_step is None:
        lines.append("All steps done. Run `llm-localizator sync` whenever your source strings change.")
    else:
        lines.append(f"Next: {next_step.title}")
        if next_step.cli:
            lines.append(f"  run: {next_step.cli}")
    return OpResult(
        ok=True,
        exit_code=0,
        command="guide",
        summary=f"{done}/{len(required)} steps done"
        + (f"; next: {next_step.title}" if next_step else ""),
        lines=lines,
        data={
            "steps": [asdict(s) for s in steps],
            "next": next_step.id if next_step else None,
            "done": done,
            "total": len(required),
            "hasConfig": cfg is not None,
            "tqAvailable": shutil.which("tq") is not None,
        },
    )
