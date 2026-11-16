"""The validation run: every check, over a whole project, with no LLM.

This is the piece that makes the tool useful on day one and in CI. It needs no
Ollama, no GPU, and no network -- only the project's message files and, if it
has them, a glossary and context notes.

Checks, and where their logic lives:

===  ==============================  ========  ===========================
ID   Check                           Severity  Implementation
===  ==============================  ========  ===========================
V01  missing key in target           error     here
V02  ICU placeholder mismatch        error     core.validate
V03  plural category incomplete      error     core.validate
V04  glossary violation (blocking)   error     core.validate
V05  output shape (newlines/length)  error     core.validate
V06  untranslated (same as source)   warning   here
V07  stale (source hash changed)     warning   catalog.state
V08  structurally stale              warning   catalog.state
V09  maxChars budget exceeded        warning   core.validate
V10  naive plural (counted noun)     warning   here
V11  counted noun with no context    warning   here
V12  orphan key absent from source   warning   here
V13  approved glossary term absent   warning   core.validate
V14  expansion band (opt-in)         warning   core.validate
V16  source message syntax           error     core.standards
V17  whitespace parity (semantic)    warning   core.validate
V18  duplicate source text           warning   core.source_quality
V19  placeholder, no context note    warning   core.source_quality
V20  raw HTML in a plain message     warning   core.source_quality
V21  unexpected script (semantic)     warning   core.validate
V22  maxChars (semantic detail)       warning   core.validate
V23  word-count band (semantic)       warning   core.validate
V25  suspicious digraphs (semantic)   warning   core.quality
V26  TM conflict (live ≠ high-score)  warning   catalog.tm
V27  HTML tag integrity               error     core.validate
V28  screenshot layout QA (opt-in)    warning   core.layout_qa
V30  same-source coherence (semantic) warning   catalog.coherence_index
V31  similar-source coherence         warning   catalog.coherence_index
V46  prompt leak (tiny source grew)  error     core.validate
V47  ICU kind / select keys changed  error     core.validate
V48  term rendered inconsistently    warning   core.term_consistency
===  ==============================  ========  ===========================

Two checks are deliberately advisory rather than blocking, both because they are
heuristics that measured badly against a real catalogue (ADR-8): V13 compares
the approved glossary translation by exact substring and so cannot see inflected
forms, and V14 compares character counts against bands authored for rendered
width. V14 is off unless ``--check-expansion`` is passed.

Hardcoded-source-string detection is check V15 and lives in ``scan`` -- it reads
source code rather than catalogues. V26 flags when the live translation differs
from a high-score translation-memory exact hit for the same source+context.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..catalog import Catalog, StateStore, is_structurally_stale, needs_translation
from ..catalog.state import state_key
from ..catalog.tm import TranslationMemory
from ..core.dnt_spans import check_dnt_spans
from ..core.quality import check_number_format
from ..core.validate import (
    check_expansion_band,
    check_locale_grammar,
    check_locale_typography,
    check_register,
    check_max_chars,
    classify_failure,
    glossary_violations,
    validate_translation,
    validate_translation_detailed,
)
from ..core.icu import extract_placeholders, extract_plural_categories
from ..core.standards import get_standard
from ..projects import ContextNotes, ProjectConfig, GlossaryCache
from ..catalog.io import read_json

__all__ = ["Finding", "ValidationReport", "run_validation", "SEVERITY_ERROR", "SEVERITY_WARNING",
           "SEMANTIC_FULL_CATALOG_MAX_KEYS", "SEMANTIC_COHERENCE_MAX_KEYS"]

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# Refuse ``--semantic`` on an unscoped full catalogue above this key count (P-04).
SEMANTIC_FULL_CATALOG_MAX_KEYS = 500
# Skip V30/V31 coherence within a namespace above this size (O(n²)).
SEMANTIC_COHERENCE_MAX_KEYS = 500

# A bare {n} adjacent to a word is very likely a counted noun that should be an
# ICU plural. Deliberately narrow: "Level {n}" and "Step {n} of {total}" are
# legitimate and must not fire.
_NAIVE_PLURAL_RE = re.compile(r"\{(\w+)\}\s+([A-Za-z]+s)\b")
_COUNTED_HINT_RE = re.compile(r"\{n\}|\{count\}|\{total\}")


class _CleanKeyCache:
    """Per-locale record of keys that validated clean, for ``--diff-only``.

    Lives beside the state files; the frozen state format (ADR-7) is untouched.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory) / ".validate-cache"
        self._data: dict[str, dict[str, str]] = {}

    def get(self, locale: str) -> dict[str, str]:
        if locale not in self._data:
            try:
                loaded = read_json(self.dir / f"{locale}.json")
            except (OSError, ValueError):
                loaded = {}
            self._data[locale] = loaded if isinstance(loaded, dict) else {}
        return self._data[locale]

    def save(self) -> None:
        from ..catalog.io import atomic_write_text

        self.dir.mkdir(parents=True, exist_ok=True)
        for locale, data in self._data.items():
            atomic_write_text(
                self.dir / f"{locale}.json",
                json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
            )


def _key_fingerprint(
    src, translated, glossary, notes, ns: str, key: str, flags_sig: str, entry,
) -> str:
    """Everything that can change a key's findings, hashed."""
    entry = entry or {}
    payload = json.dumps([
        src, translated, glossary, flags_sig,
        notes.note(ns, key), notes.screen(ns, key), notes.max_chars(ns, key),
        notes.full_key(ns, key), notes.domain(ns, key),
        entry.get("src_sha"), entry.get("structure_sig"), entry.get("context_sha"),
    ], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    locale: str
    namespace: str
    key: str
    message: str
    file: Path | None = None

    def location(self) -> str:
        ns = f"{self.namespace}." if self.namespace else ""
        return f"{self.locale}/{ns}{self.key}"


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    checked_keys: int = 0
    checked_locales: list[str] = field(default_factory=list)
    scope_error: str | None = None
    skipped_unchanged: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    def exit_code(self, strict: bool = False) -> int:
        """0 clean, 1 errors, 2 warnings only. ``strict`` promotes 2 to 1."""
        if self.scope_error or self.errors:
            return 1
        if self.warnings:
            return 1 if strict else 2
        return 0


def _namespace_key_count(cfg: ProjectConfig, catalog: Catalog, ns: str) -> int:
    source = catalog.load(cfg.source_locale, ns)
    return len([k for k, v in source.items() if not cfg.is_skipped(ns, k, v if isinstance(v, str) else None)])


def _semantic_scope_error(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    namespace: str | None,
    namespaces: list[str] | None,
    check_semantic: bool,
) -> str | None:
    """Return an error message when ``--semantic`` scope is unsafe at scale."""
    if not check_semantic:
        return None
    if namespace or namespaces:
        return None
    ns_list = cfg.namespaces_for(catalog)
    total = sum(_namespace_key_count(cfg, catalog, ns) for ns in ns_list)
    if total > SEMANTIC_FULL_CATALOG_MAX_KEYS:
        return (
            f"semantic validation refused: {total} source keys exceed "
            f"{SEMANTIC_FULL_CATALOG_MAX_KEYS} without --namespace "
            f"(V30/V31 coherence is O(n²) per namespace). "
            f"Re-run with --namespace <name> or validate subsets."
        )
    return None


def _namespaces(
    cfg: ProjectConfig,
    catalog: Catalog,
    only: str | None,
    namespaces: list[str] | None = None,
) -> list[str]:
    if namespaces:
        return list(namespaces)
    return cfg.namespaces_for(catalog, only)


_PLURAL_SUFFIX = re.compile(r"_(zero|one|two|few|many|other)$")


def _structure_drift(src_keys: set[str], tgt_keys: set[str]) -> str | None:
    """V98: more than 10% of target keys do not exist in the source.

    A flattened or re-nested target (``a_b`` instead of ``a.b``) shows up here, because nested
    JSON keys are dotted paths. Plural suffix variants are not counted as orphans.
    """
    base = {_PLURAL_SUFFIX.sub("", key) for key in src_keys}
    orphans = [key for key in tgt_keys if _PLURAL_SUFFIX.sub("", key) not in base]
    if src_keys and len(orphans) / len(src_keys) > 0.10:
        return f"{len(orphans)} target key(s) do not exist in the source ({len(src_keys)} source keys)"
    return None


def _emit_term_spreads(report: ValidationReport, glossary: dict, term_rows: dict) -> None:
    """V48: keys that render a glossary term differently from the rest of the locale."""
    from ..core.term_consistency import term_spreads

    for locale, rows in term_rows.items():
        for spread in term_spreads(rows, glossary, locale):
            keep = spread.majority
            used = len(spread.by_rendering.get(keep, []))
            for rendering, labels in spread.outliers.items():
                for ns, key, path in labels:
                    report.findings.append(Finding(
                        "V48", SEVERITY_WARNING, locale, ns, key,
                        f"glossary term '{spread.term}' rendered '{rendering}' here; "
                        f"'{keep}' in {used} other key(s)", path,
                    ))


def run_validation(
    cfg: ProjectConfig,
    catalog: Catalog,
    *,
    locales: list[str] | None = None,
    namespace: str | None = None,
    namespaces: list[str] | None = None,
    only_keys: set[tuple[str, str]] | None = None,
    changed_files: set[Path] | None = None,
    check_expansion: bool = False,
    check_semantic: bool = False,
    check_script: bool = False,
    check_digraphs: bool = False,
    check_length_semantic: bool = False,
    check_layout: bool = False,
    check_numbers: bool = False,
    diff_only: bool = False,
) -> ValidationReport:
    """Run every catalogue check and return a report.

    ``changed_files`` implements ``--diff-scope``: when given, only namespaces
    whose source or target file appears in the set are examined.
    ``check_expansion`` enables the noisy V14 band check.
    ``check_semantic`` enables all advisory families (V17/V21-V25).
    Granular ``check_script`` / ``check_digraphs`` / ``check_length_semantic``
    enable subsets without the full semantic umbrella.
    ``check_layout`` runs ``core.layout_qa`` when a screenshot resolves (V28).
    ``diff_only`` skips keys that validated clean last time with identical
    inputs (text, context, state signatures, glossary, check flags). Keys with
    findings are always re-checked. Needs ``state_dir``; ignored without it.
    """
    from ..core.layout_qa import check_layout as layout_check
    from ..projects.screenshots import resolve_screenshot_path

    report = ValidationReport()
    scope_err = _semantic_scope_error(
        cfg, catalog,
        namespace=namespace, namespaces=namespaces, check_semantic=check_semantic,
    )
    if scope_err:
        report.scope_error = scope_err
        return report

    notes = ContextNotes(cfg.context_dir)
    state = StateStore(cfg.state_dir) if cfg.state_dir else None
    tm = cfg.open_tm()
    glossary_cache = GlossaryCache(
        cfg.glossary_path,
        shared=list(getattr(cfg, "glossary_shared", []) or []),
        conflict=getattr(cfg, "glossary_conflict", "own"),
    )

    targets = locales if locales is not None else cfg.targets
    report.checked_locales = list(targets)
    source_items: list[tuple[str, str, str]] = []
    # Every translated key per locale, for the cross-key term check (V48).
    term_rows: dict[str, list] = {}

    diff_cache = _CleanKeyCache(cfg.state_dir) if diff_only and cfg.state_dir else None
    flags_sig = json.dumps([
        check_expansion, check_semantic, check_script, check_digraphs,
        check_length_semantic, check_layout, check_numbers,
    ])

    want_script = check_semantic or check_script
    want_digraphs = check_semantic or check_digraphs
    want_length = check_semantic or check_length_semantic
    want_ws_fullkey = check_semantic  # V17/V22/V24 with umbrella only
    want_any_advisory = want_script or want_digraphs or want_length or want_ws_fullkey
    want_layout = check_layout

    for ns in _namespaces(cfg, catalog, namespace, namespaces):
        source = catalog.load(cfg.source_locale, ns)
        if not source:
            continue

        if changed_files is not None:
            touched = {catalog.path_for(loc, ns).resolve() for loc in [cfg.source_locale, *targets]}
            if not (touched & changed_files):
                continue

        # Source-side checks run once per key, independent of any target.
        standard = get_standard(cfg.catalog_standard)
        for key, src in source.items():
            if cfg.is_skipped(ns, key, src):
                continue
            if only_keys is not None and (ns, key) not in only_keys:
                continue
            report.checked_keys += 1
            if isinstance(src, str):
                source_items.append((ns, key, src))
            _check_source_quality(report, cfg, notes, ns, key, src, standard)

        for missing_key in standard.missing_plural_keys(source, cfg.source_locale):
            report.findings.append(Finding(
                "V03", SEVERITY_ERROR, cfg.source_locale, ns, missing_key,
                f"missing required plural key for {cfg.source_locale}",
            ))

        for locale in targets:
            target = catalog.load(locale, ns)
            path = catalog.path_for(locale, ns)

            # V99 — structure guard: target holds under half the source keys.
            # (Fully empty targets are already reported per key as V01.)
            tgt_keys = set(target.keys()) if target else set()
            src_keys = set(source.keys())
            if tgt_keys and len(tgt_keys) / len(src_keys) < 0.5:
                report.findings.append(Finding(
                    "V99", SEVERITY_WARNING, locale, ns, "",
                    f"target has only {len(tgt_keys)}/{len(src_keys)} source keys", path,
                ))
            elif tgt_keys:
                drift = _structure_drift(src_keys, tgt_keys)
                if drift:
                    report.findings.append(Finding(
                        "V98", SEVERITY_WARNING, locale, ns, "", drift, path,
                    ))

            # Hoist state once per locale (avoid per-key path.stat).
            state_entries = state.load(locale) if state is not None else {}

            for key, src in source.items():
                if cfg.is_skipped(ns, key, src):
                    continue
                if only_keys is not None and (ns, key) not in only_keys:
                    continue
                translated = target.get(key)

                if translated is None:
                    # Frozen locales are layout checks (zh, ar): a gap is expected, not a defect.
                    frozen = locale in (getattr(cfg, "frozen", None) or [])
                    report.findings.append(Finding(
                        "V01", SEVERITY_WARNING if frozen else SEVERITY_ERROR, locale, ns, key,
                        "missing from frozen layout locale" if frozen else "missing from target locale",
                        path,
                    ))
                    continue

                key_glossary = glossary_cache.get(
                    cfg.glossary_domains_for(
                        ns, key_domain=notes.domain(ns, key),
                    ),
                )
                term_rows.setdefault(locale, []).append(
                    ((ns, key, path), src, translated),
                )

                findings_before = len(report.findings)
                fingerprint = None
                sk = state_key(ns, key)
                entry = state_entries.get(sk) if state_entries is not None else None
                if diff_cache is not None:
                    fingerprint = _key_fingerprint(
                        src, translated, key_glossary, notes, ns, key, flags_sig,
                        entry,
                    )
                    if diff_cache.get(locale).get(sk) == fingerprint:
                        report.skipped_unchanged += 1
                        continue

                ok, reason = validate_translation(
                    src, translated, locale, key_glossary, standard=standard,
                    prompt_text=getattr(cfg, "domain", None) or None,
                )
                if not ok:
                    report.findings.append(Finding(
                        _classify(reason), SEVERITY_ERROR, locale, ns, key, reason, path,
                    ))

                # V13 -- advisory glossary issues, reported separately from the
                # blocking ones already covered by validate_translation.
                for issue in glossary_violations(src, translated, key_glossary, locale):
                    if not issue.blocking:
                        report.findings.append(Finding(
                            "V13", SEVERITY_WARNING, locale, ns, key, issue.message, path,
                        ))

                # V26 -- live text diverges from a high-score TM exact hit.
                context_parts = [notes.note(ns, key)]
                context = "; ".join(p for p in context_parts if p)
                tm_hit = tm.exact(locale, src, context=context)
                if (
                    tm_hit
                    and tm_hit.text.strip()
                    and tm_hit.text.strip() != translated.strip()
                    and (tm_hit.quality_score is None or tm_hit.quality_score >= 0.80)
                ):
                    report.findings.append(Finding(
                        "V26", SEVERITY_WARNING, locale, ns, key,
                        "translation differs from high-score TM exact match",
                        path,
                    ))

                if translated == src and src.strip():
                    if not entry or entry.get("status") != "intentional":
                        report.findings.append(Finding(
                            "V06", SEVERITY_WARNING, locale, ns, key,
                            "identical to source (untranslated?)", path,
                        ))

                budget = check_max_chars(translated, notes.max_chars(ns, key))
                if budget:
                    report.findings.append(Finding(
                        "V09", SEVERITY_WARNING, locale, ns, key, budget, path,
                    ))

                if check_expansion:
                    band = check_expansion_band(src, translated, locale)
                    if band:
                        report.findings.append(Finding(
                            "V14", SEVERITY_WARNING, locale, ns, key, band, path,
                        ))

                typography = check_locale_typography(translated, locale)
                if typography:
                    report.findings.append(Finding(
                        "V34", SEVERITY_WARNING, locale, ns, key, typography, path,
                    ))

                grammar = check_locale_grammar(translated, locale)
                if grammar:
                    report.findings.append(Finding(
                        "V45", SEVERITY_WARNING, locale, ns, key, grammar, path,
                    ))

                dnt_issue = check_dnt_spans(src, translated)
                if dnt_issue:
                    report.findings.append(Finding(
                        "V42", SEVERITY_WARNING, locale, ns, key, dnt_issue, path,
                    ))

                eff_register, _ = cfg.style_for(locale)
                if cfg.register_set or cfg.locale_styles.get(locale, ("", ""))[0]:
                    register_hint = check_register(translated, locale, eff_register)
                    if register_hint:
                        report.findings.append(Finding(
                            "V40", SEVERITY_WARNING, locale, ns, key, register_hint, path,
                        ))

                if check_numbers:
                    numbers = check_number_format(src, translated, locale)
                    if numbers:
                        report.findings.append(Finding(
                            "V38", SEVERITY_WARNING, locale, ns, key, numbers, path,
                        ))

                if want_layout:
                    shot = resolve_screenshot_path(
                        cfg.context_dir,
                        screen=notes.screen(ns, key),
                        image=notes.image(ns, key),
                        locale=locale,
                    )
                    if shot is not None:
                        for issue in layout_check(
                            src,
                            translated,
                            locale,
                            max_chars=notes.max_chars(ns, key),
                            screenshot=shot,
                        ):
                            report.findings.append(Finding(
                                "V28",
                                SEVERITY_WARNING,
                                locale,
                                ns,
                                key,
                                f"{issue.code}: {issue.message}",
                                path,
                            ))

                if want_any_advisory:
                    fk_name = notes.full_key(ns, key)
                    fk_val = target.get(fk_name) if fk_name else None
                    _, advisory = validate_translation_detailed(
                        src, translated, locale, key_glossary,
                        max_chars=notes.max_chars(ns, key),
                        fullkey_sibling=fk_val,
                        check_whitespace=want_ws_fullkey,
                        check_script=want_script,
                        check_digraphs=want_digraphs,
                        check_max_chars_warn=want_ws_fullkey,
                        check_word_count=want_length,
                        check_fullkey=want_ws_fullkey,
                        check_untranslated=check_semantic,
                        check_typography=False,
                        standard=standard,
                    )
                    for failure in advisory:
                        if failure.severity == "error":
                            continue  # already reported via validate_translation
                        if failure.id == "V13":
                            continue  # already reported above, from the same glossary check
                        report.findings.append(Finding(
                            failure.id, SEVERITY_WARNING, locale, ns, key,
                            failure.message, path,
                        ))

                if state is not None:
                    if entry is not None:
                        if needs_translation(src, entry, **notes.stale_args(ns, key)):
                            report.findings.append(Finding(
                                "V07", SEVERITY_WARNING, locale, ns, key,
                                "stale: source or translator context changed since translation",
                                path,
                            ))
                        # Checked independently of V07, not nested inside it. A
                        # signature mismatch on an *unchanged* source cannot come
                        # from an edit -- it means the stored value was written by
                        # something computing signatures differently, which is
                        # exactly the shape of a second-implementation divergence
                        # or an unmigrated signature format.
                        if is_structurally_stale(src, entry):
                            report.findings.append(Finding(
                                "V08", SEVERITY_WARNING, locale, ns, key,
                                "structure signature does not match the current source"
                                + ("; the ICU shape changed and the existing "
                                   "translation is now wrong"
                                   if needs_translation(src, entry) else
                                   " even though the source is unchanged -- run "
                                   "'llm-localizator migrate-state'"),
                                path,
                            ))

                if fingerprint is not None:
                    sk = state_key(ns, key)
                    if len(report.findings) == findings_before:
                        diff_cache.get(locale)[sk] = fingerprint
                    else:
                        diff_cache.get(locale).pop(sk, None)

            # V12 -- keys present in the target but gone from source.
            for orphan in sorted(set(target) - set(source)):
                report.findings.append(Finding(
                    "V12", SEVERITY_WARNING, locale, ns, orphan,
                    "not present in source locale (will be pruned on next write)", path,
                ))
            for missing_key in standard.missing_plural_keys(target, locale):
                report.findings.append(Finding(
                    "V03", SEVERITY_ERROR, locale, ns, missing_key,
                    f"missing required plural key for {locale}", path,
                ))

    from ..core.source_quality import duplicate_source_findings, source_style_findings

    for ns, key, message in duplicate_source_findings(source_items):
        report.findings.append(Finding(
            "V18", SEVERITY_WARNING, cfg.source_locale, ns, key, message,
        ))
    for ns, key, code, message in source_style_findings(source_items):
        report.findings.append(Finding(
            code, SEVERITY_WARNING, cfg.source_locale, ns, key, message,
        ))

    _emit_term_spreads(report, glossary_cache.get(None), term_rows)

    if check_semantic:
        from ..catalog.scores import ScoreStore

        _emit_coherence_findings(
            report, cfg, catalog, notes, state, targets,
            namespace=namespace, namespaces=namespaces,
            scores=ScoreStore(cfg.scores_root()),
        )

    if diff_cache is not None:
        diff_cache.save()

    if cfg.severity_overrides:
        report.findings = apply_severity_overrides(report.findings, cfg.severity_overrides)

    report.findings.sort(key=lambda f: (f.severity != SEVERITY_ERROR, f.locale, f.namespace, f.key))
    return report


def apply_severity_overrides(findings: list[Finding], overrides: dict[str, str]) -> list[Finding]:
    """Re-grade or drop findings per ``[validate.severity]`` (ADR-72). Pure."""
    out: list[Finding] = []
    for f in findings:
        level = overrides.get(f.check)
        if level == "off":
            continue
        if level and level != f.severity:
            f = replace(f, severity=level)
        out.append(f)
    return out


def _emit_coherence_findings(
    report: ValidationReport,
    cfg: ProjectConfig,
    catalog: Catalog,
    notes: ContextNotes,
    state: StateStore | None,
    targets: list[str],
    *,
    namespace: str | None,
    namespaces: list[str] | None,
    scores,
) -> None:
    """V30 exact same-source / V31 similar-source catalogue coherence."""
    from ..catalog.coherence_index import CoherenceIndex

    ns_list = list(_namespaces(cfg, catalog, namespace, namespaces))

    for locale in targets:
        for ns in ns_list:
            source = catalog.load(cfg.source_locale, ns)
            target = catalog.load(locale, ns)
            if not source:
                continue

            entries: list[tuple[str, str, str, str]] = []
            for key, src in source.items():
                if cfg.is_skipped(ns, key, src) or key not in target:
                    continue
                if not isinstance(src, str) or not isinstance(target[key], str):
                    continue
                entries.append((ns, key, src, target[key]))

            # One load per locale — avoid per-key mtime checks on state.entry.
            state_map = state.load(locale) if state is not None else {}
            from ..catalog.state import state_key as _state_key

            def _quality_ok(
                q_ns: str, key: str, *, _loc: str = locale,
            ) -> bool:
                if state is not None:
                    entry = state_map.get(_state_key(q_ns, key)) or {}
                    if entry.get("status") in {"human", "verified", "llm_reviewed", "agent", "imported"}:
                        return True
                    if entry.get("verified"):
                        return True
                if scores is not None:
                    row = scores.get(_loc, q_ns, key) or {}
                    qs = row.get("quality_score")
                    if qs is not None and float(qs) >= 0.80:
                        return True
                return False

            index = CoherenceIndex()
            index.build(entries, quality_ok=_quality_ok)

            def _different_context(
                ns_a: str, key_a: str, ns_b: str, key_b: str,
            ) -> bool:
                if notes.full_key(ns_a, key_a) == key_b or notes.full_key(ns_b, key_b) == key_a:
                    return True
                note_a = (notes.note(ns_a, key_a) or "").strip()
                note_b = (notes.note(ns_b, key_b) or "").strip()
                return bool(note_a and note_b and note_a != note_b)

            for a, b in index.exact_conflicts(
                skip_keys=set(cfg.skip_keys),
                different_context=_different_context,
                max_group=SEMANTIC_COHERENCE_MAX_KEYS,
            ):
                path = catalog.path_for(locale, a.namespace)
                report.findings.append(Finding(
                    "V30", SEVERITY_WARNING, locale, a.namespace, a.key,
                    f"same English source as {b.namespace}.{b.key} but translations "
                    f"differ ({a.target!r} vs {b.target!r})",
                    path,
                ))

            for group, size in index.skipped_groups:
                report.findings.append(Finding(
                    "V30", SEVERITY_WARNING, locale, ns, "",
                    f"V30 skipped one group of {size} keys with the same English "
                    f"source (starts at {group}): above {SEMANTIC_COHERENCE_MAX_KEYS}",
                    catalog.path_for(locale, ns),
                ))

            fuzzy = index.fuzzy_conflicts(
                skip_keys=set(cfg.skip_keys), max_rows=SEMANTIC_COHERENCE_MAX_KEYS,
            )
            if index.fuzzy_skipped:
                report.findings.append(Finding(
                    "V31", SEVERITY_WARNING, locale, ns, "",
                    f"V31 (similar-source) skipped: {len(entries)} keys exceed "
                    f"{SEMANTIC_COHERENCE_MAX_KEYS} in this namespace; "
                    f"V30 (same-source) still ran",
                    catalog.path_for(locale, ns),
                ))
            for a, b, overlap in fuzzy:
                path = catalog.path_for(locale, a.namespace)
                report.findings.append(Finding(
                    "V31", SEVERITY_WARNING, locale, a.namespace, a.key,
                    f"similar English to {b.namespace}.{b.key} "
                    f"(overlap={overlap:.0%}) but translations diverge "
                    f"({a.target!r} vs {b.target!r})",
                    path,
                ))


def _classify(reason: str) -> str:
    return classify_failure(reason)


def _check_source_quality(
    report: ValidationReport,
    cfg: ProjectConfig,
    notes: ContextNotes,
    ns: str,
    key: str,
    src: str,
    standard,
) -> None:
    """Checks on the English source itself -- these are authoring bugs."""
    err = standard.syntax_error(src)
    if err:
        report.findings.append(Finding(
            "V16", SEVERITY_ERROR, cfg.source_locale, ns, key, err,
        ))
        return
    from ..core.source_quality import placeholder_without_note, raw_html_in_plain

    note_missing = placeholder_without_note(
        src,
        has_placeholder=bool(standard.tokens(src)),
        has_note=notes.has_entry(ns, key),
    )
    if note_missing:
        report.findings.append(Finding(
            "V19", SEVERITY_WARNING, cfg.source_locale, ns, key, note_missing,
        ))
    html_plain = raw_html_in_plain(src, marked_html=notes.html(ns, key))
    if html_plain:
        report.findings.append(Finding(
            "V20", SEVERITY_WARNING, cfg.source_locale, ns, key, html_plain,
        ))
    if standard.id != "icu":
        return
    if extract_plural_categories(src) is not None:
        return  # already a proper ICU plural

    m = _NAIVE_PLURAL_RE.search(src)
    if m:
        report.findings.append(Finding(
            "V10", SEVERITY_WARNING, cfg.source_locale, ns, key,
            f"looks like a counted noun ('{m.group(0)}') without ICU plural syntax; "
            f"many languages need 3-6 plural forms",
        ))
        return

    if _COUNTED_HINT_RE.search(src) and not notes.has_entry(ns, key):
        placeholders = extract_placeholders(src)
        if placeholders & {"n", "count", "total"}:
            report.findings.append(Finding(
                "V11", SEVERITY_WARNING, cfg.source_locale, ns, key,
                "numeric placeholder with no context note; translators cannot tell "
                "whether this counts a noun",
            ))
