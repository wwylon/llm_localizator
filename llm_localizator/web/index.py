"""Message index for paginated web table — compact rows, filter, sort, hydrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..catalog.provenance import provider_of
from ..catalog.state import is_verified, matches_status_filter, state_key, translation_status
from ..core.locale_ui import font_family, text_direction
from ..render import preview_if_icu
from ..projects.screenshots import resolve_screenshot_path
from ..scan.usage_hints import load_usage_hints
from .plurals import plural_view

if TYPE_CHECKING:
    from .server import AppState

MAX_PAGE_LIMIT = 250
PAGE_SIZE_ALL_THRESHOLD = 500
FULL_FINDINGS_THRESHOLD = 2000

_STATUS_ORDER = {
    "missing": 0,
    "stale": 1,
    "untranslated": 2,
    "intentional": 3,
    "machine": 4,
    "imported": 5,
    "agent": 6,
    "human": 7,
}


def clamp_limit(limit: int | None, *, default: int = 100) -> int:
    """Return a clamped positive page size (never unlimited).

    ``None`` and ``<= 0`` both resolve to *default* so clients cannot bypass
    ``MAX_PAGE_LIMIT`` with ``limit=0`` / ``limit=-1``.
    """
    if limit is None:
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = default
    if n <= 0:
        return default
    return min(n, MAX_PAGE_LIMIT)


@dataclass
class IndexRow:
    namespace: str
    key: str
    source: str
    values: dict[str, str | None]
    statuses: dict[str, str]
    providers: dict[str, str | None]
    models: dict[str, str | None]
    primary_status: str
    primary_provider: str | None
    verified: bool
    quality_score: float | None
    _haystack: str | None = None

    @property
    def haystack(self) -> str:
        """Lower-cased search text; built on first use, not for every row."""
        if self._haystack is None:
            self._haystack = (
                self.key + " " + self.source + " "
                + " ".join(v or "" for v in self.values.values())
            ).lower()
        return self._haystack


@dataclass
class MessageIndex:
    """Compact index for one (locales, namespace scope) pair."""

    locales: tuple[str, ...]
    namespace_scope: str
    rows: list[IndexRow] = field(default_factory=list)

    @classmethod
    def build_row(
        cls,
        st: AppState,
        locales: list[str],
        ns: str,
        key: str,
        *,
        scores=None,
        _source: dict | None = None,
        _targets: dict[str, dict] | None = None,
    ) -> IndexRow | None:
        if st.cfg.is_skipped(ns, key):
            return None
        source = _source if _source is not None else st.catalog.load(st.cfg.source_locale, ns)
        if key not in source:
            return None
        src = source[key]
        if not locales:
            locales = st.cfg.targets[:1]
        primary = locales[0] if locales else ""
        if scores is None and primary:
            scores = st.scores_store()
        targets = _targets if _targets is not None else {
            loc: st.catalog.load(loc, ns) for loc in locales
        }
        values: dict[str, str | None] = {}
        statuses: dict[str, str] = {}
        providers: dict[str, str | None] = {}
        models: dict[str, str | None] = {}
        for loc in locales:
            val = targets[loc].get(key)
            values[loc] = val
            entry = st.store.entry(loc, ns, key) if st.store else None
            statuses[loc] = translation_status(src, val, entry)
            if val is None or entry is None:
                providers[loc] = None
                models[loc] = None
            else:
                providers[loc] = provider_of(entry)
                models[loc] = entry.get("model")

        primary_entry = st.store.entry(primary, ns, key) if st.store else None
        score_entry = scores.get(primary, ns, key) if scores else None
        quality_score = None
        if score_entry and score_entry.get("quality_score") is not None:
            try:
                quality_score = float(score_entry["quality_score"])
            except (TypeError, ValueError):
                quality_score = None

        return IndexRow(
            namespace=ns,
            key=key,
            source=src,
            values=values,
            statuses=statuses,
            providers=providers,
            models=models,
            primary_status=statuses.get(primary, "missing"),
            primary_provider=providers.get(primary),
            verified=is_verified(primary_entry),
            quality_score=quality_score,
        )

    @classmethod
    def build(
        cls,
        st: AppState,
        locales: list[str],
        namespace: str,
    ) -> MessageIndex:
        all_ns = namespace == "__all__"
        ns_list = st.namespaces() if all_ns else [namespace]
        if not locales:
            locales = st.cfg.targets[:1]
        primary = locales[0] if locales else ""
        scores = st.scores_store() if primary else None
        index = cls(locales=tuple(locales), namespace_scope=namespace)

        for ns in ns_list:
            source = st.catalog.load(st.cfg.source_locale, ns)
            targets = {loc: st.catalog.load(loc, ns) for loc in locales}
            for key in source:
                row = cls.build_row(
                    st, locales, ns, key, scores=scores, _source=source,
                    _targets=targets,
                )
                if row is not None:
                    index.rows.append(row)
        return index

    def patch_row(
        self,
        st: AppState,
        locales: list[str],
        namespace: str,
        key: str,
    ) -> bool:
        """Replace one row in-place; drop it when the key left the source."""
        row = self.build_row(st, locales, namespace, key)
        for i, existing in enumerate(self.rows):
            if existing.namespace == namespace and existing.key == key:
                if row is None:
                    del self.rows[i]
                else:
                    self.rows[i] = row
                return row is not None
        if row is not None and (
            self.namespace_scope == namespace or self.namespace_scope == "__all__"
        ):
            self.rows.append(row)
            return True
        return False

    def filter_rows(
        self,
        *,
        only: str,
        query: str,
        threshold: float,
        findings_by_ns: dict[str, dict[str, list[str]]] | None = None,
        pre_translated_keys: set[str] | None = None,
        mode: str = "exact",
    ) -> list[IndexRow]:
        import re

        needle = (query or "").strip()
        needle_l = needle.lower()
        mode = (mode or "exact").lower()
        regexp = None
        if mode == "regexp" and needle:
            try:
                regexp = re.compile(needle, re.IGNORECASE)
            except re.error:
                return []
        fuzzy_tokens = [t for t in needle_l.split() if t] if mode == "fuzzy" and needle else []
        need_findings = only == "has_findings"
        out: list[IndexRow] = []
        for row in self.rows:
            row_findings = (
                (findings_by_ns or {}).get(row.namespace, {}).get(row.key, [])
                if need_findings
                else []
            )
            if only == "pre_translated":
                if state_key(row.namespace, row.key) not in (pre_translated_keys or set()):
                    continue
            elif only == "has_findings":
                if not row_findings:
                    continue
            elif not matches_status_filter(
                only,
                status=row.primary_status,
                provider=row.primary_provider,
                verified=row.verified,
                quality_score=row.quality_score,
                threshold=threshold,
            ):
                continue
            if needle:
                hay = row.haystack or ""
                if mode == "regexp":
                    if regexp is None or regexp.search(hay) is None:
                        continue
                elif mode == "fuzzy":
                    hay_l = hay.lower()
                    if not fuzzy_tokens or not all(tok in hay_l for tok in fuzzy_tokens):
                        continue
                elif needle_l not in hay.lower():
                    continue
            out.append(row)
        return out

    def sort_rows(
        self,
        rows: list[IndexRow],
        sort_col: str,
        sort_dir: str,
        primary: str,
    ) -> list[IndexRow]:
        if not sort_col:
            return rows
        reverse = sort_dir == "desc"
        col = sort_col

        def key_fn(r: IndexRow) -> Any:
            if col == "key":
                return r.key
            if col == "namespace":
                return r.namespace
            if col == "source":
                return r.source
            if col == "status":
                return _STATUS_ORDER.get(r.primary_status, 99)
            if col == "score":
                return r.quality_score if r.quality_score is not None else -1.0
            if col == "primary" or col == primary:
                return r.values.get(primary) or ""
            return r.key

        return sorted(rows, key=key_fn, reverse=reverse)


def hydrate_rows(
    st: AppState,
    index_rows: list[IndexRow],
    locales: list[str],
    *,
    detail: str = "minimal",
    findings_by_ns: dict[str, dict[str, list[str]]] | None = None,
) -> list[dict]:
    """Build API row dicts for a page of index rows."""
    primary = locales[0] if locales else ""
    full_detail = detail == "full"
    native_cache: dict[str, dict[str, str]] = {}
    targets_by_ns: dict[str, dict[str, dict]] = {}
    hints_by_ns: dict[str, dict[str, str]] = {}
    if getattr(st.catalog, "carries_notes", False):
        for row in index_rows:
            if row.namespace not in native_cache:
                native_cache[row.namespace] = {
                    k: m.note
                    for k, m in st.catalog.load_entries(
                        st.cfg.source_locale, row.namespace
                    ).items()
                }

    out: list[dict] = []
    for row in index_rows:
        ns, key = row.namespace, row.key
        primary_entry = st.store.entry(primary, ns, key) if st.store else None
        row_findings = (findings_by_ns or {}).get(ns, {}).get(key, [])

        entry: dict[str, Any] = {
            "key": key,
            "namespace": ns,
            "source": row.source,
            "icuPreview": preview_if_icu(row.source, st.cfg.source_locale),
            "values": row.values,
            "statuses": row.statuses,
            "providers": row.providers,
            "models": row.models,
            "provider": row.primary_provider,
            "model": row.models.get(primary),
            "verified": row.verified,
            "verifiedAt": (primary_entry or {}).get("verified_at"),
            "qualityScore": row.quality_score,
            "findings": row_findings,
            "textDirection": text_direction(primary),
            "fontFamily": font_family(primary),
        }

        if full_detail:
            from ..catalog import ScoreStore

            scores = st.scores or ScoreStore(st.cfg.scores_root())
            score_entry = scores.get(primary, ns, key) if scores else None
            quality_signals: list[str] = []
            quality_dimensions: dict[str, float] | None = None
            quality_scorer = None
            if score_entry:
                raw_signals = score_entry.get("signals") or []
                if isinstance(raw_signals, list):
                    quality_signals = [str(s) for s in raw_signals]
                raw_dims = score_entry.get("dimensions")
                if isinstance(raw_dims, dict):
                    quality_dimensions = {
                        str(k): float(v)
                        for k, v in raw_dims.items()
                        if isinstance(v, (int, float))
                    }
                if isinstance(score_entry.get("scorer"), str):
                    quality_scorer = score_entry["scorer"]

            targets = targets_by_ns.get(ns)
            if targets is None:
                targets = targets_by_ns[ns] = {
                    loc: st.catalog.load(loc, ns) for loc in locales
                }
            entry["valuePreviews"] = {
                loc: html
                for loc, val in row.values.items()
                if (html := preview_if_icu(val or "", loc))
            }
            screen_id = st.notes.screen(ns, key)
            image_rel = st.notes.image(ns, key)
            fk = st.notes.full_key(ns, key)
            entry.update({
                "qualitySignals": quality_signals,
                "qualityDimensions": quality_dimensions,
                "qualityScorer": quality_scorer,
                "note": native_cache.get(ns, {}).get(key) or st.notes.note(ns, key),
                "llmNote": st.notes.llm_note(ns, key),
                "scanHint": hints_by_ns.setdefault(
                    ns, load_usage_hints(getattr(st.cfg, "scan_out_dir", None), ns),
                ).get(key, ""),
                "tags": st.notes.tags(ns, key),
                "maxChars": st.notes.max_chars(ns, key),
                "fullKey": fk,
                "fullKeyValue": targets[primary].get(fk) if fk else None,
                "screen": screen_id,
                "image": image_rel,
                "screenshot": None,
            })
            if st.cfg.context_dir:
                shot = resolve_screenshot_path(
                    st.cfg.context_dir,
                    screen=screen_id,
                    image=image_rel,
                )
                if shot:
                    entry["screenshot"] = str(
                        shot.relative_to(st.cfg.context_dir.resolve())
                    )
            entry["plural"] = plural_view(
                row.source,
                row.values.get(primary) or "",
                primary,
                getattr(st.cfg, "catalog_standard", None),
            )
            entry["glossaryHits"] = []
            entry["locked"] = bool(primary_entry and primary_entry.get("locked") is True)
        else:
            entry.update({
                "qualitySignals": [],
                "qualityDimensions": None,
                "qualityScorer": None,
                "note": "",
                "llmNote": "",
                "tags": [],
                "maxChars": None,
                "fullKey": None,
                "fullKeyValue": None,
                "screen": None,
                "image": None,
                "screenshot": None,
            })

        out.append(entry)
    return out


def index_cache_key(locales: list[str], namespace: str) -> tuple[tuple[str, ...], str]:
    return (tuple(locales), namespace)
