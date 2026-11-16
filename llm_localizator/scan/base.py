"""Source-code scanner interface.

Scanners read *source files*, not catalogues. They answer two questions:

  * which call sites use which message key (usage backreferences, which give the
    translator "this string appears on the club roster screen" context); and
  * which user-visible strings are hardcoded instead of routed through the
    translation function -- a string that never reaches the catalogue can never
    be translated, so no catalogue check can find it.

Only the next-intl adapter ships. A scanner is inherently framework-specific,
which is exactly why it lives behind an interface instead of in ``core``.
"""

from __future__ import annotations

import abc
import bisect
import fnmatch
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

__all__ = [
    "Usage", "HardcodedString", "Scanner", "SKIP_DIR_PARTS", "SOFT_SKIP_PARTS",
    "path_is_skipped", "walk_tree", "line_number", "read_source_lines", "drop_brand_hits", "split_lines",
    "scan_file_hits",
]

SKIP_DIR_PARTS = (
    ".next", "node_modules", "__tests__", "dist", "build", ".turbo", ".git",
)

#: Path segments that are documentation or dev tooling, not shipped UI.
#: ``[scan] unskip`` can bring one of these paths back. The hard skips above
#: stay skipped.
SOFT_SKIP_PARTS = (
    "docs", "documentation", "scripts", "storybook", "__mocks__", "fixtures",
    "examples", "e2e", "cypress", "playwright", ".github", "experiments",
    # V-004: test trees dominate agent-hardcoded noise on django/flask corpora.
    "tests", "test", "testing",
    # Third-party copies shipped beside the UI.
    "vendor", "vendors", "third_party", "thirdparty", "3rdparty", "external_libs",
    # Mock and sample data shipped for previews and demos, not product copy.
    "sampledata", "sample_data", "mockdata", "mock_data", "mocks", "fakes",
    # Generated schema migrations (Django, Alembic, Knex): frozen copies of field labels, never shown (B12).
    "migrations",
    # Generators of docs and code, and Kubernetes-style ``hack/`` scripts: developer tooling (B23).
    "gen-docs", "gendocs", "docgen", "hack",
)

SKIP_FILE_SUFFIXES = (
    ".test.tsx", ".test.ts", ".test.jsx", ".test.js",
    ".spec.tsx", ".spec.ts", ".spec.jsx", ".spec.js",
    ".stories.tsx", ".stories.ts",
    ".d.ts",
    ".min.js", ".min.mjs", ".bundle.js",
)

SKIP_FILE_STEMS = ("readme", "changelog", "contributing")

_HARD_SKIP_LOW = frozenset(p.lower() for p in SKIP_DIR_PARTS)
_SOFT_SKIP_LOW = frozenset(p.lower() for p in SOFT_SKIP_PARTS)

#: Larger files are bundles or data, not hand-written UI source.
MAX_SOURCE_BYTES = 1_000_000
#: A file with a line this long whose lines average _MINIFIED_AVG is minified.
_MINIFIED_LINE = 2_000
_MINIFIED_AVG = 300

_NEWLINE = re.compile(r"\n")
_LINE_MEMO = threading.local()


def line_number(text: str, index: int) -> int:
    """1-based line of *index* in *text*. Line starts are computed once per text,
    so whole-file passes stay linear instead of counting newlines per hit."""
    memo = getattr(_LINE_MEMO, "value", None)
    if memo is None or memo[0] is not text:
        starts = [0]
        starts.extend(m.end() for m in _NEWLINE.finditer(text))
        memo = (text, starts)
        _LINE_MEMO.value = memo
    return bisect.bisect_right(memo[1], index)


def split_lines(text: str) -> list[str]:
    """Lines as editors and git count them: only ``\\n``, ``\\r\\n`` and ``\\r`` end a line.

    ``str.splitlines`` also breaks on form feeds, ``\\x85`` and ``\\u2028``, which shifts every later line number (M2).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def is_minified(lines: list[str]) -> bool:
    """One-line bundles: a very long line and a very long average line."""
    if not lines:
        return False
    if max(len(line) for line in lines) < _MINIFIED_LINE:
        return False
    return sum(len(line) for line in lines) / len(lines) >= _MINIFIED_AVG


def read_source_lines(
    path: Path, result: ScanResult | None = None, rel: str = "",
) -> list[str] | None:
    """Lines of one source file, or None when it should not be scanned.

    Oversized and minified files go to ``result.skipped``. Bytes that are not
    UTF-8 are replaced so the rest of the file is still scanned.
    """
    label = rel or path.as_posix()
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            if result is not None:
                result.skipped.append(f"{label}: too large")
            return None
        raw = path.read_bytes()
    except OSError as exc:
        if result is not None:
            result.unreadable.append(f"{label}: {type(exc).__name__}")
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        if result is not None:
            result.decode_fallback += 1
    lines = split_lines(text)
    if is_minified(lines):
        if result is not None:
            result.skipped.append(f"{label}: minified")
        return None
    return lines


#: A quoted literal made of ``\uXXXX`` escapes (with optional plain text between them).
_ESCAPED_LITERAL = re.compile(r"""(["'])((?:\\u[0-9a-fA-F]{4}|[^"'\\\n]|\\[^u\n]){0,200}?\\u[0-9a-fA-F]{4}(?:\\u[0-9a-fA-F]{4}|[^"'\\\n]|\\[^u\n]){0,200}?)\1""")
_ESC_CHAR = re.compile(r"\\u([0-9a-fA-F]{4})")


def relative_posix(path: Path, root: Path) -> str:
    """``path.relative_to(root).as_posix()``, by string prefix when *path* was built under *root* (the walk does that).

    M4: on Python 3.12 ``relative_to`` checks every parent of *root* and was about a tenth of scan CPU time.
    Raises ValueError, like ``relative_to``, when *path* is not below *root*.
    """
    s, r = str(path), str(root)
    n = len(r)
    if n and s.startswith(r) and len(s) > n and s[n] in "\\/" and r not in (".", ""):
        return s[n + 1:].replace("\\", "/")
    return path.relative_to(root).as_posix()


def scan_file_hits(scanner, path: Path, result: "ScanResult", scan_fn=None) -> list | None:
    """One file through the steps every scan loop shares (M2: ``Scanner._scan_all`` and ``agent-hardcoded``).

    Read with line numbers as editors count them, skip minified files (scanning a minified JS bundle's escaped text
    instead), run *scan_fn* (default ``scanner.scan_file``), apply ignore directives unless the scanner lints them,
    and drop repeats of the same ``(line, text)``. Counts go to *result*; the file's kept hits are appended to it and
    also returned (for per-file caches). Returns None when the file was not read.
    """
    try:
        rel = relative_posix(path, scanner.root)
    except ValueError:
        rel = path.as_posix()
    lines = read_source_lines(path, result, rel)
    if lines is None:
        if result.skipped and result.skipped[-1] == f"{rel}: minified" and path.suffix.lower() in (".js", ".mjs", ".cjs"):
            escaped_bundle_text(path, rel, result)
        return None
    result.files_scanned += 1
    before = len(result.hardcoded)
    (scan_fn or scanner.scan_file)(path, lines, result)
    hits = result.hardcoded[before:]
    if hits and getattr(scanner, "apply_directives", True):
        from .directives import apply_directives

        hits, dropped = apply_directives(lines, hits, getattr(scanner, "directive_aliases", True), rel)
        result.suppressed += dropped
    seen: set[tuple[str, int, str]] = set()
    kept = []
    for hit in hits:
        mark = (hit.file, hit.line, hit.text)
        if mark not in seen:
            seen.add(mark)
            kept.append(hit)
    result.hardcoded[before:] = kept
    return kept


def escaped_bundle_text(path: Path, rel: str, result: "ScanResult") -> None:
    """A minified bundle is skipped, except literals whose ``\\u`` escapes decode to text in a non-Latin script.

    Build tools escape CJK, Cyrillic or Arabic copy into ``"\\u63d2\\u4ef6\\u914d\\u7f6e"``; in a shipped bundle with no
    other source copy, that is the UI text. Latin-only literals stay skipped: a bundle is mostly library code.
    """
    from .prose import dominant_script

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    seen: set[str] = set()
    for m in _ESCAPED_LITERAL.finditer(text):
        decoded = _ESC_CHAR.sub(lambda e: chr(int(e.group(1), 16)), m.group(2))
        decoded = " ".join(decoded.split())
        letters = [ch for ch in decoded if ch.isalpha()]
        if len(letters) < 2 or decoded in seen or dominant_script(decoded) in ("", "latin"):
            continue
        seen.add(decoded)
        result.hardcoded.append(HardcodedString(
            decoded, rel, line_number(text, m.start()), confidence="medium",
            reason="escaped non-Latin text in a minified bundle; move it to the catalogue at its source",
        ))


def drop_brand_hits(result: ScanResult, root: Path) -> None:
    """Drop hits that are the project's own name (``Akadelist``, ``Akadelist —``).

    A product name is never translated; the project folder is the cheapest
    reliable source for it.
    """
    name = re.sub(r"[-_]+", " ", Path(root).resolve().name).strip().casefold()
    if len(name) < 3:
        return
    kept = []
    for hit in result.hardcoded:
        text = " ".join(hit.text.split()).casefold()
        rest = text[len(name):] if text.startswith(name) else None
        if rest is not None and not re.search(r"\w", rest):
            continue  # the name alone, maybe with punctuation ("Akadelist —")
        kept.append(hit)
    result.hardcoded = kept


def _posix(path: Path) -> str:
    return path.as_posix().lower()


def _token_in_path(token: str, posix: str) -> bool:
    """Whether *token* occurs in *posix* aligned to path-segment boundaries.

    The match must start at a segment start and end at a segment end or just
    before a file extension, so ``features/design`` does not match
    ``features/designSystem.tsx``.
    """
    start = posix.find(token)
    while start != -1:
        end = start + len(token)
        head_ok = start == 0 or token.startswith("/") or posix[start - 1] == "/"
        tail_ok = end == len(posix) or token.endswith("/") or posix[end] in "/."
        if head_ok and tail_ok:
            return True
        start = posix.find(token, start + 1)
    return False


#: ``commonTest``, ``androidTest``, ``UITests``, ``unitTest``: test source sets of Kotlin/Android/Swift/.NET projects.
_TEST_DIR = re.compile(r"(?:[a-z0-9](?:Test|Tests)|^(?:test|tests|unittests?|uitests?|xctest|androidtest|specs?)$)$")
#: ``FooTest.kt``, ``FooTests.swift``, ``foo_test.go``, ``foo_test.py``, ``FooSpec.scala``, ``Foo.Tests.cs``.
_TEST_FILE = re.compile(r"(?:[a-z0-9](?:Test|Tests|Spec)|_tests?|\.tests?)$")


def _is_test_path(path: Path) -> bool:
    parts = path.parts[:-1]
    if any(_TEST_DIR.search(p) or _TEST_DIR.search(p.lower()) for p in parts):
        return True
    return bool(_TEST_FILE.search(path.stem)) and path.suffix.lower() in {
        ".kt", ".java", ".swift", ".cs", ".go", ".py", ".scala", ".rb", ".rs", ".dart", ".cpp", ".cc", ".php", ".ex", ".exs",
    }


def path_is_skipped(
    path: Path,
    *,
    exclude: tuple[str, ...] = (),
    unskip: tuple[str, ...] = (),
    root: Path | None = None,
) -> bool:
    """Whether a source file is docs, tests, or dev tooling rather than UI.

    With *root*, only the part of the path below it is judged: a project that
    lives under a directory named ``docs`` or ``build`` must not skip itself.
    """
    if root is not None:
        try:
            path = PurePosixPath(relative_posix(path, root))
        except ValueError:
            pass
    posix = "/" + path.as_posix().lstrip("/")
    low = posix.lower()
    parts_low = {part.lower() for part in path.parts}
    if parts_low & _HARD_SKIP_LOW:
        return True
    if path.name.endswith(SKIP_FILE_SUFFIXES):
        return True
    stem = path.stem.lower()
    if stem in SKIP_FILE_STEMS or stem.split(".")[0] in SKIP_FILE_STEMS:
        return True
    if _is_test_path(path):
        return True
    if exclude and any(ex and _token_in_path(ex, posix) for ex in exclude):
        return True
    if unskip and any(tok and _token_in_path(tok, posix) for tok in unskip):
        return False
    if parts_low & _SOFT_SKIP_LOW:
        return True
    if any(seg in low for seg in ("/docs/", "/documentation/", "/scripts/")):
        return True
    return is_catalogue_file(path)


#: Directory names that hold translation catalogues in most frameworks (Laravel ``lang``, ``locales``, ``i18n``).
_CATALOGUE_DIRS = frozenset({"lang", "langs", "locale", "locales", "i18n", "l10n", "translations", "language", "languages"})
_EXTRA_LOCALES = frozenset({
    "zh", "tr", "uk", "sv", "vi", "th", "ca", "sk", "sl", "et", "lt", "lv", "sr", "ms", "bn", "ta", "te", "ur",
    "af", "sq", "hy", "az", "eu", "be", "bs", "cy", "ka", "kk", "mk", "mn", "ml", "si", "sw", "tl", "uz", "gl", "ga",
})


def _locale_like(name: str) -> bool:
    """``en``, ``es``, ``zh_cn``, ``pt-BR``, ``en-US``: a known primary language, optionally with a region."""
    from ..core.locales import known_locales

    head = name.lower().replace("_", "-").split("-")[0]
    if not (2 <= len(head) <= 3) or len(name) > 10:
        return False
    primary = {c.lower().split("-")[0] for c in known_locales()} | _EXTRA_LOCALES
    return head in primary


def is_catalogue_file(path: Path) -> bool:
    """A project's own translation file: below a ``lang``/``locales``/``i18n`` directory, named or nested by a locale code.

    ``resources/js/lang/en/form.js`` and ``lang/es.js`` are catalogues; ``lang/index.js`` and ``i18n/setup.ts`` are code.
    """
    if path.suffix.lower() == ".dart":
        # Flutter's generated per-language classes: ``l10n_ru.dart``, ``app_localizations_zh.dart``, ``messages_pt_BR.dart``.
        match = re.fullmatch(r"(?:\w+_)?(?:l10n|localizations|messages)_(\w{2,3}(?:_\w+)?)", path.stem)
        if match and _locale_like(match.group(1)):
            return True
    parts = path.parts[:-1]
    for i, part in enumerate(parts):
        if part.lower() in _CATALOGUE_DIRS:
            below = [*parts[i + 1:], path.stem.split(".")[0]]
            return any(_locale_like(seg) for seg in below)
    return False


_PRUNE_DIRS = _HARD_SKIP_LOW
_CASE_FOLD = os.name == "nt"


def walk_tree(scanner) -> list[list[Path]]:
    """Every file under each src dir, one ``os.walk`` per dir, hard-skip dirs pruned.

    Pruning only drops directories ``path_is_skipped`` would reject for every
    file below them, so results match the per-extension globs it replaces.
    Memoised on the scanner; ``Scanner.reset_tree`` forces a fresh walk.
    """
    cached = getattr(scanner, "_tree", None)
    if cached is not None:
        return cached
    tree: list[list[Path]] = []
    for rel in scanner.src_dirs:
        base = scanner.root / rel
        files: list[Path] = []
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d.lower() not in _PRUNE_DIRS]
                here = Path(dirpath)
                files.extend(here / name for name in filenames)
        tree.append(files)
    scanner._tree = tree
    return tree


def scanner_skips(scanner, path: Path) -> bool:
    """``path_is_skipped`` with the scanner's settings, memoised per walk (M4: each adapter and the literal pass asked
    again for the same files). ``Scanner.reset_tree`` clears the memo."""
    memo = scanner.__dict__.get("_skip_memo")
    settings = (scanner.root, scanner.exclude, scanner.unskip)
    if memo is None or memo[0] != settings:
        memo = (settings, {})
        scanner.__dict__["_skip_memo"] = memo
    known = memo[1].get(path)
    if known is None:
        known = path_is_skipped(path, exclude=scanner.exclude, unskip=scanner.unskip, root=scanner.root)
        memo[1][path] = known
    return known


def paths_with_suffixes(scanner, suffixes, *, skip_names: tuple[str, ...] = ()):
    """Yield walked files per suffix, sorted, in the order the globs used."""
    wanted = [suffix.lower() if _CASE_FOLD else suffix for suffix in suffixes]
    for files in walk_tree(scanner):
        # One pass over the tree, bucketed by suffix, instead of one per suffix.
        buckets: list[list[Path]] = [[] for _ in wanted]
        for p in files:
            name = p.name.lower() if _CASE_FOLD else p.name
            for i, suf in enumerate(wanted):
                if name.endswith(suf):
                    buckets[i].append(p)
        for hits in buckets:
            for path in sorted(hits):
                if path.name in skip_names:
                    continue
                if scanner_skips(scanner, path):
                    continue
                yield path


#: File types that usually carry UI copy but that no scanner here reads. Reported, never silently skipped.
UNSUPPORTED_UI_EXTENSIONS = frozenset({
    ".pug", ".jade", ".clj", ".groovy",
})


def count_unsupported(scanner) -> dict[str, int]:
    """Files in the scanned tree whose type may carry UI copy but is not read by any scanner."""
    counts: dict[str, int] = {}
    for files in walk_tree(scanner):
        for path in files:
            suffix = path.suffix.lower()
            if suffix in UNSUPPORTED_UI_EXTENSIONS and not scanner_skips(scanner, path):
                counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


@dataclass(frozen=True)
class Usage:
    namespace: str
    key: str
    file: str
    line: int
    component: str = "unknown"


@dataclass(frozen=True)
class HardcodedString:
    text: str
    file: str
    line: int
    reason: str = "user-visible text not routed through t()"
    confidence: str = "medium"  # "high" | "medium" | "low"
    key_hint: str = ""  # from `l10n: key=...` (ADR-106)
    note: str = ""
    max_length: int = 0
    dnt: bool = False
    namespace_hint: str = ""


@dataclass
class ScanResult:
    usages: list[Usage] = field(default_factory=list)
    hardcoded: list[HardcodedString] = field(default_factory=list)
    files_scanned: int = 0
    suppressed: int = 0  # hits dropped by in-code directives
    # Diagnostics so "zero findings" is not confused with "could not read".
    unreadable: list[str] = field(default_factory=list)
    unsupported_ext: int = 0
    skipped: list[str] = field(default_factory=list)  # too large / minified
    decode_fallback: int = 0  # files read with replaced non-UTF-8 bytes

    def by_namespace(self) -> dict[str, dict[str, list[dict]]]:
        """Group usages into the ``{ns: {key: [site, ...]}}`` artefact shape."""
        out: dict[str, dict[str, list[dict]]] = {}
        for u in self.usages:
            out.setdefault(u.namespace, {}).setdefault(u.key, []).append(
                {"file": u.file, "line": u.line, "component": u.component}
            )
        return out

    def diagnostics(self) -> dict:
        return {
            "filesScanned": self.files_scanned,
            "suppressed": self.suppressed,
            "unreadable": list(self.unreadable),
            "unreadableCount": len(self.unreadable),
            "unsupportedExt": self.unsupported_ext,
            "skipped": list(self.skipped),
            "skippedCount": len(self.skipped),
            "decodeFallback": self.decode_fallback,
            "usageCount": len(self.usages),
            "hardcodedCount": len(self.hardcoded),
        }


class Scanner(abc.ABC):
    """Reads a project's source tree."""

    def __init__(
        self,
        root: Path,
        src_dirs: list[str],
        *,
        exclude: list[str] | None = None,
        unskip: list[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.src_dirs = src_dirs
        # Path substrings to skip (e.g. "features/design", "TranslateWorkspace").
        self.exclude = tuple(str(p).replace("\\", "/") for p in (exclude or []) if str(p).strip())
        self.unskip = tuple(str(p).replace("\\", "/") for p in (unskip or []) if str(p).strip())
        self._tree = None
        #: Project-specific translate wrappers (``[scan] t_functions``): calls whose literal is already routed.
        self.t_functions: tuple[str, ...] = ()
        #: Files the project declares as shown text (``[scan] content_globs``), read by the content scanner.
        self.content_globs: tuple[str, ...] = ()

    @property
    def routing_note(self) -> str:
        """How an agent should route a literal through this framework."""
        return ""

    @property
    @abc.abstractmethod
    def file_glob(self) -> str:
        """Glob for the files this scanner understands, e.g. ``**/*.tsx``."""

    @abc.abstractmethod
    def scan_file(self, path: Path, lines: list[str], result: ScanResult) -> None:
        """Append findings for one file."""

    def reset_tree(self) -> None:
        """Forget the memoised directory walk and the per-scan project index (files changed on disk).

        M2: a long-lived scanner (web server, watch) used to keep the first scan's catalogue keys and Xcode targets.
        M3: those facts live in one ``project_index.ProjectIndex`` per scan.
        """
        self._tree = None
        self.__dict__.pop("_project_index", None)
        self.__dict__.pop("_skip_memo", None)
        for delegate in self.__dict__.get("_delegates", {}).values():
            delegate.reset_tree()

    def _glob_paths(self, base: Path, files: list[Path]):
        """Files under *base* matching ``file_glob``, sorted.

        ``**/*.ext`` and ``*.ext`` match on the file name over the pruned walk
        (no descent into node_modules and friends); any other glob keeps the
        plain ``Path.glob`` behaviour.
        """
        pattern = self.file_glob
        name_pat = pattern[3:] if pattern.startswith("**/") else pattern
        if "/" in name_pat or "**" in name_pat:
            return sorted(base.glob(pattern))
        fold = os.name == "nt"
        want = name_pat.lower() if fold else name_pat
        return sorted(
            p for p in files
            if fnmatch.fnmatchcase(p.name.lower() if fold else p.name, want)
        )

    def iter_files(self):
        trees = walk_tree(self)
        for rel, files in zip(self.src_dirs, trees):
            base = self.root / rel
            if not base.is_dir():
                continue
            for path in self._glob_paths(base, files):
                if scanner_skips(self, path):
                    continue
                yield path

    def scan(self) -> ScanResult:
        from .usage_calls import EXTRA_ROUTED

        token = EXTRA_ROUTED.set(frozenset(self.t_functions))
        try:
            return self._scan_all()
        finally:
            EXTRA_ROUTED.reset(token)

    def _scan_all(self) -> ScanResult:
        self.reset_tree()
        result = ScanResult()
        seen: set[Path] = set()
        for path in self.iter_files():
            seen.add(path)
            scan_file_hits(self, path, result)
        # Literal languages (Go, Python, …) are not owned by a framework adapter.
        from .literals import scan_unseen_literals
        scan_unseen_literals(self, result, seen)
        drop_brand_hits(result, self.root)
        return result

    #: Set False by ``scan --lint-directives`` so stale ignores stay visible.
    apply_directives = True
    directive_aliases = True
