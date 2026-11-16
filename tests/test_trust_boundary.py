"""Phase 2 trust-boundary checks. Hermetic: no Ollama, no network."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from llm_localizator.catalog.flush_journal import FlushIntent, FlushJournal
from llm_localizator.catalog.io import atomic_write_text
from llm_localizator.ops.acknowledge import op_acknowledge_flush
from llm_localizator.projects.config import ProviderConfig
from llm_localizator.providers import ProviderError, project_provider
from llm_localizator.providers.anthropic import AnthropicProvider
from llm_localizator.providers.deepl import DeepLProvider


def test_atomic_write_text_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    atomic_write_text(path, "hello\n")
    atomic_write_text(path, "again\n")
    assert path.read_text(encoding="utf-8") == "again\n"


def test_cloud_provider_refuses_without_allow_cloud(tmp_path, make_config) -> None:
    cfg = make_config(
        tmp_path,
        provider=ProviderConfig(kind="anthropic"),
        allow_cloud=False,
    )
    try:
        project_provider(cfg)
    except ProviderError as exc:
        assert "allow_cloud" in str(exc)
    else:
        raise AssertionError("expected ProviderError")


def test_provider_repr_masks_secrets() -> None:
    assert "sk-secret" not in repr(AnthropicProvider(api_key="sk-secret"))
    assert "key-secret" not in repr(DeepLProvider(auth_key="key-secret"))


def test_acknowledge_flush_deletes_journal_and_writes_nothing(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    catalog = tmp_path / "messages" / "pl" / "app.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")
    journal = FlushJournal(cfg.state_root())
    journal.begin(FlushIntent(run_id="abc", started_at="2026-09-19T00:00:00+00:00"))
    result = op_acknowledge_flush(cfg)
    assert result.exit_code == 0
    assert not journal.path.exists()
    assert catalog.read_text(encoding="utf-8") == "{}\n"


def test_zip_import_rejects_too_many_entries() -> None:
    from llm_localizator.catalog.import_formats import explode_import_file

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for i in range(101):
            archive.writestr(f"{i}.csv", "namespace,key,source,pl\n")
    docs, error = explode_import_file("pack.zip", raw=buf.getvalue())
    assert docs == []
    assert error and "100" in error


def test_add_locale_keeps_a_comment(tmp_path, make_config) -> None:
    from llm_localizator.web.server import add_locale

    cfg_path = tmp_path / ".llm-localize.toml"
    cfg_path.write_text(
        '[project]\nname = "demo"\n\n'
        "# keep me\n"
        "[locales]\n"
        'targets = ["pl"]\n',
        encoding="utf-8",
    )
    cfg = make_config(tmp_path, config_path=cfg_path, targets=["pl"])
    st = type("S", (), {"cfg": cfg})()
    result = add_locale(st, "de", model="aya:8b")
    assert result["ok"] is True
    text = cfg_path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "de" in text
    assert 'aya:8b' in text or "aya:8b" in text


def test_session_token_rejects_a_post_without_it(tmp_path, make_config) -> None:
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from llm_localizator.web import build_state
    from llm_localizator.web.server import _Handler

    cfg = make_config(tmp_path)
    (tmp_path / "messages" / "en").mkdir(parents=True)
    (tmp_path / "messages" / "en" / "app.json").write_text(
        json.dumps({"greet": "Hello"}), encoding="utf-8",
    )
    handler = type("Handler", (_Handler,), {
        "states": {"testproj": build_state(cfg)},
        "default_project": "testproj",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ops/status",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("expected 403")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ops/status",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-LLM-Token": "secret-token",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
    finally:
        server.shutdown()
