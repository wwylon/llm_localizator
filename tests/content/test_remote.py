"""Remote content contract, client, status, and write-back. No sockets."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from llm_localizator.content.client import ContentAPIError, ContentClient
from llm_localizator.content.contract import ContractError, classify, needs_write, parse_unit
from llm_localizator.content.translate import content_prompt
from llm_localizator.core.hash import src_hash
from llm_localizator.ops.content import op_content_translate
from llm_localizator.ops.status import op_status
from llm_localizator.ops.translate import op_translate
from llm_localizator.ops.types import StatusRequest, TranslateRequest
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.providers.null import NullProvider

ROOT = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["de", "pl"]

[collections.live]
kind = "remote"
"""


def _cfg(tmp_path: Path):
    path = tmp_path / ".llm-localize.toml"
    path.write_text(ROOT, encoding="utf-8")
    return load_config(path)


def _unit(**overrides):
    body = {
        "id": "club/abc/description",
        "source_locale": "pl",
        "source_text": "Turniej dla początkujących.",
        "translate": True,
        "note": "club description",
        "targets": {},
    }
    body.update(overrides)
    return parse_unit(body)


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class _Opener:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        if req.get_method() == "PUT":
            return _Body(b"{}")
        if not self.pages:
            raise AssertionError("no page left")
        return _Body(json.dumps(self.pages.pop(0)).encode())


def test_source_locale_is_required() -> None:
    with pytest.raises(ContractError, match="source_locale"):
        parse_unit({"id": "club/a/name", "source_text": "Open"})


def test_classify_skips_names_and_marks_author_language() -> None:
    name = _unit(id="club/abc/name", translate=False, source_text="Kraken Cup")
    cells = {c.locale: c.status for c in classify(name, ["en", "pl"])}
    assert cells == {"en": "skipped", "pl": "skipped"}

    prose = _unit()
    cells = {c.locale: c.status for c in classify(prose, ["en", "de", "pl"])}
    assert cells["pl"] == "source"
    assert cells["en"] == "missing"
    assert cells["de"] == "missing"


def test_hash_mismatch_is_stale_and_human_stays_locked() -> None:
    text = "Turniej dla początkujących."
    unit = _unit(targets={
        "de": {"status": "machine", "text": "old", "src_sha": "not-the-hash"},
        "en": {"status": "human_verified", "text": "Beginners", "src_sha": src_hash(text)},
    })
    by_locale = {c.locale: c for c in classify(unit, ["de", "en", "pl"])}
    assert by_locale["de"].status == "stale"
    assert by_locale["de"].locked is False
    assert by_locale["en"].status == "human"
    assert by_locale["en"].locked is True
    assert needs_write(by_locale["en"], force=False) is False
    assert needs_write(by_locale["en"], force=True) is True
    assert needs_write(by_locale["de"], force=False) is True


def test_prompt_uses_the_unit_source_language() -> None:
    prompt = content_prompt(_unit(), "de", domain="bridge")
    assert "from Polish to German" in prompt
    assert "from English" not in prompt


def test_client_calls_the_configured_host_not_localhost() -> None:
    opener = _Opener([{
        "units": [{
            "id": "club/abc/description",
            "source_locale": "pl",
            "source_text": "Cześć",
            "targets": {},
        }],
        "next_cursor": "p2",
    }, {"units": [], "next_cursor": None}])
    client = ContentClient("http://content.internal:9", "s3cret", opener=opener)
    units = client.list_units()
    assert [u.id for u in units] == ["club/abc/description"]
    assert "content.internal" in opener.calls[0].full_url
    assert opener.calls[0].full_url.startswith("http://content.internal:9/v1/units?")
    assert opener.calls[0].get_header("Authorization") == "Bearer s3cret"
    assert "cursor=p2" in opener.calls[1].full_url


def test_client_put_keeps_slashes_in_the_unit_id() -> None:
    opener = _Opener([])
    client = ContentClient("http://content.internal:9", "s3cret", opener=opener)
    client.put_translation("club/abc/description", "de", {"text": "x", "status": "machine"})
    assert opener.calls[0].full_url.endswith("/v1/units/club/abc/description/de")
    assert opener.calls[0].get_method() == "PUT"


def test_client_reports_http_errors_without_the_token() -> None:
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"denied"))

    client = ContentClient("http://content.internal:9", "s3cret", opener=opener)
    with pytest.raises(ContentAPIError, match="HTTP 401") as exc:
        client.list_units()
    assert "s3cret" not in str(exc.value)


def test_status_lists_source_language(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_URL", "http://content.internal:9")
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_TOKEN", "s3cret")
    unit = _unit()
    monkeypatch.setattr(
        "llm_localizator.ops.content.ContentClient.list_units",
        lambda self: [unit],
    )
    result = op_status(cfg, StatusRequest(collection="live"))
    assert result.ok
    assert result.data["kind"] == "remote"
    assert result.data["counts"]["missing"] == 2
    assert result.data["counts"]["source"] == 1
    assert any("source=pl" in line for line in result.lines)


def test_translate_writes_missing_and_skips_human(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_URL", "http://content.internal:9")
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_TOKEN", "s3cret")
    text = "Turniej dla początkujących."
    opener = _Opener([{
        "units": [{
            "id": "club/abc/description",
            "source_locale": "pl",
            "source_text": text,
            "note": "club description",
            "targets": {
                "en": {
                    "status": "human_verified",
                    "text": "Beginners",
                    "src_sha": src_hash(text),
                },
            },
        }],
    }])
    monkeypatch.setattr(
        "llm_localizator.ops.content.ContentClient",
        lambda *args, **kwargs: ContentClient(
            "http://content.internal:9", "s3cret", opener=opener,
        ),
    )
    result = op_content_translate(cfg, TranslateRequest(
        collection="live", locales=["en", "de"], dry_run=False, submit=False,
    ), "live", provider=NullProvider())
    assert result.exit_code == 0, result.summary
    puts = [c for c in opener.calls if c.get_method() == "PUT"]
    assert len(puts) == 1
    assert puts[0].full_url.endswith("/de")
    body = json.loads(puts[0].data.decode())
    assert body["status"] == "machine"
    assert body["source_locale"] == "pl"
    assert body["src_sha"] == src_hash(text)
    assert body["text"] == text


def test_remote_collection_rejects_a_token_in_toml(tmp_path: Path) -> None:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(ROOT + 'token = "nope"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="token"):
        load_config(path)


def test_dry_run_does_not_put(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_URL", "http://content.internal:9")
    monkeypatch.setenv("LLM_LOCALIZE_CONTENT_TOKEN", "s3cret")
    opener = _Opener([{"units": [{
        "id": "club/abc/description",
        "source_locale": "pl",
        "source_text": "Cześć",
        "targets": {},
    }]}])
    monkeypatch.setattr(
        "llm_localizator.ops.content.ContentClient",
        lambda *args, **kwargs: ContentClient(
            "http://content.internal:9", "s3cret", opener=opener,
        ),
    )
    result = op_translate(cfg, TranslateRequest(collection="live", dry_run=True, submit=False))
    assert result.ok
    assert all(c.get_method() != "PUT" for c in opener.calls)
    assert "would translate" in result.summary
