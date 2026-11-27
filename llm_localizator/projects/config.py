"""Project configuration: ``.llm-localize.toml``.

Discovery is three-way and ordered (ADR-3): a named lookup in the registry, an
explicit path, or an upward walk from the current directory. The third is what
makes CI and fresh clones work with no machine-level state.

Catalogue, glossary, context, and document source paths are relative to the
directory containing the config. Engine sidecars (state, history, scores, TM,
review, budget) default to ``~/.llm_localize/data/<name>/`` (ADR-112); set
``[project] data_home = "project"`` to keep them beside the config instead.
"""

from __future__ import annotations

import re
import tomllib
import warnings
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

PLACE_POLICIES = ("auto", "request", "review", "never")

# C-002: opt-in wording per style; the default (no preset) adds nothing (ADR-89).
STYLE_PRESETS = {
    "faithful": "Style: stay close to the source wording and structure; do not paraphrase.",
    "fluid": "Style: write natural, idiomatic text; reorder or rephrase when it reads better, keeping the meaning.",
    "creative": "Style: adapt for impact in the target culture; slogans and marketing copy may be rewritten, keeping the intent.",
}

__all__ = [
    "ProjectConfig",
    "ProviderConfig",
    "NamedProvider",
    "LocaleRole",
    "CONFIG_FILENAME",
    "load_config",
    "discover_config",
    "ConfigError",
]

CONFIG_FILENAME = ".llm-localize.toml"


class ConfigError(Exception):
    """Configuration is missing, malformed, or internally inconsistent."""



def _register_wording(locale: str, register: str) -> str:
    """Language-profile wording for an explicitly chosen register (C-003)."""
    from ..core.locales import profile

    prof = profile(locale)
    return prof.formal_prompt if register == "formal" else prof.informal_prompt

#: How a project can be localized (ADR-123); ops/approaches.py describes each.
APPROACH_IDS = ("local", "cloud", "agent", "human", "hybrid")


@dataclass
class ProviderConfig:
    kind: str = "ollama"
    url: str = "http://localhost:11434"
    keep_alive: str = "30m"
    options: dict = field(default_factory=lambda: {"temperature": 0.1, "top_p": 0.9, "num_gpu": 99})
    timeout_batch_s: int = 600
    timeout_single_s: int = 300
    timeout_shorten_s: int = 120
    # CTranslate2 model directory (Wave 3b / MADLAD). Unused by Ollama.
    model_path: str = ""
    # Name of the environment variable that holds this provider's API key (never the key itself).
    api_key_env: str = ""


@dataclass
class NamedProvider:
    """One named LLM endpoint (ADR-47). ``id`` is the TOML table key."""

    id: str
    name: str = ""
    kind: str = "ollama"
    url: str = "http://localhost:11434"
    keep_alive: str = "30m"
    options: dict = field(default_factory=lambda: {"temperature": 0.1, "top_p": 0.9, "num_gpu": 99})
    timeout_batch_s: int = 600
    timeout_single_s: int = 300
    timeout_shorten_s: int = 120
    model_path: str = ""
    api_key_env: str = ""

    def display_name(self) -> str:
        return self.name.strip() or self.id

    def as_provider_config(self) -> ProviderConfig:
        return ProviderConfig(
            kind=self.kind,
            url=self.url,
            keep_alive=self.keep_alive,
            options=dict(self.options or {}),
            timeout_batch_s=self.timeout_batch_s,
            timeout_single_s=self.timeout_single_s,
            timeout_shorten_s=self.timeout_shorten_s,
            model_path=self.model_path,
            api_key_env=self.api_key_env,
        )


def _named_from_provider(provider: ProviderConfig, *, id: str = "default", name: str = "") -> NamedProvider:
    return NamedProvider(
        id=id,
        name=name or ("Default" if id == "default" else id),
        kind=provider.kind or "ollama",
        url=provider.url or "http://localhost:11434",
        keep_alive=provider.keep_alive,
        options=dict(provider.options or {}),
        timeout_batch_s=provider.timeout_batch_s,
        timeout_single_s=provider.timeout_single_s,
        timeout_shorten_s=provider.timeout_shorten_s,
        model_path=provider.model_path or "",
        api_key_env=provider.api_key_env or "",
    )


@dataclass
class LocaleRole:
    """Optional per-locale translator / judge roles (ADR-21)."""

    primary: str | None = None
    secondary: str | None = None
    judge: str | None = None
    prefer_secondary: bool = False


@dataclass
class ProjectConfig:
    root: Path
    name: str
    source_locale: str = "en"
    # Where engine sidecars live (ADR-112): engine → ~/.llm_localize/data/<name>/
    # (or LLM_LOCALIZE_HOME); project → beside the config (legacy).
    data_home: str = "engine"

    catalog_format: str = "json-nested"
    catalog_standard: str = "icu"
    catalog_path: str = "messages/{locale}/{namespace}.json"
    namespaces: str | list[str] = "*"
    skip_keys: set[str] = field(default_factory=set)
    # [exclude] (ADR-71): key/namespace globs and source-text regexes that are never translated.
    exclude_keys: tuple[str, ...] = ()
    # [validate.severity] (ADR-72): check id -> "off" | "warning" | "error".
    severity_overrides: dict[str, str] = field(default_factory=dict)
    exclude_source: tuple[re.Pattern[str], ...] = ()
    skip_namespaces: set[str] = field(default_factory=set)
    # Branch source strings are meant to be synced from; `sync` warns elsewhere.
    source_branch: str = "main"

    targets: list[str] = field(default_factory=list)
    # Locales that stay in the catalogue but are skipped by default translate /
    # improve / review / sync / documents / rescore / taskqueue sweeps. Explicit
    # ``--locales`` (or a checked frozen locale in the web UI) still runs them.
    frozen: list[str] = field(default_factory=list)
    # Prefer these active locales first in default sweeps (ADR-47). Disjoint from frozen.
    asap: list[str] = field(default_factory=list)
    pivots: dict[str, str] = field(default_factory=dict)
    # Display-only. A missing target may show this locale's text in the editor.
    # It is not copied into the catalogue and not served by the bundle (ADR-44).
    fallbacks: dict[str, str] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)
    roles: dict[str, LocaleRole] = field(default_factory=dict)

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    # Named endpoints (ADR-47). Always includes at least ``default`` after load.
    providers: dict[str, NamedProvider] = field(default_factory=dict)

    domain: str = "a software application"
    glossary_path: Path | None = None
    # Read-only glossaries merged under the project file (project wins).
    glossary_shared: list[Path] = field(default_factory=list)
    # Namespace → domain name(s) for glossary subset selection (R-10).
    glossary_domains: dict[str, list[str]] = field(default_factory=dict)
    context_dir: Path | None = None
    examples_file: Path | None = None
    tm_dir: Path | None = None
    # Read-only TM consulted after the project memory. Writes stay on tm_dir.
    tm_shared: Path | None = None
    tm_shared_more: list[Path] = field(default_factory=list)  # C-030: later read-only memories
    tm_write: Path | None = None  # C-030: also receives approved text
    org_use: bool = False  # C-036: read the organisation TM and glossary (ADR-99)
    org_contribute: bool = False  # C-036: approved text also goes to the organisation TM
    git_host: dict = field(default_factory=dict)  # C-015: opt-in PR settings (ADR-101)
    register: str = "informal"  # informal | formal
    register_set: bool = False  # [prompt] register was given: use profile wording, V40
    # Prompt instruction family: chat (default) or mt_chat (shorter MT-oriented).
    prompt_family: str = "chat"
    locale_prompt_families: dict[str, str] = field(default_factory=dict)
    # locale → (register override or "", style notes). Empty register uses global.
    locale_styles: dict[str, tuple[str, str]] = field(default_factory=dict)
    # ADR-60: project prompt text, bridge locale, identity.
    display_name: str = ""
    description: str = ""
    audience: str = ""
    tone: str = ""  # C-001 ``[voice] tone``; empty adds no prompt line
    style_preset: str = ""  # C-002 faithful | fluid | creative; empty adds no prompt line
    locale_style_presets: dict[str, str] = field(default_factory=dict)
    prompt_localize: str = "source"  # source | target | per-model
    model_prompts: dict[str, tuple[str, bool]] = field(default_factory=dict)
    glossary_conflict: str = "own"  # own | shared | flag
    bridge_mode: str = "none"  # none | en | custom
    bridge_locale: str = ""
    bridge_model: str = ""
    bridge_store: bool = True

    state_dir: Path | None = None
    flags_path: Path | None = None
    history_dir: Path | None = None
    scores_dir: Path | None = None

    scan_adapter: str | None = None
    scan_src_dirs: list[str] = field(default_factory=list)
    #: Python server code whose payload strings people read (B3, ADR-134).
    scan_server_dirs: list[str] = field(default_factory=list)
    scan_exclude: list[str] = field(default_factory=list)
    scan_unskip: list[str] = field(default_factory=list)
    scan_t_functions: list[str] = field(default_factory=list)  # project-specific translate wrappers
    scan_content_globs: list[str] = field(default_factory=list)  # opt-in shown-text files (OpenAPI, bot YAML)
    scan_directive_aliases: bool = True  # eslint/noqa-style ignores count as l10n-ignore
    scan_unused_allow: list[str] = field(default_factory=list)  # key globs never reported by validate --unused
    #: ``[scan.surfaces.<name>]``: {"paths": [globs], "mode": "fix" | "report" | "ignore"}.
    #: Empty means every finding is a "fix" finding, as before.
    scan_surfaces: dict[str, dict] = field(default_factory=dict)
    scan_out_dir: Path | None = None

    # Long-form Markdown documents (terms, privacy policy). Separate from the
    # message catalogue: a different directory, a different state layout, and
    # usually a larger model, because legal register is where a small model's
    # output stops being acceptable.
    documents_dir: Path | None = None
    documents_state_dir: Path | None = None
    documents_model: str | None = None
    # Extra confirmed roots. ``[documents]`` is collection ``legal``; this table
    # is how a project adds help or any other directory without a code change.
    collections: dict = field(default_factory=dict)

    # Automated quality / improve loop (local by default).
    quality_threshold: float = 0.55
    # Per-locale override of quality_threshold: [quality.thresholds] pl = 0.6.
    quality_thresholds: dict[str, float] = field(default_factory=dict)
    # Content tiers (ADR-52): glob -> "human" | "review" | "auto"; first match wins.
    quality_tiers: dict[str, str] = field(default_factory=dict)
    # LQS band cuts (Wave 2 judge). Parsed now; BT path still uses threshold only.
    band_approve: float = 0.95
    band_flag: float = 0.90
    band_retranslate: float = 0.80
    # Below this score a candidate is held as a draft, not written (C2). None = per-scale default.
    write_floor: float | None = None
    # Judge one- and two-word keys with the scoring model when no judge_model is set (C3).
    judge_risky: bool = True
    improve_model: str | None = None
    score_model: str | None = None
    # Named provider id (or kind) for BT scoring, the judge and improve scoring. None = the
    # translator's provider. Lets a cloud translator score locally, or a fully cloud run score on cloud.
    score_provider: str | None = None
    judge_model: str | None = None
    # When None, translate auto-defers LLM scoring if score_model != pin model.
    defer_scoring: bool | None = None
    bt_batch_size: int = 5
    #: Cloud scorer: keys per back-translation request (0 = use [translate] cloud_batch_size) and parallel requests.
    bt_cloud_batch_size: int = 0
    bt_workers: int = 4
    # Vision-capable model for screenshot-context translation. Unset by
    # default -- most local text models cannot accept images, so screenshot
    # attachment is skipped entirely unless a project opts in explicitly.
    vision_model: str | None = None
    improve_limit: int = 50
    # After KEEP/FAIL, skip the same src_sha for this many hours so --limit
    # batches rotate. 0 = skip forever until source changes or --include-rejected.
    improve_skip_rejected: bool = True
    improve_reject_cooldown_hours: int = 168
    multi_sample: int = 1
    # Best-of-N sample count for the improve loop specifically. Falls back to
    # ``multi_sample`` when unset, so raising quality for the slow retranslate
    # path doesn't silently multiply cost on the fast translate path too.
    improve_multi_sample: int | None = None
    high_risk_patterns: list[str] | None = None
    # Prefer character n-gram / optional transformer TM near matches.
    tm_semantic: bool = False
    # Catalogue English similarity for few-shot examples (live keys, not only TM).
    catalogue_semantic: bool = False
    # Consumer visual findings JSONL (ADR-27). None → derive from context_dir.
    visual_findings_path: Path | None = None
    translate_batch_size: int = 10
    # Keys per request for a cloud (paying) locale; local models keep translate_batch_size.
    translate_cloud_batch_size: int = 50
    # [engine] id (ADR-156): the engine layered under this config, or None.
    engine_id: str | None = None
    # Set when --engine / engine_override applied it for one run; queued submits pass it on as --engine.
    engine_override: str | None = None
    translate_short_batch: bool = False
    # Compact history every N translate flushes (1 = every flush).
    history_compact_every: int = 10
    translate_enabled: bool = True
    # Skip GPU translate when pending keys for a locale are below this (0 = off).
    translate_min_keys: int = 50
    # One retry for answers that pass every hard gate but carry a soft defect (ADR-57).
    translate_soft_retry: bool = True
    # Abort a run after this many consecutive rejects/skips (0 = off).
    translate_max_consecutive_rejects: int = 10
    length_sensitive: list[str] = field(default_factory=lambda: ["de"])
    budget_monthly_usd: float = 0.0
    # on_request spends only on an explicit key list. dynamic may send every
    # due string whose pre-flight ceiling fits the remaining monthly budget.
    budget_mode: str = "on_request"
    budget_output_expansion: float = 2.0
    budget_thinking_tokens: int = 1024
    budget_rates: dict = field(default_factory=dict)
    # Prefer Anthropic Message Batches / OpenAI Batch for cloud multi-batch
    # translate (~50% list price). DeepSeek has no Batch API.
    budget_cloud_batch: bool = True
    gather_auto_stub: bool = False
    # Cross-origin overlay save/flag. Inspect stays on. Default off (ADR-33).
    overlay_edit: bool = False
    # QA marker locales in the UI picker / URL prefix (ADR-110). Empty = off
    # (production default). Dogfood may set ``["en-XX"]`` for leftover hunting.
    qa_locales: list[str] = field(default_factory=list)
    # Base URL of the published docs; the editor links each finding code to
    # ``<docs_url>/checks.md#<code>``. Empty means no link, only a tooltip.
    docs_url: str = ""
    # Opt-in Server-Timing / ``_timing`` on API responses (review UI profiler).
    web_profile: bool = False
    # Where `llm-localizator runtime install` puts the shipped i18n.js, relative to the
    # project root (a directory or a .js path). Empty = runtime not managed (ADR-118).
    web_runtime_path: str = ""
    # ``[qa]``: how the QA crawl reaches the UI (QaConfig, ADR-119). None = no crawl.
    qa: Any = None
    # How this project is localized (ADR-123): one of APPROACH_IDS, or "" = not chosen yet.
    translate_approach: str = ""
    # Optional role × operation overrides (ADR-39). Keys are operation names;
    # values are four booleans: Admin, Supervisor, Translator, Developer.
    # Overrides cannot grant Translator translate (enforced in ops/permissions).
    permission_matrix: dict[str, list[bool]] = field(default_factory=dict)
    # Opt-in completion webhook URL (ADR-40). Empty = off.
    notify_webhook: str = ""
    # "json" (envelope, HMAC-signed) or "slack" ({"text"} for incoming webhooks).
    notify_format: str = "json"
    # ADR-52: glob -> assignee for new review tickets; 0 days = never escalate.
    ownership: dict[str, str] = field(default_factory=dict)
    review_escalate_after_days: int = 0
    # Share (0-100) of ``review``-tier keys that get a review ticket; the rest are spot-check free.
    review_sample_percent: int = 100
    # ADR-55: how an accepted scan result reaches the catalogue: manual | request | auto.
    apply_mode: str = "manual"
    # Who may change source code: never | patch (report only) | agent-branch (branch-ready task).
    source_edits: str = "patch"
    decisions_in: str = "state"  # state | code (ADR-106)
    # ADR-104: place glob -> auto | request | review | never; "" is the default for unmatched places.
    places: dict = field(default_factory=dict)
    places_default: str = "auto"
    target_branch: str = "l10n/auto"  # bot branch for target-locale files (two-lane workflow)
    # Named score-routing workflows (W-10). Keys are names; values are normalised (ADR-62):
    # high/low, rules, max_improve_loops, notify, locales.
    workflows: dict = field(default_factory=dict)
    # Anthropic and DeepL stay off until the operator opts in (ADR-33).
    allow_cloud: bool = False
    delivery_require: str = "none"  # C-007: none | verified | reviewed
    local_only: bool = False  # C-023: hard-block cloud providers and off-machine endpoints
    tasks_only: bool = False  # C-029: translators edit only keys a task assigns to them

    # Per-locale provider kind override (e.g. ar = "anthropic"). Empty → project provider.
    locale_providers: dict[str, str] = field(default_factory=dict)

    config_path: Path | None = None

    # ---- helpers -----------------------------------------------------------

    def quality_threshold_for(self, locale: str) -> float:
        """Back-translation / heuristic cut for one locale (override, else the global)."""
        return self.quality_thresholds.get(locale, self.quality_threshold)

    def model_for(self, locale: str) -> str:
        """Per-locale model, falling back to the roster default."""
        if (
            locale and self.bridge_mode != "none" and self.bridge_model
            and locale == self.bridge_locale
        ):
            return self.bridge_model
        role = self.roles.get(locale)
        if role and role.primary:
            return role.primary
        if self.models.get(locale):
            return self.models[locale]
        if self.models.get("default"):
            return self.models["default"]
        configured = {model for key, model in self.models.items() if key != "default" and model}
        if len(configured) == 1:
            return next(iter(configured))
        if len(configured) > 1:
            raise ValueError(
                "multiple locale models are configured without [locales.models].default; "
                "set a default so GPU jobs can pin one model"
            )
        return "llama3.2"

    def role_for(self, locale: str) -> LocaleRole:
        return self.roles.get(locale) or LocaleRole()

    def secondary_model_for(self, locale: str) -> str | None:
        role = self.roles.get(locale)
        if role and role.secondary:
            return role.secondary
        return None

    def judge_model_for(self, locale: str = "") -> str | None:
        """Locale role judge, else ``[quality] judge_model``."""
        if locale:
            role = self.roles.get(locale)
            if role and role.judge:
                return role.judge
        model = self.judge_model
        if isinstance(model, str) and model.strip():
            return model.strip()
        return None

    def apply_model_override(self, model: str) -> None:
        """Force one translator tag for CLI/ops ``--model`` (disables dual-pass)."""
        self.models["default"] = model
        for locale in list(self.models):
            if locale != "default":
                self.models[locale] = model
        for locale, role in list(self.roles.items()):
            self.roles[locale] = LocaleRole(
                primary=model,
                secondary=None,
                judge=role.judge,
                prefer_secondary=False,
            )

    def is_frozen(self, locale: str) -> bool:
        return locale in self.frozen

    def is_asap(self, locale: str) -> bool:
        return locale in self.asap

    def order_locales(self, locales: list[str]) -> list[str]:
        """Pivot-safe order with ASAP preferred among ready locales (ADR-47)."""
        ordered: list[str] = []
        remaining = list(locales)
        asap = set(self.asap)
        while remaining:
            ready = [
                loc for loc in remaining
                if self.pivot_for(loc) not in remaining or self.pivot_for(loc) == loc
            ]
            if not ready:
                ordered.extend(remaining)
                break
            ready_asap = [loc for loc in ready if loc in asap]
            pick = ready_asap[0] if ready_asap else ready[0]
            ordered.append(pick)
            remaining.remove(pick)
        return ordered

    def active_targets(self) -> list[str]:
        """Targets that participate in default LLM sweeps (excludes ``frozen``)."""
        frozen = set(self.frozen)
        active = [loc for loc in self.targets if loc not in frozen]
        return self.order_locales(active)

    def resolve_locales(self, locales: list[str] | None) -> list[str]:
        """Work set for a run: explicit list as-is (ordered), else :meth:`active_targets`."""
        if locales is not None:
            return self.order_locales(list(locales))
        return self.active_targets()

    def provider_entry_for(self, locale: str) -> NamedProvider:
        """Named provider for a locale (ADR-47). Kind-string overrides still work."""
        registry = self.providers or {}
        default = registry.get("default") or _named_from_provider(self.provider)
        ref = (self.locale_providers.get(locale) or "").strip()
        if not ref:
            return default
        if ref in registry:
            return registry[ref]
        # Legacy: value is a provider kind, not an id.
        return NamedProvider(
            id=ref,
            name=ref,
            kind=ref,
            url=default.url,
            keep_alive=default.keep_alive,
            options=dict(default.options or {}),
            timeout_batch_s=default.timeout_batch_s,
            timeout_single_s=default.timeout_single_s,
            timeout_shorten_s=default.timeout_shorten_s,
            model_path=default.model_path,
        )

    def provider_config_for(self, locale: str) -> ProviderConfig:
        """ProviderConfig used by ``build_provider`` for one locale."""
        return self.provider_entry_for(locale).as_provider_config()

    def provider_kind_for(self, locale: str) -> str:
        """Provider kind for a locale, falling back to the project default."""
        return self.provider_entry_for(locale).kind or self.provider.kind or "ollama"

    def prompt_family_for(self, locale: str | None = None) -> str:
        """Prompt instruction family for a locale (``chat`` or ``mt_chat``)."""
        from ..pipeline.prompts import PROMPT_FAMILIES, normalize_family

        if locale:
            override = self.locale_prompt_families.get(locale)
            if override:
                return normalize_family(override)
        family = self.prompt_family if self.prompt_family in PROMPT_FAMILIES else "chat"
        return normalize_family(family)

    def style_for(self, locale: str, model: str = "") -> tuple[str, str]:
        """Register and prompt notes for one locale (and model).

        Notes are ``<locale notes>\n<project/model lines>``; the first line is
        the locale note (may be empty). Missing table uses the global register.
        """
        reg, notes = self.locale_styles.get(locale, ("", ""))
        extras = self.prompt_extras_for(locale, model)
        if extras:
            notes = f"{notes}\n{extras}"
        eff = reg or self.register
        if reg or self.register_set:
            wording = _register_wording(locale, eff)
            if wording:
                notes = (notes + chr(10) + wording) if notes else wording
        return eff, notes

    def prompt_extras_for(self, locale: str, model: str = "", *, raw: bool = False) -> str:
        """Project description, audience and model variant lines (ADR-60)."""
        lines: list[str] = []
        if self.description:
            lines.append(f"Project description: {self.description}")
        if self.audience:
            lines.append(f"Target audience: {self.audience}")
        if self.tone:
            lines.append(f"Tone: {self.tone}")
        preset = STYLE_PRESETS.get(self.locale_style_presets.get(locale) or self.style_preset)
        if preset:
            lines.append(preset)
        variant = self.model_prompts.get(model) if model else None
        if variant and variant[0]:
            lines.append(f"Model guidance: {variant[0]}")
        text = "\n".join(lines)
        if text and not raw and self.localize_prompt_for(model):
            from ..pipeline.prompt_i18n import cached_translation

            text = cached_translation(self, locale, text) or text
        return text

    def localize_prompt_for(self, model: str = "") -> bool:
        if self.prompt_localize == "target":
            return True
        if self.prompt_localize == "per-model":
            variant = self.model_prompts.get(model) if model else None
            return bool(variant and variant[1])
        return False

    def pivot_for(self, locale: str) -> str | None:
        """Explicit pivot, else the bridge locale (ADR-60)."""
        explicit = self.pivots.get(locale)
        if explicit:
            return explicit
        if self.bridge_mode != "none" and self.bridge_locale not in ("", locale, self.source_locale):
            return self.bridge_locale
        return None

    def resolve(self, rel: str | Path | None) -> Path | None:
        if rel is None:
            return None
        p = Path(rel)
        return p if p.is_absolute() else (self.root / p)

    def is_skipped(self, namespace: str, key: str, source: str | None = None) -> bool:
        """True when this key must never be translated.

        ``skip_keys`` matches one key in any namespace. ``skip_namespaces``
        matches that namespace and every child (``admin`` skips ``admin/users``).
        An explicit ``--namespace`` does not override this.
        """
        if key in self.skip_keys:
            return True
        if self.places and self.place_policy(namespace, key) == "never":
            return True
        if self.exclude_keys:
            from ..core.keyglob import key_glob_matches

            if any(key_glob_matches(g, namespace, key) for g in self.exclude_keys):
                return True
        if isinstance(source, str) and source and self.exclude_source and any(r.search(source) for r in self.exclude_source):
            return True
        ns = (namespace or "").replace("\\", "/").strip("/")
        for raw in self.skip_namespaces:
            skip = str(raw).replace("\\", "/").strip("/")
            if not skip:
                continue
            if ns == skip or ns.startswith(skip + "/"):
                return True
        return False

    def is_request_only(self, namespace: str, key: str = "") -> bool:
        """ADR-104 ``request`` place: bulk runs leave it alone, an explicit key list still works."""
        return bool(self.places) and self.place_policy(namespace, key) == "request"

    def place_policy(self, namespace: str, key: str = "") -> str:
        """ADR-104 policy for a place. ``ns-glob`` or ``ns-glob:key-glob``; the longest pattern wins."""
        from fnmatch import fnmatchcase

        ns = (namespace or "").replace("\\", "/").strip("/")
        best, best_len = self.places_default, -1
        for pattern, policy in self.places.items():
            ns_glob, _, key_glob = pattern.partition(":")
            if not fnmatchcase(ns, ns_glob.strip("/")):
                continue
            if key_glob and not (key and fnmatchcase(key, key_glob)):
                continue
            if len(pattern) > best_len:
                best, best_len = policy, len(pattern)
        return best

    def namespaces_for(self, catalog, override: str | None = None) -> list[str]:
        """Resolve the effective namespace set in one place."""
        if override is not None:
            return [override]
        if isinstance(self.namespaces, list) and self.namespaces:
            return sorted(self.namespaces)
        return catalog.namespaces()

    def data_root(self) -> Path:
        """Base directory for engine sidecars (ADR-112)."""
        if self.data_home == "project":
            return self.root
        from .registry import registry_home

        return registry_home() / "data" / self.name

    def state_root(self) -> Path:
        return self.state_dir or (self.data_root() / ".llm-state")

    def history_root(self) -> Path:
        return self.history_dir or (self.data_root() / ".llm-history")

    def scores_root(self) -> Path:
        return self.scores_dir or (self.data_root() / ".llm-scores")

    def tm_root(self) -> Path:
        return self.tm_dir or (self.data_root() / ".llm-tm")

    def tm_shared_all(self) -> list[Path]:
        """Every read-only shared memory, in lookup order (ADR-95)."""
        return ([self.tm_shared] if self.tm_shared else []) + list(self.tm_shared_more)

    def open_tm(self):
        """The project TM with its shared read set and optional write target."""
        from ..catalog.tm import TranslationMemory

        return TranslationMemory(
            self.tm_root(), shared=self.tm_shared_all() or None, write_to=self.tm_write,
        )

    def review_root(self) -> Path:
        return self.data_root() / ".llm-review"

    def findings_path(self) -> Path:
        """Path to consumer visual findings JSONL (ADR-27)."""
        if self.visual_findings_path is not None:
            return Path(self.visual_findings_path)
        from ..catalog.visual_findings import default_findings_path

        return default_findings_path(self.context_dir, self.root)

    def budget_root(self) -> Path:
        return self.data_root() / ".llm-budget"

    def documents_state_root(self, doc_dir: Path | None = None) -> Path:
        """Per-locale document translation state (ADR-112)."""
        if self.documents_state_dir is not None:
            return self.documents_state_dir
        if self.data_home == "engine":
            return self.data_root() / "documents-state"
        base = doc_dir or self.documents_dir or (self.root / "content" / "legal")
        return Path(base) / ".state"

    def scan_out_root(self) -> Path | None:
        """Usage-hint output directory; ``None`` means scan has no default out dir."""
        if self.scan_out_dir is not None:
            return self.scan_out_dir
        if self.data_home == "engine":
            return self.data_root() / ".usage"
        return None

    def glossary_domains_for(
        self,
        namespace: str,
        *,
        key_domain: str | None = None,
    ) -> list[str] | None:
        """Domains to inject for one string. ``None`` → all (or single-file)."""
        names: list[str] = []
        if key_domain:
            names.append(key_domain)
        mapped = self.glossary_domains.get(namespace)
        if mapped:
            for d in mapped:
                if d not in names:
                    names.append(d)
        return names or None

    def glossary_cache(self):
        """Shared glossary loader used by validate, draft, import and bulk edits."""
        from .context import GlossaryCache

        return GlossaryCache(
            self.glossary_path,
            shared=list(getattr(self, "glossary_shared", []) or []),
            conflict=getattr(self, "glossary_conflict", "own"),
        )


from .config_load import load_config  # noqa: E402  — keep public API on this module


def discover_config(start: str | Path | None = None) -> Path:
    """Walk upward from ``start`` looking for a config file.

    This is the no-registry path -- the one CI and fresh clones use.
    """
    cur = Path(start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        probe = candidate / CONFIG_FILENAME
        if probe.exists():
            return probe
    raise ConfigError(
        f"no {CONFIG_FILENAME} found in {cur} or any parent directory. "
        "Run 'llm-localizator init' to create one."
    )


def __getattr__(name: str):
    """Lazy re-exports for helpers that live in ``config_load`` after the split."""
    if name == "_content_tiers":
        from .config_load import _content_tiers

        return _content_tiers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
