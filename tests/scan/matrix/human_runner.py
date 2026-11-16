"""Score the human-language matrix: per (host, language, kind) was the phrase reported at medium or high?"""

from __future__ import annotations

import tempfile
import unicodedata
from pathlib import Path

from llm_localizator.scan import build_scanner

from .human_spec import GROUPS, HOSTS, KINDS, LANGS


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(text.split()))


def _core(phrase: str) -> str:
    """The phrase without trailing sentence punctuation, so a hit that dropped it still counts."""
    return phrase.rstrip(".!?;։۔。！？…")


def run_host(host: str) -> dict[str, dict[str, bool]]:
    """``{lang: {kind: found at >= medium}}`` for one host. One file per (language, kind): hits cannot satisfy each other."""
    fname, snippet = HOSTS[host]
    out: dict[str, dict[str, bool]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        index: dict[str, tuple[str, str]] = {}
        for lang, (_group, phrases) in LANGS.items():
            for kind in KINDS:
                phrase = phrases[kind]
                name = f"{Path(fname).stem}_{lang.replace('-', '_')}_{kind}{Path(fname).suffix}"
                (src / name).write_text(snippet.replace("@P@", phrase) + "\n", encoding="utf-8")
                index[f"src/{name}"] = (lang, kind)
        hits = build_scanner("source", root, ["src"]).scan().hardcoded
    for lang, (_g, _p) in LANGS.items():
        out[lang] = {kind: False for kind in KINDS}
    for hit in hits:
        key = index.get(hit.file)
        if key is None or hit.confidence == "low":
            continue
        lang, kind = key
        if _core(_norm(LANGS[lang][1][kind])) in _norm(hit.text):
            out[lang][kind] = True
    return out


def scores() -> dict[str, dict]:
    """Per host and per group: share of phrases found, with English as the reference."""
    table: dict[str, dict] = {}
    for host in HOSTS:
        cells = run_host(host)
        by_group: dict[str, list[bool]] = {g: [] for g in GROUPS}
        for lang, kinds in cells.items():
            by_group[LANGS[lang][0]].extend(kinds.values())
        table[host] = {
            "cells": cells,
            "groups": {g: (sum(v) / len(v) if v else None) for g, v in by_group.items()},
            "english": sum(cells["en"].values()) / len(KINDS),
        }
    return table


def run_negative(host: str) -> list[str]:
    """Languages whose developer-only sentence (a comment or a log call) was wrongly reported."""
    from .human_spec import NEGATIVE_HOSTS

    fname, variants = NEGATIVE_HOSTS[host]
    wrong: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        index: dict[str, tuple[str, str]] = {}
        for lang, (_group, phrases) in LANGS.items():
            for variant, template in variants.items():
                name = f"{Path(fname).stem}_{lang.replace('-', '_')}_{variant}{Path(fname).suffix}"
                (src / name).write_text(template.replace("@P@", phrases["sentence"]) + "\n", encoding="utf-8")
                index[f"src/{name}"] = (lang, variant)
        hits = build_scanner("source", root, ["src"]).scan().hardcoded
    for hit in hits:
        key = index.get(hit.file)
        if key and _core(_norm(LANGS[key[0]][1]["sentence"])) in _norm(hit.text):
            wrong.append(f"{key[0]}/{key[1]}")
    return sorted(set(wrong))


def _extra_phrases(lang: str, interp: str) -> dict[str, str]:
    from .human_spec import CHAR1, NATIVE_DIGITS

    p = LANGS[lang][1]
    out = {
        "interp": f"{_core(p['greet'])} {interp}",
        "mixed": f"{p['action']} Wi-Fi",
        "digits": f"{p['action']} {NATIVE_DIGITS.get(lang, '30')}",
        "nfd": unicodedata.normalize("NFD", p["label"]),
    }
    if lang in CHAR1:
        out["char1"] = CHAR1[lang]
    return out


def run_extra(host: str) -> dict[str, list[str]]:
    """Per extra kind, the languages whose text was not reported at medium or high."""
    from .human_spec import EXTRA_HOSTS

    fname, snippet, interp = EXTRA_HOSTS[host]
    wanted: dict[str, tuple[str, str, str]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        for lang in LANGS:
            for kind, phrase in _extra_phrases(lang, interp).items():
                name = f"{Path(fname).stem}_{lang.replace('-', '_')}_{kind}{Path(fname).suffix}"
                (src / name).write_text(snippet.replace("@P@", phrase) + "\n", encoding="utf-8")
                core = phrase.replace(interp, "").strip()
                wanted[f"src/{name}"] = (lang, kind, _norm(core.split(interp)[0]) if interp in phrase else _norm(core))
        hits = build_scanner("source", root, ["src"]).scan().hardcoded
    found: set[tuple[str, str]] = set()
    for hit in hits:
        key = wanted.get(hit.file)
        if key and hit.confidence != "low" and key[2].split()[0] in _norm(hit.text):
            found.add((key[0], key[1]))
    missing: dict[str, list[str]] = {}
    for lang_kind in {(v[0], v[1]) for v in wanted.values()} - found:
        missing.setdefault(lang_kind[1], []).append(lang_kind[0])
    return {k: sorted(v) for k, v in sorted(missing.items())}
