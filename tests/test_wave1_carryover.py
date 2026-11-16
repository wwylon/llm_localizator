"""Wave 1 carry-overs: webhook SSRF filter, undecodable .strings must not read as empty."""

from __future__ import annotations

import pytest

from llm_localizator.ops.notify import notify_webhook, validate_webhook_url


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/hook",
    "http://192.168.1.2/hook",
    "http://0.0.0.0/hook",
    "http://[fe80::1]/hook",
])
def test_webhook_rejects_non_public_targets(url) -> None:
    assert validate_webhook_url(url)


def test_webhook_allows_loopback_and_public_names() -> None:
    assert validate_webhook_url("http://127.0.0.1:5678/hook") is None
    assert validate_webhook_url("https://hooks.example.com/x") is None


def test_webhook_resolve_dns_rejects_loopback_hostname(monkeypatch) -> None:
    import ipaddress

    from llm_localizator.ops import notify as notify_mod

    monkeypatch.setattr(
        notify_mod,
        "_resolve_host_ips",
        lambda host: [ipaddress.ip_address("127.0.0.1")],
    )
    assert validate_webhook_url("https://evil.example/hook", resolve_dns=True)
    assert validate_webhook_url("https://evil.example/hook", resolve_dns=False) is None


def test_webhook_does_not_follow_redirects(monkeypatch) -> None:
    import ipaddress
    import urllib.request

    from llm_localizator.ops import notify as notify_mod

    seen = {}

    class Opener:
        def open(self, req, timeout=0):
            seen["handlers"] = True
            raise OSError("stop")

    def build_opener(*handlers):
        seen["redirect_blocked"] = any(
            getattr(h, "redirect_request", None) and not isinstance(h, type) for h in handlers
        )
        return Opener()

    monkeypatch.setattr(
        notify_mod,
        "_resolve_host_ips",
        lambda host: [ipaddress.ip_address("8.8.8.8")],
    )
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    notify_webhook("https://hooks.example.com/x", {"a": 1})
    assert seen.get("handlers")


def test_undecodable_strings_file_raises(tmp_path) -> None:
    from llm_localizator.catalog.ios_strings import IosStringsCatalog

    p = tmp_path / "Localizable.strings"
    p.write_bytes(b"\xff\xfe\x00\xd8garbage\x00")  # lone surrogate: invalid in every tried codec
    with pytest.raises((ValueError, RuntimeError, OSError)):
        IosStringsCatalog._parse_file(p)


def test_po_bom_and_extra_escapes(tmp_path) -> None:
    from llm_localizator.catalog.gettext_po import GettextPoCatalog, parse_po

    p = tmp_path / "a.po"
    p.write_bytes('﻿# c\nmsgid "k"\nmsgstr "x\x41\101\a"\n'.encode("utf-8"))
    entries = GettextPoCatalog(tmp_path, "a.po")._parse_po_file(p)[0]
    assert entries[0].msgid == "k"
    assert entries[0].msgstr == "xAA\x07"
    assert parse_po(r'msgid "q"' + "\n" + r'msgstr "it\'s"' + "\n")[0].msgstr == "it's"


def test_android_unescapes_tab_and_unicode() -> None:
    from llm_localizator.catalog.android_xml import _unescape

    assert _unescape(r"a\tb\u0041") == "a\tbA"


def test_tm_compact_keeps_entries_appended_by_another_process(tmp_path) -> None:
    from llm_localizator.catalog.tm import TranslationMemory

    a = TranslationMemory(tmp_path)
    a.record(locale="pl", source="Hello", text="Hi", model="m")
    a.exact("pl", "Hello")  # warm a's in-memory index
    b = TranslationMemory(tmp_path)  # a second process
    b.record(locale="pl", source="Bye", text="Pa", model="m")
    a.compact("pl")
    assert TranslationMemory(tmp_path).exact("pl", "Bye") is not None


def test_review_queue_sees_tickets_written_by_another_instance(tmp_path) -> None:
    from llm_localizator.catalog.review_queue import ReviewQueue

    q1 = ReviewQueue(tmp_path)
    assert q1.open_tickets("pl") == []  # caches the empty list
    (tmp_path / "pl.jsonl").write_text(
        '{"id": "t1", "locale": "pl", "key": "k", "status": "open"}' + chr(10), encoding="utf-8")
    assert [t.id for t in q1.open_tickets("pl")] == ["t1"]


def test_line_number_matches_count_semantics() -> None:
    # The lexers call base.line_number directly (M3 removed the literals._line_of alias).
    from llm_localizator.scan.base import line_number

    text = "a\nbb\n\nccc\n"
    for i in range(len(text) + 1):
        assert line_number(text, i) == text.count("\n", 0, i) + 1
