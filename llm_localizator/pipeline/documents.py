"""Section-level Markdown translation for long documents.

Built for legal text -- terms of service, privacy policy -- where three things
differ from UI strings:

* **Sections are the unit.** Splitting on ``## `` headings means an edit to one
  clause retranslates that clause, not the whole document.
* **Neighbouring sections are supplied as context** so terminology stays
  coherent across a document translated in pieces.
* **Failure is all-or-nothing.** If any section fails, the whole locale file is
  removed so the page falls back to the source language. A half-translated
  privacy policy is worse than an untranslated one: it looks authoritative and
  is wrong.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..core.cldr import language_name
from ..core.hash import src_hash
from ..catalog.io import atomic_write_text
from ..providers import CompletionRequest, Provider, ProviderError, metered_complete

__all__ = [
    "split_sections", "join_sections", "is_frontmatter", "DocumentResult", "translate_document",
    "validate_document", "validate_section", "draft_section_edits",
]

Reporter = Callable[[str], None]

_HEADING_RE = re.compile(r"^##\s+")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s)>\]\"']+[^\s)>\]\"'.,;:!?]")


_DEFAULT_KEEP_ALIVE_S = 30 * 60.0
_now = time.monotonic  # replaced in tests


def _keep_alive_seconds(provider: Provider) -> float:
    """The provider's keep_alive as seconds. 0 means "never trust the warm model"."""
    raw = getattr(provider, "keep_alive", None)
    if raw is None:
        return _DEFAULT_KEEP_ALIVE_S
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else 0.0
    text = str(raw).strip().lower()
    units = {"s": 1.0, "m": 60.0, "h": 3600.0}
    try:
        if text and text[-1] in units:
            value = float(text[:-1]) * units[text[-1]]
        else:
            value = float(text)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0


def is_frontmatter(section: str) -> bool:
    """A leading YAML block. It is metadata, so it is copied, never sent to the model."""
    return bool(_FRONTMATTER_RE.fullmatch(section))


def _heading_offsets(text: str) -> list[int]:
    """Offsets of ``## `` headings that are not inside a fenced code block."""
    offsets: list[int] = []
    fence = ""
    pos = 0
    for line in text.splitlines(keepends=True):
        marker = _FENCE_RE.match(line)
        if marker:
            char = marker.group(1)[0]
            if not fence:
                fence = marker.group(1)
            elif char == fence[0] and len(marker.group(1)) >= len(fence) and not line.strip(char + " \t\r\n"):
                fence = ""
        elif not fence and _HEADING_RE.match(line):
            offsets.append(pos)
        pos += len(line)
    return offsets


def split_sections(text: str) -> list[str]:
    """Split Markdown on ``## `` headings.

    A ``## `` inside a fenced code block is not a heading. A leading YAML
    frontmatter block is its own section. Any preamble before the first heading
    becomes a section, so a document with no headings round-trips as one section.
    """
    if not text:
        return []
    sections: list[str] = []
    front = _FRONTMATTER_RE.match(text)
    if front:
        sections.append(front.group(0))
        text = text[front.end():]
        if not text:
            return sections
    offsets = _heading_offsets(text)
    if not offsets:
        return sections + [text]

    if offsets[0] > 0:
        sections.append(text[:offsets[0]])
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(text)
        sections.append(text[start:end])
    return sections


def join_sections(sections: list[str]) -> str:
    """Reassemble, dropping empties so a failed section cannot leave a hole."""
    return "".join(s for s in sections if s and s.strip())


@dataclass
class DocumentResult:
    translated: int = 0
    reused: int = 0
    failed: int = 0
    written: Path | None = None
    removed: Path | None = None
    sections: list[str] = field(default_factory=list)
    # One row per section: {"index", "status", "problem"} -- the validation report.
    report: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def validate_section(source: str, translated: str) -> str | None:
    """Why *translated* cannot stand in for *source*, or ``None`` when it can.

    Cheap structural checks only: the heading marker survives, code fences stay
    equal in number, and every URL is copied through unchanged.
    """
    first_src = next((ln for ln in source.splitlines() if ln.strip()), "")
    first_out = next((ln for ln in translated.splitlines() if ln.strip()), "")
    if _HEADING_RE.match(first_src) and not _HEADING_RE.match(first_out):
        return "heading marker '## ' was lost"
    fences_src = sum(1 for ln in source.splitlines() if _FENCE_RE.match(ln))
    fences_out = sum(1 for ln in translated.splitlines() if _FENCE_RE.match(ln))
    if fences_src != fences_out:
        return f"code fence count changed ({fences_src} -> {fences_out})"
    missing = [u for u in _URL_RE.findall(source) if u not in translated]
    if missing:
        return f"URL not preserved: {missing[0]}"
    return None


def validate_document(source_path: Path, target_path: Path) -> list[dict]:
    """Per-section validation report of an existing translation (no LLM).

    Rows are ``{"index", "status", "problem"}`` with status ``ok``, ``invalid``,
    ``missing`` (target has fewer sections) or ``frontmatter``.
    """
    src = split_sections(Path(source_path).read_text(encoding="utf-8"))
    tgt_path = Path(target_path)
    tgt = split_sections(tgt_path.read_text(encoding="utf-8")) if tgt_path.exists() else []
    rows: list[dict] = []
    for i, section in enumerate(src):
        if is_frontmatter(section):
            rows.append({"index": i, "status": "frontmatter", "problem": None})
        elif i >= len(tgt):
            rows.append({"index": i, "status": "missing", "problem": "no translated section"})
        else:
            problem = validate_section(section, tgt[i])
            rows.append({"index": i, "status": "invalid" if problem else "ok", "problem": problem})
    return rows


def build_section_prompt(
    section: str, previous_translation: str | None, before: str, after: str,
    language: str, domain: str,
) -> str:
    prior = ""
    if previous_translation:
        prior = (
            "An earlier translation of this same section is provided. Update it to match "
            "the current English rather than starting over, so wording stays stable across "
            f"revisions:\n---\n{previous_translation}\n---\n"
        )
    context = ""
    if before or after:
        context = (
            "Neighbouring sections, for terminology consistency only -- do NOT translate "
            f"or repeat them:\n[before]\n{before[:600]}\n[after]\n{after[:600]}\n\n"
        )
    return (
        f"You are a professional legal translator for {domain}.\n"
        f"{prior}{context}"
        f"Translate the following Markdown section from English to {language}.\n"
        f"\n"
        f"Rules:\n"
        f"1. Output ONLY the translated Markdown. No commentary, and do not wrap the answer in a code fence.\n"
        f"2. Preserve the Markdown structure exactly: heading level, lists, emphasis, links.\n"
        f"3. Translate the heading text itself, keeping the '## ' marker.\n"
        f"4. Keep legal register. Prefer the established legal term over a literal one.\n"
        f"5. Leave URLs, email addresses, and proper nouns unchanged.\n"
        f"6. Fenced code blocks and inline `code` stay exactly as written; translate only prose and comments meant for readers.\n"
        f"\n"
        f"Section:\n{section}"
    )


def draft_section_edits(
    source_path: Path,
    target_path: Path,
    locale: str,
    provider: Provider,
    *,
    model: str,
    state: dict,
) -> list[dict]:
    """Minimal-edit drafts for changed sections (C-047, ADR-100). Writes nothing.

    A section qualifies when its English changed, the state recorded the old English
    (``src``, kept since C-047) and a translation exists at the same position. The
    rest are left to ``translate_document``. Each draft is for a person to review.
    """
    from ..pipeline.minimal_edit import minimal_edit

    if not target_path.exists():
        return []
    sections = split_sections(source_path.read_text(encoding="utf-8"))
    previous = split_sections(target_path.read_text(encoding="utf-8"))
    language = language_name(locale)
    drafts: list[dict] = []
    for index, section in enumerate(sections):
        if is_frontmatter(section) or index >= len(previous):
            continue
        record = state.get(str(index))
        if not isinstance(record, dict) or record.get("src_sha") == src_hash(section):
            continue
        old_source = record.get("src")
        if not old_source or not previous[index].strip():
            continue
        text = minimal_edit(
            provider, model, old_source=old_source, new_source=section,
            old_translation=previous[index], language=language,
        )
        if text:
            drafts.append({
                "index": index, "oldSource": old_source, "newSource": section,
                "previous": previous[index], "draft": text if text.endswith("\n") else text + "\n\n",
            })
    return drafts


def translate_document(
    source_path: Path,
    target_path: Path,
    locale: str,
    provider: Provider,
    *,
    model: str,
    domain: str = "a software application",
    state: dict | None = None,
    timeout_s: int = 600,
    dry_run: bool = False,
    report: Reporter = print,
    project=None,
) -> DocumentResult:
    """Translate one document, reusing sections whose English is unchanged."""
    result = DocumentResult()
    language = language_name(locale)
    source = source_path.read_text(encoding="utf-8")
    sections = split_sections(source)
    if not sections:
        return result

    previous = split_sections(
        target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    )
    state = state if state is not None else {}
    out: list[str] = []

    # Reuse is keyed by the source section's hash, not its position, so
    # inserting or removing a section cannot pair a translation with the wrong
    # English. Entries written before text was kept fall back to position.
    stored = {
        rec["src_sha"]: rec["text"]
        for rec in state.values()
        if isinstance(rec, dict) and rec.get("src_sha") and rec.get("text")
    }

    def reusable(index: int, digest: str) -> str | None:
        if digest in stored:
            return stored[digest]
        recorded = state.get(str(index))
        if (
            isinstance(recorded, dict) and "text" not in recorded
            and recorded.get("src_sha") == digest and index < len(previous)
        ):
            return previous[index]
        return None

    needs_llm = any(
        not is_frontmatter(section) and reusable(i, src_hash(section)) is None
        for i, section in enumerate(sections)
    )
    warm_window = _keep_alive_seconds(provider) / 2
    last_call = float("-inf")
    if not dry_run and needs_llm:
        provider.ensure_ready(model, report=report)
        last_call = _now()

    for index, section in enumerate(sections):
        if is_frontmatter(section):
            out.append(section)
            result.report.append({"index": index, "status": "frontmatter", "problem": None})
            continue
        digest = src_hash(section)
        cached = reusable(index, digest)

        if cached is not None:
            out.append(cached)
            result.reused += 1
            result.report.append({"index": index, "status": "reused", "problem": None})
            continue

        if dry_run:
            report(f"[{index + 1}/{len(sections)}] would translate section {index} -> {locale}")
            out.append(section)
            result.translated += 1
            continue

        # Re-warm so keep_alive expiry mid-document does not strand later sections
        # on a cold model, but not when the model was used within half its
        # keep_alive window: it is still resident and the warmup is pure overhead.
        if _now() - last_call >= warm_window:
            provider.ensure_ready(model, report=report)
            last_call = _now()
        prompt = build_section_prompt(
            section,
            previous[index] if index < len(previous) else None,
            sections[index - 1] if index > 0 else "",
            sections[index + 1] if index + 1 < len(sections) else "",
            language, domain,
        )
        try:
            req = CompletionRequest(
                prompt=prompt, model=model, timeout_s=timeout_s,
                options={"target_lang": locale, "locale": locale},
                source_texts=[section], target_locale=locale,
            )
            if project is not None:
                translated = metered_complete(project, provider, locale, req)
            else:
                translated = provider.complete(req)
        except ProviderError as exc:
            report(f"    FAIL: section {index} -- {exc}")
            result.report.append({"index": index, "status": "failed", "problem": str(exc)})
            result.failed += 1
            break
        last_call = _now()

        if not translated.strip():
            report(f"    FAIL: section {index} -- empty translation")
            result.report.append({"index": index, "status": "failed", "problem": "empty translation"})
            result.failed += 1
            break

        problem = validate_section(section, translated)
        if problem:
            report(f"    FAIL: section {index} -- {problem}")
            result.report.append({"index": index, "status": "failed", "problem": problem})
            result.failed += 1
            break

        translated = translated if translated.endswith("\n") else translated + "\n\n"
        out.append(translated)
        state[str(index)] = {"src_sha": digest, "model": model, "text": translated, "src": section}
        result.translated += 1
        result.report.append({"index": index, "status": "translated", "problem": None})
        report(f"[{index + 1}/{len(sections)}] section {index} -> {locale} "
               f"({round((index + 1) / len(sections) * 100, 1)}%)")

    if dry_run:
        result.sections = out
        return result

    if not result.ok:
        # All-or-nothing: remove the target so the page falls back to English
        # rather than serving a partially translated legal document.
        if target_path.exists():
            target_path.unlink()
            result.removed = target_path
            report(f"    removed {target_path} -- falling back to source language")
        # Finished sections stay in *state* so the next run resumes after them.
        return result

    target_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target_path, join_sections(out))
    result.written = target_path
    result.sections = out
    return result
