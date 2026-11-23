"""Shared request/response types for CLI and web operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def parse_csv_list(value) -> list[str] | None:
    """Split a comma string or a list of comma strings. Empty becomes None."""
    if value is None or value == "" or value == []:
        return None
    raw = [value] if isinstance(value, str) else list(value)
    items: list[str] = []
    for part in raw:
        items.extend(piece.strip() for piece in str(part).split(",") if piece.strip())
    return items or None


def _coerce(annotation: str, value, default):
    """A web/CLI value as the request field's declared type (annotations are strings here)."""
    kind = annotation.replace(" ", "")
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind.startswith("int"):
        if value in (None, ""):
            return default if kind == "int" else None
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if kind.startswith("float"):
        if value in (None, ""):
            return default if kind == "float" else None
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if kind.startswith("list[str]"):
        return parse_csv_list(value)
    if kind == "str|None":
        return (str(value).strip() or None) if value is not None else None
    if kind == "str":
        return default if value in (None, "") else str(value)
    return value


def request_from_mapping(cls, mapping: dict, **overrides):
    """Build an ops request dataclass from a web body or ``vars(args)`` (M3, audit ops #21).

    Only the request's own fields are read; each value is coerced to the field's declared type (booleans from
    ``"true"``, ints from strings, comma lists split), so CLI and web handlers stop hand-copying keys. Keyword
    *overrides* win over the mapping.
    """
    from dataclasses import MISSING, fields

    kwargs = {}
    for f in fields(cls):
        default = f.default if f.default is not MISSING else None
        if f.name in overrides:
            kwargs[f.name] = overrides[f.name]
        elif f.name in mapping:
            kwargs[f.name] = _coerce(str(f.type), mapping[f.name], default)
    return cls(**kwargs)


@dataclass
class OpResult:
    ok: bool
    exit_code: int
    command: str
    summary: str
    lines: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidateRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    strict: bool = False
    check_expansion: bool = False
    check_length: bool = False
    check_script: bool = False
    check_digraphs: bool = False
    check_layout: bool = False
    check_numbers: bool = False
    diff_only: bool = False
    semantic: bool = False
    write_flags: bool = False
    flag_checks: str = "V13"
    diff_scope: list[str] | None = None
    unused: bool = False
    # Web default is summary (counts only). "full" keeps findings; findings_limit caps them.
    detail: str = "full"
    findings_limit: int | None = None


@dataclass
class QualityRequest:
    """Quality report for a project, or for files named on the command line (C-016)."""
    root: str | None = None
    fmt: str | None = None
    path_template: str | None = None
    source: str | None = None
    targets: list[str] | None = None
    locales: list[str] | None = None
    score: bool = False
    model: str | None = None
    limit: int = 50


@dataclass
class IngestVisualRequest:
    path: str | None = None
    dry_run: bool = False


@dataclass
class StatusRequest:
    missing: bool = False
    collection: str | None = None
    by_screen: bool = False


@dataclass
class ConcordanceRequest:
    locale: str = ""
    query: str = ""
    source: bool = True
    target: bool = True
    limit: int = 20
    namespace: str | None = None
    key: str | None = None
    mode: str = "substring"  # "substring" or "fuzzy" (word overlap, C-037)
    min_similarity: float = 0.55


@dataclass
class TmExportRequest:
    locale: str = ""
    path: str | None = None


@dataclass
class TmImportRequest:
    locale: str = ""
    path: str | None = None
    tmx: str | None = None
    conflict: str = "skip"
    dry_run: bool = False


@dataclass
class SyncRequest:
    locales: list[str] | None = None
    dry_run: bool = False
    no_translate: bool = False
    submit_translate: bool = False
    strict_branch: bool = False
    diff: bool = False
    exit_nonzero: bool = False


@dataclass
class TranslateRequest:
    locales: list[str] | None = None
    collection: str | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    model: str | None = None
    batch_size: int = 10
    force: bool = False
    flagged: bool = False
    dry_run: bool = False
    multi_sample: int | None = None
    submit: bool = False
    keys: list[str] | None = None
    pre_translate: bool = False
    tags: list[str] | None = None
    # Run in this process even when taskqueue is available (the ``run-`` aliases).
    inline: bool = False
    # ICU residual lane: only keys that need span decomposition (or only plain).
    icu_only: bool = False
    plain_only: bool = False
    # "layout" / "layout:N": translate a small layout-check sample (frozen zh/ar).
    sample: str | None = None
    # Only keys whose target value is absent or empty (never overwrites an existing translation).
    only_missing: bool = False
    # Cloud: one synchronous request per batch (full price, no Message Batches wait).
    sync: bool = False


@dataclass
class BakeoffRequest:
    """Model bakeoff (ADR-12): evidence for a model decision. Local Ollama only."""

    locales: list[str] | None = None
    models: list[str] | None = None
    limit: int = 30
    corpus: str | None = None
    out: str | None = None
    family: str | None = None
    matrix: bool = False
    force_cells: bool = False
    dry_run: bool = False
    submit: bool = False
    inline: bool = False
    propose_config: bool = False


@dataclass
class EstimateCostRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    keys: list[str] | None = None
    batch_size: int = 10
    collection: str | None = None
    #: ``translate`` (due strings) or ``review`` / ``rescore`` (translated strings judged by the project model; M6).
    purpose: str = "translate"


@dataclass
class ImproveRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    model: str | None = None
    limit: int | None = None
    dry_run: bool = False
    submit: bool = False
    include_rejected: bool = False
    keys: list[str] | None = None
    tags: list[str] | None = None
    inline: bool = False


@dataclass
class ReviewRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    model: str | None = None
    batch_size: int = 5
    dry_run: bool = False
    submit: bool = False
    keys: list[str] | None = None
    inline: bool = False


@dataclass
class ExportRequest:
    locales: list[str] | None = None
    collection: str | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    fmt: str = "csv"
    only: str = "all"
    layout: str = "single"
    screenshots: bool = False
    file_count: int = 1
    approved_only: bool = False
    xliff_version: str = "1.2"
    bom: bool = False


@dataclass
class ImportRequest:
    text: str = ""
    locales: list[str] | None = None
    fmt: str = "csv"
    dry_run: bool = False
    model: str = "import"
    files: list | None = None


@dataclass
class RescoreRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    model: str | None = None
    dry_run: bool = False
    submit: bool = False
    stale_only: bool = False
    below_score: float | None = None
    keys: list[str] | None = None
    inline: bool = False


@dataclass
class HardKeysRequest:
    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    threshold: float = 0.7
    min_locales: int = 4
    dry_run: bool = False


@dataclass
class AdoptRequest:
    """Stamp catalogue-present keys that lack state (ADR-19 agent provenance)."""

    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    dry_run: bool = False
    limit: int | None = None
    model: str = "cursor-agent"
    provider: str = "agent"
    verified_by: str = "cursor-agent"


@dataclass
class AgentHardcodedRequest:
    """Paste-ready report of hardcoded source strings. Writes nothing."""

    adapter: str | None = None
    limit: int | None = None
    fmt: str = "prompt"
    llm: bool = False
    dry_run: bool = False
    submit: bool = False
    catalogue_audit: bool = True
    refresh: bool = False
    show_ignored: bool = False
    show_low: bool = False  # default report is high+medium only
    split: str | None = None  # None = one document; "auto" = agent-sized parts (ADR-105)
    budget_tokens: int = 15000
    max_hits: int = 150
    out_dir: str | None = None


@dataclass
class ScanDecideRequest:
    """Accept, ignore or reset scan results (ADR-55); ``status`` only summarises."""

    action: str = "status"  # accept | ignore | reset | status
    kind: str = "hit"  # hit | collection
    ids: list[str] | None = None
    confidence: str | None = None
    file: str | None = None
    all_pending: bool = False
    key: str | None = None
    note: str = ""
    by: str = ""
    adapter: str | None = None
    limit: int | None = None


@dataclass
class PatchRequest:
    """Generate a patch changeset (no writes to project)."""

    adapter: str | None = None
    limit: int | None = None
    out_dir: str | None = None
    fmt: str = "json"


@dataclass
class ApplyRequest:
    """Apply catalogue additions from hardcoded-string scan (writes catalogue)."""

    adapter: str | None = None
    limit: int | None = None
    dry_run: bool = False
    confirm: bool = False
    enqueue_translate: bool = True


@dataclass
class AgentBacklogRequest:
    """Prompt/JSON backlog of keys an agent should still translate."""

    locales: list[str] | None = None
    namespace: str | None = None
    namespaces: list[str] | None = None
    reasons: list[str] | None = None
    limit: int | None = None
    fmt: str = "prompt"
    include_existing: bool = False
    split: str | None = None  # locale | namespace: write one part file per group
    out_dir: str | None = None
    budget_tokens: int = 15000


def resolve_namespaces(
    namespace: str | None,
    namespaces: list[str] | None,
) -> list[str] | None:
    """Prefer multi-select ``namespaces``; fall back to singular ``namespace``."""
    if namespaces:
        return list(namespaces)
    if namespace:
        return [namespace]
    return None


def namespace_override_sets(namespaces: list[str] | None) -> list[dict[str, str]]:
    """One override so a locale job can carry every namespace.

    ``None`` / empty → one empty dict (all namespaces, intentional).
    Non-empty → one ``{"--namespace": "a,b"}`` so submit is one task per
    locale, not one task per namespace. The worker splits on commas.
    """
    if not namespaces:
        return [{}]
    return [{"--namespace": ",".join(namespaces)}]


@dataclass
class ScanRequest:
    adapter: str | None = None
    out_dir: str | None = None
    no_write: bool = False
    strict: bool = False
    lint_directives: bool = False
    surface: str | None = None  # comma-separated [scan.surfaces] names; others are left out


@dataclass
class MigrateRequest:
    locales: list[str] | None = None
    dry_run: bool = False
    stamp_provider: bool = False


@dataclass
class AnalyticsRequest:
    since: str | None = None
    run_command: str | None = None
    locale: str | None = None
    locales: list[str] | None = None
    model: str | None = None
    last: int | None = None
    fmt: str = "text"


@dataclass
class SuggestRequest:
    locale: str = ""
    namespace: str = ""
    key: str = ""
    explain: bool = False
    alternatives: bool = False
    ambiguity: bool = False


@dataclass
class DraftRequest:
    action: str = "list"
    locale: str = ""
    namespace: str = ""
    key: str = ""
    keys: list[str] | None = None
    by: str = ""
    mode: str = ""  # "" = suggest, "minimal-edit" = edit the old translation (C-041)
    confirm: bool = False  # accept only: overwrite a human-edited translation (R-009, ADR-103)


@dataclass
class OpenPrRequest:
    action: str = "plan"  # plan | open | status (C-015, ADR-101)
    branch: str = ""
    confirm: bool = False


@dataclass
class ScreenshotLinkRequest:
    action: str = "list"  # list | link | unlink (C-012, ADR-102)
    file: str = ""
    namespace: str = ""
    key: str = ""
    region: object = None
    note: str = ""
    link: str = ""
    by: str = ""


@dataclass
class TaskRequest:
    action: str = "list"
    id: str = ""
    name: str = ""
    namespace: str | None = None
    keys: list[str] | None = None
    assign: list[str] | None = None
    due: str = ""
    unverified: bool = False
    assignee: str = ""
    by: str = ""


@dataclass
class DiscussRequest:
    action: str = "list"
    namespace: str = ""
    key: str = ""
    text: str = ""
    mention: str = ""
    open_only: bool = False
    by: str = ""


@dataclass
class FlagSourceRequest:
    namespace: str = ""
    key: str = ""
    note: str = ""


@dataclass
class SourceReviewQueueRequest:
    pass


@dataclass
class BulkClearRequest:
    locale: str | None = None
    locales: list[str] | None = None
    namespace: str | None = None
    stale_to_source: bool = False
    purge_machine_older_than: int | None = None
    invalid: bool = False
    latin_leftover: bool = False
    dry_run: bool = False
    confirm: bool = False


@dataclass
class ApplyNearRequest:
    locale: str = ""
    namespace: str = ""
    key: str = ""
    min_similarity: float = 0.85
    keys: list[str] | None = None
    dry_run: bool = False
    confirm: bool = False


@dataclass
class FindReplaceRequest:
    locale: str = ""
    find: str = ""
    replace: str = ""
    namespace: str | None = None
    case_sensitive: bool = False
    keys: list[str] | None = None
    dry_run: bool = False
    confirm: bool = False


@dataclass
class PlaceholderRenameRequest:
    old: str = ""
    new: str = ""
    namespace: str | None = None
    keys: list[str] | None = None
    dry_run: bool = False
    confirm: bool = False


@dataclass
class MetricsRequest:
    by: str | None = None
    since: str | None = None
    locale: str | None = None
    locales: list[str] | None = None
    fmt: str = "text"
    why_low: bool = False
    threshold: float | None = None


@dataclass
class InitRequest:
    directory: str | None = None
    name: str | None = None
    source_locale: str = "en"
    catalog_format: str | None = None
    catalog_path: str | None = None
    taskqueue: bool = False
    no_register: bool = False
    force: bool = False
    targets: list[str] | None = None
    model: str | None = None
    domain: str | None = None
    provider: str | None = None
    approach: str | None = None


@dataclass
class VerifyRequest:
    """Run the verification workflow on a disposable copy of a project."""

    path: str = ""
    profile: str = "quick"  # quick | standard | deep
    locales: str | None = None  # named locale set (deep profile)
    out: str | None = None
    resume: str | None = None
    only: list[str] | None = None
    skip: list[str] | None = None


@dataclass
class GuideRequest:
    directory: str | None = None
    smoke_test: bool = False
    skip_provider: bool = False
    yes: bool = False
    # Web dashboard polls guide often; full validate would re-walk every catalogue.
    skip_validate: bool = False


@dataclass
class DocumentsRequest:
    locales: list[str] | None = None
    doc: str | None = None
    doc_dir: str | None = None
    model: str | None = None
    dry_run: bool = False
    submit: bool = False
    inline: bool = False  # execute locally instead of enqueue / preview-only


@dataclass
class GlossaryExportRequest:
    format: str = "csv"
    file: str | None = None


@dataclass
class GlossaryImportRequest:
    format: str = ""
    file: str | None = None
    text: str | None = None
    conflict: str = "skip"
    dry_run: bool = False


@dataclass
class PseudoRequest:
    locale: str = "en-XA"
    length_factor: float = 1.4
    style: str = ""  # accents | xxxx; empty → infer from locale (en-XX → xxxx)
