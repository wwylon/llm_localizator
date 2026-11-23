"""Verify stages. Each takes a :class:`Ctx` and returns a :class:`StageResult`."""

from __future__ import annotations

import os
import time
from collections import Counter
from pathlib import Path

from ..scan.base import UNSUPPORTED_UI_EXTENSIONS
from ..projects.config import CONFIG_FILENAME
from .runner import (
    DEGRADED, FAIL, PASS, SKIPPED, UNSUPPORTED, Ctx, StageResult, _COPY_SKIP, _same_bytes,
)

_I18N_MARKERS = {
    "next-intl": "next-intl", "i18next": "i18next", "react-intl": "react-intl",
    "vue-i18n": "vue-i18n", "formatjs": "formatjs", "flutter_localizations": "flutter_localizations",
    "gettext": "gettext", "rails-i18n": "rails-i18n", "lingui": "lingui", "svelte-i18n": "svelte-i18n",
}
_MANIFESTS = ("package.json", "pubspec.yaml", "requirements.txt", "pyproject.toml", "Gemfile", "composer.json")
_TIERS = ((50, "XS"), (300, "S"), (2000, "M"), (10000, "L"), (50000, "XL"))
_GREENFIELD = {"catalog_format": "json-nested", "catalog_path": "messages/{locale}/{namespace}.json"}


def _walk(ws: Path):
    for dirpath, dirnames, filenames in os.walk(ws):
        dirnames[:] = [d for d in dirnames if d not in _COPY_SKIP and not d.startswith(".llm-")]
        for name in filenames:
            yield Path(dirpath) / name


def s0_fingerprint(ctx: Ctx) -> StageResult:
    from ..core.languages import source_languages

    res = StageResult("S0", "fingerprint", PASS)
    scanned = {e for lang in source_languages() for e in lang.extensions}
    exts: Counter = Counter()
    lines = files = 0
    libs: set[str] = set()
    for path in _walk(ctx.ws):
        files += 1
        ext = path.suffix.lower()
        exts[ext] += 1
        if ext in scanned:
            try:
                with path.open("rb") as fh:
                    lines += sum(1 for _ in fh)
            except OSError:
                pass
        if path.name in _MANIFESTS:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            libs.update(label for key, label in _I18N_MARKERS.items() if key in text)
    has_cfg = (ctx.ws / CONFIG_FILENAME).is_file()
    ctx.fingerprint = {
        "files": files,
        "lines": lines,
        "tier": next((t for limit, t in _TIERS if files <= limit), "XXL"),
        "i18n_libs": sorted(libs),
        "top_extensions": dict(exts.most_common(8)),
        "unscanned_known_gaps": {e: n for e, n in exts.items() if e in UNSUPPORTED_UI_EXTENSIONS},
        "maturity": "configured" if has_cfg else ("partial" if libs else "greenfield"),
    }
    res.metrics = dict(ctx.fingerprint)
    return res


def s1_lifecycle(ctx: Ctx) -> StageResult:
    from ..ops.init import op_init
    from ..ops.types import InitRequest
    from ..projects import load_config
    from ..projects.registry import register_project, resolve_project

    res = StageResult("S1", "lifecycle", PASS)
    cfg_file = ctx.ws / CONFIG_FILENAME
    if cfg_file.is_file():
        ctx.cfg = load_config(cfg_file)
        ctx.has_catalogue = True
        res.notes.append(f"existing {CONFIG_FILENAME} used")
    else:
        out = op_init(InitRequest(directory=str(ctx.ws), name="verify-target"))
        if out.ok:
            ctx.has_catalogue = True
        else:
            res.worsen(DEGRADED, f"auto-detect failed ({out.summary}); greenfield fallback")
            out = op_init(InitRequest(directory=str(ctx.ws), name="verify-target", **_GREENFIELD))
            if not out.ok:
                res.worsen(FAIL, f"greenfield init failed: {out.summary}")
                return res
        ctx.cfg = load_config(cfg_file)

    cfg = ctx.cfg
    ctx.fingerprint["has_catalogue"] = ctx.has_catalogue
    scan_adapter, scan_dirs = cfg.scan_adapter, cfg.scan_src_dirs
    if not scan_adapter or not scan_dirs:
        scan_adapter, scan_dirs = scan_adapter or "source", scan_dirs or ["."]
        ctx.scan_configured_by_verify = True
        res.notes.append("no [scan] configured; verify scans '.' with the source adapter")

    # A manual edit must survive re-running init --force.
    marker = "# verify-marker: keep me\n"
    cfg_file.write_text(marker + cfg_file.read_text(encoding="utf-8"), encoding="utf-8")
    again = op_init(InitRequest(
        directory=str(ctx.ws), name=cfg.name, force=True,
        catalog_format=cfg.catalog_format, catalog_path=cfg.catalog_path,
    ))
    if not again.ok:
        res.worsen(DEGRADED, f"init --force failed: {again.summary}")
    elif marker not in cfg_file.read_text(encoding="utf-8"):
        res.worsen(DEGRADED, "init --force discarded a manual comment (Part 8 merge gap)")
    ctx.cfg = load_config(cfg_file)
    ctx.cfg.scan_adapter, ctx.cfg.scan_src_dirs = scan_adapter, scan_dirs

    for n in (1, 2):
        d = ctx.run_dir / f"dummy{n}"
        d.mkdir(exist_ok=True)
        (d / CONFIG_FILENAME).write_text(f'[project]\nname = "dummy{n}"\n', encoding="utf-8")
        register_project(f"dummy{n}", d)
    try:
        for n in (1, 2):
            if resolve_project(f"dummy{n}").parent.name != f"dummy{n}":
                res.worsen(FAIL, "registry resolved a wrong root")
    except Exception as exc:
        res.worsen(FAIL, f"registry resolve failed: {exc}")
    return res


def s2_catalogues(ctx: Ctx) -> StageResult:
    from ..catalog import catalog_for
    from ..ops.discover import op_discover

    res = StageResult("S2", "catalogues", PASS)
    cfg = ctx.cfg
    disc = op_discover(cfg)
    res.metrics["discover"] = [(p["name"], p["format"], p["root"]) for p in disc.data["proposals"]]
    if not ctx.has_catalogue:
        res.verdict = SKIPPED
        res.notes.append("greenfield: no catalogue to inspect")
        return res
    cat = catalog_for(cfg)
    namespaces = cat.namespaces()
    res.metrics["namespaces"] = len(namespaces)
    res.metrics["locales"] = cat.locales_present()
    broken: list[str] = []
    diffs: list[str] = []
    keys = 0
    for ns in namespaces:
        try:
            msgs = cat.load(cfg.source_locale, ns or None)
            keys += len(msgs)
            path = cat.path_for(cfg.source_locale, ns or None)
            before = path.read_bytes()
            cat.save(cfg.source_locale, ns or None, msgs)
            if path.read_bytes() != before:
                diffs.append(path.relative_to(ctx.ws).as_posix())
                path.write_bytes(before)
        except Exception as exc:
            broken.append(f"{ns or '(root)'}: {type(exc).__name__}")
    res.metrics["source_keys"] = keys
    if broken:
        res.worsen(FAIL, f"{len(broken)} unreadable namespace(s): {broken[:3]}")
    if diffs:
        res.worsen(DEGRADED, f"round-trip changed {len(diffs)} file(s): {diffs[:3]}")
    return res


def s3_baseline(ctx: Ctx) -> StageResult:
    from ..ops.status import op_status
    from ..ops.types import StatusRequest, ValidateRequest
    from ..ops.validate import op_validate

    res = StageResult("S3", "baseline validate", PASS)
    if not ctx.has_catalogue:
        res.verdict = SKIPPED
        res.notes.append("greenfield: nothing to validate")
        return res
    for name, fn in (
        ("status", lambda: op_status(ctx.cfg, StatusRequest())),
        ("validate", lambda: op_validate(ctx.cfg, ValidateRequest())),
    ):
        t = time.perf_counter()
        out = fn()
        res.metrics[name] = {
            "exit": out.exit_code, "summary": out.summary,
            "seconds": round(time.perf_counter() - t, 2),
        }
        if out.exit_code not in (0, 1, 2):  # 2 = warnings only
            res.worsen(FAIL, f"{name} exit {out.exit_code}: {out.summary}")
    return res


def s4_scan(ctx: Ctx) -> StageResult:
    from ..ops.agent_hardcoded import op_agent_hardcoded
    from ..ops.types import AgentHardcodedRequest

    res = StageResult("S4", "scan", PASS)

    def request(**kw) -> AgentHardcodedRequest:
        return AgentHardcodedRequest(fmt="json", catalogue_audit=False, **kw)

    t = time.perf_counter()
    cold = op_agent_hardcoded(ctx.cfg, request(refresh=True))
    cold_s = time.perf_counter() - t
    if not cold.ok:
        res.worsen(FAIL, f"scan failed: {cold.summary}")
        return res
    t = time.perf_counter()
    warm = op_agent_hardcoded(ctx.cfg, request())
    warm_s = time.perf_counter() - t
    hits = cold.data["hits"]
    res.metrics = {
        "hits": len(hits),
        "by_confidence": dict(Counter(h.get("confidence") for h in hits)),
        "files_scanned": cold.data["filesScanned"],
        "top_dirs": dict(Counter(h["file"].split("/")[0] for h in hits).most_common(5)),
        "cold_s": round(cold_s, 2),
        "warm_s": round(warm_s, 2),
        "report_chars_est": sum(len(h["text"]) + len(h["file"]) + 40 for h in hits),
    }
    if len(warm.data["hits"]) != len(hits):
        res.worsen(FAIL, "warm scan returned different hits than cold")
    if cold_s > 2 and warm_s > cold_s * 0.1:
        res.worsen(DEGRADED, f"warm scan not fast ({warm_s:.2f}s vs cold {cold_s:.2f}s)")
    gaps = ctx.fingerprint.get("unscanned_known_gaps", {})
    if gaps:
        res.worsen(UNSUPPORTED, f"extensions with no scanner: {gaps}")
    return res


def s6_oob_edits(ctx: Ctx) -> StageResult:
    """Edit catalogue values on the copy the way an agent would; each edit must surface as a gap."""
    from ..catalog import catalog_for
    from ..ops.catalogue_gaps import iter_catalogue_gaps

    res = StageResult("S6", "out-of-band edits", PASS)
    if not ctx.has_catalogue or not ctx.cfg.targets:
        res.verdict = SKIPPED
        res.notes.append("no catalogue with target locales")
        return res
    cfg = ctx.cfg
    cat = catalog_for(cfg)
    locale = cfg.targets[0]
    ns = next((n for n in cfg.namespaces_for(cat) if cat.load(locale, n) and cat.load(cfg.source_locale, n)), None)
    if ns is None:
        res.verdict = SKIPPED
        res.notes.append("no namespace with both source and target values")
        return res
    original = cat.load(locale, ns)
    source = cat.load(cfg.source_locale, ns)
    key = next((k for k, v in original.items() if k in source and isinstance(v, str) and v.strip()), None)
    if key is None:
        res.verdict = SKIPPED
        return res

    def reasons() -> set[str]:
        return {g.reason for g in iter_catalogue_gaps(cfg, locales=[locale], namespaces=[ns])
                if g.key == key}

    probes = {
        "changed value": ({**original, key: original[key] + " (edited)"}, {"external_edit", "no_state", "stale"}),
        "deleted key": ({k: v for k, v in original.items() if k != key}, {"missing"}),
        "blanked value": ({**original, key: ""}, {"empty"}),
    }
    try:
        for name, (data, expected) in probes.items():
            cat.save(locale, ns, data)
            got = reasons()
            res.metrics[name] = sorted(got)
            if not got & expected:
                res.worsen(FAIL if name != "changed value" else DEGRADED,
                           f"{name} on {locale}/{ns}/{key} not reported (got {sorted(got)})")
    finally:
        cat.save(locale, ns, original)
    return res


def s5_reports(ctx: Ctx) -> StageResult:
    """Split the scan hits into agent-sized parts; every part must fit the token budget."""
    from ..ops.agent_hardcoded import op_agent_hardcoded
    from ..ops.report_split import est_tokens, pack_hits, render_part
    from ..ops.types import AgentHardcodedRequest

    res = StageResult("S5", "reports", PASS)
    out = op_agent_hardcoded(ctx.cfg, AgentHardcodedRequest(fmt="json", catalogue_audit=False))
    if not out.ok:
        res.worsen(FAIL, f"scan failed: {out.summary}")
        return res
    hits = out.data["hits"]
    budget = 15000
    parts = pack_hits(hits, budget_tokens=budget)
    sizes = [est_tokens(render_part("verify", p, i, len(parts), "", "")) for i, p in enumerate(parts, 1)]
    res.metrics = {"hits": len(hits), "parts": len(parts), "max_part_tokens": max(sizes, default=0)}
    if sum(len(p.hits) for p in parts) != len(hits):
        res.worsen(FAIL, "parts do not cover every hit exactly once")
    if sizes and max(sizes) > budget:
        res.worsen(DEGRADED, f"largest part ~{max(sizes)} tokens exceeds budget {budget}")
    if not hits:
        res.notes.append("no hits to split")
    return res


def s7_translation_sample(ctx: Ctx) -> StageResult:
    """Real-model sample per locale set. Needs a running provider, so it only runs when asked for."""
    from .locale_sets import resolve_locales

    res = StageResult("S7", "translation sample", SKIPPED)
    wanted = resolve_locales(ctx.locales)
    res.metrics["locales"] = wanted
    res.notes.append("model-backed sample is queued via taskqueue (ADR-28); no provider called in-process")
    return res


def s9_locale_robustness(ctx: Ctx) -> StageResult:
    """Every requested locale resolves to a usable profile; unprofiled ones fall back and are listed."""
    from ..core.locales import known_locales, profile
    from ..core.locales.base import CLDR_CATEGORIES
    from .locale_sets import resolve_locales

    res = StageResult("S9", "locale robustness", PASS)
    wanted = resolve_locales(ctx.locales)
    if not wanted:
        res.verdict = SKIPPED
        res.notes.append("no --locales given")
        return res
    known = {c.lower() for c in known_locales()}
    unprofiled = [c for c in wanted if c.lower() not in known and c.split("-")[0].lower() not in known]
    for code in wanted:
        p = profile(code)
        if not set(p.plural_categories) <= CLDR_CATEGORIES or "other" not in p.plural_categories:
            res.worsen(FAIL, f"{code}: invalid plural categories {p.plural_categories}")
    res.metrics = {"locales": len(wanted), "unprofiled": unprofiled}
    if unprofiled:
        res.worsen(UNSUPPORTED, f"no language profile (generic fallback): {', '.join(unprofiled)}")
    return res


def s8_source_safety(ctx: Ctx) -> StageResult:
    res = StageResult("S8", "source-safety", PASS)
    changed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ctx.src):
        dirnames[:] = [d for d in dirnames if d not in _COPY_SKIP]
        for name in filenames:
            orig = Path(dirpath) / name
            rel = orig.relative_to(ctx.src).as_posix()
            if ctx.allowed(rel):
                continue
            copy = ctx.ws / rel
            if not copy.is_file() or not _same_bytes(orig, copy):
                changed.append(rel)
    if changed or ctx.violations:
        res.worsen(FAIL, f"engine changed non-catalogue files: {changed[:5]}")
        res.metrics["violations"] = ctx.violations
    return res


STAGES = {
    "S0": ("fingerprint", s0_fingerprint),
    "S1": ("lifecycle", s1_lifecycle),
    "S2": ("catalogues", s2_catalogues),
    "S3": ("baseline validate", s3_baseline),
    "S4": ("scan", s4_scan),
    "S5": ("reports", s5_reports),
    "S6": ("out-of-band edits", s6_oob_edits),
    "S7": ("translation sample", s7_translation_sample),
    "S8": ("source-safety", s8_source_safety),
    "S9": ("locale robustness", s9_locale_robustness),
}
