"""Ops layer ↔ CLI manifest parity.

Fails when an ``*Request`` field has no matching argparse dest on the command
(so the Operations UI / ``/api/commands`` cannot drive that ops input).
CLI-only presentation flags (``--format`` output style, ``--quiet``, …) are
allowed to exist without a Request field.
"""

from __future__ import annotations

from dataclasses import fields

from llm_localizator.cli.main import build_parser
from llm_localizator.ops import build_commands_manifest
from llm_localizator.ops.types import (
    AdoptRequest,
    AgentBacklogRequest,
    AgentHardcodedRequest,
    BakeoffRequest,
    AnalyticsRequest,
    DocumentsRequest,
    EstimateCostRequest,
    ExportRequest,
    ImportRequest,
    ImproveRequest,
    IngestVisualRequest,
    InitRequest,
    MetricsRequest,
    SuggestRequest,
    FlagSourceRequest,
    SourceReviewQueueRequest,
    ApplyRequest,
    ApplyNearRequest,
    DraftRequest,
    FindReplaceRequest,
    TaskRequest,
    DiscussRequest,
    BulkClearRequest,
    PlaceholderRenameRequest,
    PatchRequest,
    ScanDecideRequest,
    MigrateRequest,
    RescoreRequest,
    ReviewRequest,
    ScanRequest,
    StatusRequest,
    SyncRequest,
    TranslateRequest,
    ValidateRequest,
)

# command name (CLI / manifest) → Request dataclass
_COMMAND_REQUESTS = {
    "validate": ValidateRequest,
    "status": StatusRequest,
    "sync": SyncRequest,
    "translate": TranslateRequest,
    "run-translate": TranslateRequest,
    "improve": ImproveRequest,
    "run-improve": ImproveRequest,
    "review": ReviewRequest,
    "run-review": ReviewRequest,
    "rescore": RescoreRequest,
    "run-rescore": RescoreRequest,
    "bakeoff": BakeoffRequest,
    "run-bakeoff": BakeoffRequest,
    "export": ExportRequest,
    "import": ImportRequest,
    "scan": ScanRequest,
    "migrate-state": MigrateRequest,
    "adopt": AdoptRequest,
    "agent-backlog": AgentBacklogRequest,
    "agent-hardcoded": AgentHardcodedRequest,
    "run-agent-hardcoded": AgentHardcodedRequest,
    "init": InitRequest,
    "documents": DocumentsRequest,
    "run-documents": DocumentsRequest,
    "estimate-cost": EstimateCostRequest,
    "ingest-visual": IngestVisualRequest,
    "analytics": AnalyticsRequest,
    "metrics": MetricsRequest,
    "suggest": SuggestRequest,
    "draft": DraftRequest,
    "task": TaskRequest,
    "discuss": DiscussRequest,
    "flag-source": FlagSourceRequest,
    "source-review-queue": SourceReviewQueueRequest,
    "bulk-clear": BulkClearRequest,
    "apply-near": ApplyNearRequest,
    "find-replace": FindReplaceRequest,
    "rename-placeholder": PlaceholderRenameRequest,
    "scan-decide": ScanDecideRequest,
    "patch": PatchRequest,
    "apply": ApplyRequest,
}

# Request field → acceptable argparse dest names
_FIELD_ALIASES = {
    "fmt": {"fmt", "format", "catalog_format"},
    "catalog_format": {"catalog_format", "format"},
    "catalog_path": {"catalog_path", "path"},
    "text": {"text", "file", "csv", "xliff", "data"},
    "submit": {"submit"},  # web/ops-only; submit_* may appear on sibling cmds
    "namespaces": {"namespace"},  # web multi-select; CLI stays singular
    "check_script": {"semantic"},
    "check_digraphs": {"semantic"},
    "check_length": {"check_expansion", "semantic"},
}

# Web-only request fields (no dedicated CLI flag; driven by aliases above)
_WEB_ONLY = frozenset({
    "submit", "inline", "text", "confirm", "namespaces", "files",
    "check_script", "check_digraphs", "check_length",
    # Web Ops validate summary payload (CLI prints findings; no twin flags).
    "detail", "findings_limit",
})


def test_ops_request_fields_covered_by_manifest() -> None:
    manifest = build_commands_manifest(build_parser())["commands"]
    missing: list[str] = []
    for cmd, req_cls in _COMMAND_REQUESTS.items():
        if cmd not in manifest:
            # run-* aliases share flags with the base name when both exist
            if cmd.startswith("run-") and cmd[4:] in manifest:
                continue
            missing.append(f"{cmd}: not in manifest")
            continue
        dests = {f["name"] for f in manifest[cmd]["fields"]}
        for f in fields(req_cls):
            if f.name in _WEB_ONLY:
                aliases = _FIELD_ALIASES.get(f.name, set())
                if aliases and not aliases.isdisjoint(dests):
                    continue
                if f.name in ("submit", "inline", "text", "confirm", "namespaces", "files",
                              "check_script", "check_digraphs", "check_length",
                              "detail", "findings_limit"):
                    continue
            aliases = _FIELD_ALIASES.get(f.name, {f.name})
            if aliases.isdisjoint(dests):
                missing.append(f"{cmd}.{f.name} not in manifest dests {sorted(dests)}")
    assert not missing, "ops Request fields missing from CLI manifest:\n" + "\n".join(missing)


def test_ops_parity_core_commands_present() -> None:
    manifest = build_commands_manifest(build_parser())["commands"]
    for cmd in ("validate", "status", "sync", "translate", "improve", "review",
                "export", "import", "scan", "migrate-state", "adopt",
                "agent-backlog", "agent-hardcoded", "init", "documents"):
        assert cmd in manifest, f"missing command {cmd}"
