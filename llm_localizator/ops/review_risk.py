"""``llm-localizator review-risk``: which translations a person should read first (P5, ADR-126).

Read-only. Ranks every translated key of a locale from what the engine already
stores. Nothing calls a model. The inputs are:
- the quality score (low first);
- the ``contradiction:`` signal and a judge suggestion (ADR-125);
- one- and two-word keys (labels and buttons hide one-word errors);
- drafts held by the write floor (ADR-117);
- keys no person has reviewed (status not ``human``).

The output is a ranked list with source, current text, score, reasons and the
judge's suggestion, as text, JSON or CSV for a spreadsheet review.
"""

from __future__ import annotations

import csv
import io

from ..catalog import catalog_for
from ..catalog.drafts import DraftStore
from ..catalog.scores import quality_score_of
from ..catalog.state import is_translated_value
from ..pipeline.judge import suggestion_of
from ..pipeline.recording import provenance_stores
from ..pipeline.scoring import is_risky_key
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["op_review_risk", "risk_of"]


def risk_of(*, source: str, score: float | None, signals: list[str], status: str,
            has_draft: bool) -> tuple[float, list[str]]:
    """``(risk 0..∞, reasons)`` for one translated key. Pure, for tests."""
    risk, reasons = 0.0, []
    if score is None:
        risk += 1.0
        reasons.append("unscored")
    elif score < 0.9:
        risk += (0.9 - score) * 5
        reasons.append(f"score {score:.2f}")
    if any(isinstance(s, str) and s.startswith("contradiction") for s in signals):
        risk += 2.0
        reasons.append("back-translation contradicts the source")
    if suggestion_of(signals):
        risk += 1.5
        reasons.append("judge suggested another text")
    if has_draft:
        risk += 1.5
        reasons.append("a held draft waits")
    if is_risky_key(source):
        risk += 1.0
        reasons.append("short label")
    if status == "human":
        risk *= 0.2  # a person already chose this text
    elif reasons:
        reasons.append(f"not reviewed ({status or 'machine'})")
    return round(risk, 2), reasons


def op_review_risk(cfg: ProjectConfig, *, locale: str, limit: int = 50, fmt: str = "text") -> OpResult:
    command = "review-risk"
    if locale not in set(cfg.targets) | set(getattr(cfg, "frozen", []) or []):
        return OpResult(ok=False, exit_code=2, command=command,
                        summary=f"{locale} is not a target locale of {cfg.name}")
    catalog = catalog_for(cfg)
    stores = provenance_stores(cfg)
    state = stores.state.load(locale)
    scores = stores.scores.load(locale)
    drafts = {(d.get("namespace") or "", d.get("key")) for d in DraftStore.for_project(cfg).items().values()
              if d.get("locale") == locale}
    rows = []
    for ns in cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)
        for key, src in source.items():
            text = target.get(key)
            if not isinstance(src, str) or not is_translated_value(src, text):
                continue
            sk = f"{ns}.{key}" if ns else key
            entry = scores.get(sk) if isinstance(scores.get(sk), dict) else None
            st = state.get(sk) if isinstance(state.get(sk), dict) else {}
            signals = list((entry or {}).get("signals") or [])
            risk, reasons = risk_of(source=src, score=quality_score_of(entry), signals=signals,
                                    status=str(st.get("status") or ""), has_draft=(ns, key) in drafts)
            if risk <= 0:
                continue
            rows.append({"key": sk, "source": src, "text": text, "risk": risk,
                         "score": quality_score_of(entry), "reasons": reasons,
                         "suggestion": suggestion_of(signals)})
    rows.sort(key=lambda r: (-r["risk"], r["key"]))
    top = rows[:max(1, limit)]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["key", "source", "current", "suggestion", "risk", "score", "reasons", "decision"])
        for r in top:
            w.writerow([r["key"], r["source"], r["text"], r["suggestion"] or "", r["risk"],
                        "" if r["score"] is None else r["score"], "; ".join(r["reasons"]), ""])
        lines = buf.getvalue().splitlines()
    else:
        lines = []
        for r in top:
            lines.append(f"{r['risk']:5.2f}  {r['key']}: {r['source']!r} -> {r['text']!r}")
            lines.append(f"       {'; '.join(r['reasons'])}"
                         + (f" | judge: {r['suggestion']!r}" if r["suggestion"] else ""))
    return OpResult(
        ok=True, exit_code=0, command=command,
        summary=(f"{sum(1 for r in rows if r['risk'] >= 2)} high-risk {locale} translation(s) "
                 f"(risk >= 2) of {len(rows)} ranked; showing {len(top)}"),
        lines=lines, data={"locale": locale, "total": len(rows),
                           "high": sum(1 for r in rows if r["risk"] >= 2), "rows": top},
    )
