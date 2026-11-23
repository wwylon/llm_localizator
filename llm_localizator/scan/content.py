"""Text kept in content and manifest files: Markdown pages, TOML menus, extension manifests, Info.plist (ADR-145).

* **Markdown** under content-like paths (``content/``, ``posts/``, ``pages/``, ``blog/``, ``*.html.md`` templates):
  front-matter values for text keys (``title``, ``description``, ``label`` …), list items under them, and the prose of the
  body (headings, paragraphs, list items, table cells). Code fences, shortcodes, raw HTML and README-style project docs are
  skipped.
* **TOML** under ``config/``, ``data/``, ``content/``: ``name = "Home"``, ``title``, ``label``, ``description`` …
* **JSON manifests**: a VS Code ``package.json`` (``contributes``: command titles, setting descriptions), a web-extension or
  PWA ``manifest.json`` (``description``, ``name``). ``%key%`` and ``__MSG_key__`` values are already routed.
* **Info.plist**: ``NS…UsageDescription`` and display-name strings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from .base import HardcodedString, ScanResult, relative_posix
from .prose import LabelWordMatcher, grade, is_lone_word, is_short_label
from .usage_calls import routed_re

__all__ = ["scan_content_file"]

_TEXT_KEYS = (
    "title|subtitle|description|summary|label|content|name|alt|image_alt|caption|heading|button|text|bulletpoints|"
    "tagline|excerpt|markdownDescription|shortTitle|category|displayName|short_name|placeholder|tooltip"
)
_DOC_NAMES = re.compile(r"^(?:readme|changelog|changes|license|licence|contributing|security|code_of_conduct|agents|claude|skill|backers|authors|notice|todo)", re.I)
#: ``resources/`` and ``templates/``: Markdown a bot or server sends at run time (tag texts, reply templates).
_CONTENT_DIRS = {"content", "posts", "_posts", "pages", "blog", "articles", "stories", "docs_site", "resources", "templates"}
_TOML_DIRS = {"config", "data", "content", "i18n_data"}
_LABEL_WORD = LabelWordMatcher(2, 30)
_FM_KV = re.compile(rf"""^\s*(?:{_TEXT_KEYS})\s*[:=]\s*(?P<v>.+?)\s*$""", re.I)
_FM_ITEM = re.compile(r"^\s*-\s+(?P<v>.+?)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_MARKS = re.compile(r"(\*\*|__|\*|_|`)")
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+|^\s*>+\s*")
_PLIST_PAIR = re.compile(
    r"<key>(NS\w*UsageDescription|CFBundleDisplayName|UTTypeDescription|CFBundleTypeName)</key>\s*<string>([^<]*)</string>")
_ROUTED = routed_re("content_value")


def _clean_value(raw: str) -> str:
    value = raw.strip().rstrip(",")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return " ".join(value.replace('\\"', '"').split())


def _report(result: ScanResult, rel: str, line: int, text: str, where: str) -> None:
    if not text or _ROUTED.match(text) or not any(ch.isalpha() for ch in text):
        return
    if text.startswith(("http://", "https://", "/", "./", "#", "<", "{")) or re.fullmatch(r"[\w./-]+\.\w{1,5}", text):
        return
    if re.search(r"lorem ipsum|dolor sit amet|consectetur adipi", text, re.I):
        return  # placeholder copy of a demo site
    conf = grade(text, "none", label=(_LABEL_WORD.match, is_lone_word, is_short_label))
    if conf is None:
        return
    if conf == "high" and len(text.split()) < 3:
        conf = "medium"  # short prose in a content file is often a heading or a menu entry
    result.hardcoded.append(HardcodedString(
        text, rel, line, reason=f"{where} holds user-visible text; keep it in a catalogue or per-language content file",
        confidence=conf,
    ))


def _markdown_applies(path: Path) -> bool:
    if _DOC_NAMES.match(path.stem):
        return False
    parts = {p.lower() for p in path.parts[:-1]}
    return bool(parts & _CONTENT_DIRS) or path.stem.lower().endswith(".html")


def _scan_markdown(rel: str, lines: list[str], result: ScanResult) -> None:
    index = 0
    if lines and lines[0].strip() in {"---", "+++"}:
        fence = lines[0].strip()
        index = 1
        in_list_key = False
        while index < len(lines) and lines[index].strip() != fence:
            line = lines[index]
            kv = _FM_KV.match(line)
            if kv:
                value = kv.group("v")
                in_list_key = value in {"", "|", ">"} or value.startswith("[")
                if value.startswith("["):
                    for item in re.findall(r"""["']([^"']+)["']""", value):
                        _report(result, rel, index + 1, _clean_value(item), "front matter")
                elif value not in {"", "|", ">"}:
                    _report(result, rel, index + 1, _clean_value(value), "front matter")
            elif in_list_key and (item := _FM_ITEM.match(line)):
                _report(result, rel, index + 1, _clean_value(item.group("v")), "front matter")
            index += 1
        index += 1
    in_code = False
    for number in range(index, len(lines)):
        raw = lines[number]
        if _FENCE.match(raw):
            in_code = not in_code
            continue
        if in_code or not raw.strip() or raw.lstrip().startswith(("<", "|---", "---", "***", "[//]", "{{<", "{{%")):
            continue
        text = _SHORTCODE.sub(" ", raw)
        text = _LIST_MARK.sub("", text.strip())
        text = re.sub(r"^#{1,6}\s+", "", text)
        text = _MD_LINK.sub(lambda m: m.group(1), text)
        text = " ".join(_MD_MARKS.sub("", text).split())
        if text.startswith("|"):
            for cell in (c.strip() for c in text.strip("|").split("|")):
                _report(result, rel, number + 1, cell, "Markdown table")
            continue
        _report(result, rel, number + 1, text, "Markdown content")


def _scan_toml(rel: str, lines: list[str], result: ScanResult) -> None:
    for number, line in enumerate(lines, 1):
        kv = _FM_KV.match(line)
        if kv and not line.lstrip().startswith("#"):
            value = kv.group("v")
            if value[:1] in "\"'":
                _report(result, rel, number, _clean_value(value), "TOML data")


#: YAML text keys: the content set plus OpenAPI ``summary``.
_YAML_KV = re.compile(rf"""^\s*(?:-\s+)?(?:{_TEXT_KEYS}|summary)\s*:\s*(?P<v>.*?)\s*$""", re.I)


def _scan_yaml(rel: str, lines: list[str], result: ScanResult) -> None:
    """Text-key values of a declared YAML file, including ``>``/``|`` block scalars (joined into one message)."""
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        kv = _YAML_KV.match(line)
        if not kv or line.lstrip().startswith("#"):
            continue
        value = kv.group("v")
        if value[:1] in (">", "|"):
            indent = len(line) - len(line.lstrip())
            start, body = index + 1, []
            while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent):
                body.append(lines[index].strip())
                index += 1
            _report(result, rel, start, " ".join(" ".join(body).split()), "YAML text")
        elif value and value[0] not in "&*[{":
            _report(result, rel, index, _clean_value(value), "YAML text")


def _walk_json(node, path: tuple, found: list[tuple[str, str]]) -> None:
    keys = {"title", "description", "markdownDescription", "shortTitle", "category", "label", "tooltip", "displayName"}
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and key in keys:
                found.append((key, value))
            elif key == "enumDescriptions" and isinstance(value, list):
                found.extend((key, v) for v in value if isinstance(v, str))
            else:
                _walk_json(value, (*path, key), found)
    elif isinstance(node, list):
        for item in node:
            _walk_json(item, path, found)


def _scan_json_manifest(rel: str, path: Path, lines: list[str], result: ScanResult) -> None:
    text = "\n".join(lines)
    try:
        data = json.loads(text)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    found: list[tuple[str, str]] = []
    if path.name == "package.json":
        if "contributes" not in data and "activationEvents" not in data:
            return
        if isinstance(data.get("description"), str):
            found.append(("description", data["description"]))
        if isinstance(data.get("displayName"), str):
            found.append(("displayName", data["displayName"]))
        _walk_json(data.get("contributes", {}), (), found)
    elif path.name == "manifest.json":
        for key in ("description", "name", "short_name"):
            if isinstance(data.get(key), str):
                found.append((key, data[key]))
    else:
        return
    for _key, value in found:
        clean = " ".join(value.split())
        line = next((i for i, row in enumerate(lines, 1) if value[:40].replace("\\", "") in row.replace("\\", "")), 1)
        _report(result, rel, line, clean, "extension or app manifest")


#: Keys of a form or widget definition whose string value is a caption (``{"type": "spinbox", "label": "Cargo"}``).
_UI_JSON_KEYS = frozenset({
    "label", "heading", "placeholder", "tooltip", "caption", "helperText", "hint", "buttonText", "subtitle",
})
#: Folders of translation files, which are catalogues, not hardcoded text.
_JSON_CATALOGUE_DIRS = frozenset({"locales", "locale", "i18n", "lang", "languages", "translations", "node_modules"})
_JSON_SKIP_NAMES = frozenset({
    "package.json", "package-lock.json", "tsconfig.json", "composer.json", "manifest.json", "angular.json", "app.json",
})


def _walk_ui_config(node, found: list[str]) -> None:
    if isinstance(node, dict):
        has_type = "type" in node
        for key, value in node.items():
            if isinstance(value, str) and (key in _UI_JSON_KEYS or (key == "name" and has_type)):
                found.append(value)
            elif key == "options" and has_type and isinstance(value, list):
                found.extend(v for v in value if isinstance(v, str))
            else:
                _walk_ui_config(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_ui_config(item, found)


def _scan_json_ui_config(rel: str, path: Path, lines: list[str], result: ScanResult) -> None:
    """A JSON file that defines screens or forms (``label``, ``heading``, ``options`` next to a widget ``type``).

    Only when the file holds at least five such captions, so a data file with one ``label`` key is left alone.
    """
    if path.name.lower() in _JSON_SKIP_NAMES or {p.lower() for p in path.parts[:-1]} & _JSON_CATALOGUE_DIRS:
        return
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return
    found: list[str] = []
    _walk_ui_config(data, found)
    if len(found) < 5:
        return
    for value in dict.fromkeys(found):
        clean = " ".join(value.split())
        line = next((i for i, row in enumerate(lines, 1) if value[:40].replace("\\", "") in row.replace("\\", "")), 1)
        _report(result, rel, line, clean, "config-driven UI text (JSON)")


_MKDOCS_TOP = re.compile(r"^(?:site_name|site_description)\s*:\s*(?P<v>.+?)\s*$")
_MKDOCS_NAV = re.compile(r"""^\s*-\s+(?P<label>[^:#\n]+?)\s*:(?:\s|$)""")


def _scan_mkdocs(rel: str, lines: list[str]) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    in_nav = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        top = _MKDOCS_TOP.match(line)
        if top:
            found.append((number, _clean_value(top.group("v")), "mkdocs site text"))
        if re.match(r"^nav\s*:", line):
            in_nav = True
            continue
        if in_nav:
            if line and not line[0].isspace() and not line.startswith("-"):
                in_nav = False
                continue
            nav = _MKDOCS_NAV.match(line)
            if nav:
                found.append((number, nav.group("label").strip().strip("\"'"), "mkdocs navigation label"))
    return found


def matches_content_glob(scanner, path: Path) -> bool:
    """``[scan] content_globs``: files the project declares as shown text (opt-in; OpenAPI docs, bot YAML)."""
    globs = getattr(scanner, "content_globs", ()) or ()
    if not globs:
        return False
    try:
        rel = path.relative_to(scanner.root)
    except ValueError:
        return False
    return any(rel.match(g) or PurePosixPath(rel.as_posix()).match(g) for g in globs)


def scan_content_file(scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    rel = relative_posix(path, scanner.root)
    suffix = path.suffix.lower()
    declared = matches_content_glob(scanner, path)
    if suffix in {".md", ".markdown"}:
        # Judge the path below the project root (M2: a project inside a folder named ``content`` matched every file).
        if declared or _markdown_applies(Path(rel)):
            _scan_markdown(rel, lines, result)
    elif suffix in {".yml", ".yaml"}:
        if declared:
            _scan_yaml(rel, lines, result)
        elif path.name.lower() in {"mkdocs.yml", "mkdocs.yaml"}:
            for number, text, kind in _scan_mkdocs(rel, lines):
                _report(result, rel, number, text, kind)
    elif suffix == ".toml":
        if declared or {p.lower() for p in path.parts[:-1]} & _TOML_DIRS:
            _scan_toml(rel, lines, result)
    elif suffix == ".json":
        if path.name in {"package.json", "manifest.json"} and len(lines) < 20000:
            _scan_json_manifest(rel, path, lines, result)
        elif len(lines) < 20000:
            _scan_json_ui_config(rel, path, lines, result)
    elif suffix == ".plist":
        text = "\n".join(lines)
        for match in _PLIST_PAIR.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            _report(result, rel, line, " ".join(match.group(2).split()), "Info.plist")
