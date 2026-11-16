"""Engine download (ADR-156, A4): index + files from a local HTTP stub, hashes, redirects, size cap, allowlist."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.engines import EngineError, _BUILTIN
from llm_localizator.engines.fetch import MAX_BYTES, build_index, fetch_engines, shipped_hashes
from llm_localizator.ops.engines import op_engine

FETCHED = (
    'id = "my-engine"\nname = "Mine"\nstatus = "smoke"\n[requires]\ncloud = false\nvram_gib = 4\n'
    '[config.provider]\nkind = "ollama"\n[config.locales.models]\ndefault = "llama3.2"\n'
)


def _sha(text: str | bytes) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode()).hexdigest()


@pytest.fixture
def site():
    """A tiny static server: ``site.files`` maps path -> bytes; ``site.redirects`` maps path -> location."""
    files: dict[str, bytes] = {}
    redirects: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path in redirects:
                self.send_response(302)
                self.send_header("Location", redirects[self.path])
                self.end_headers()
                return
            body = files.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    class Site:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/engines/"

        def put(self, engine_id: str, text: str, *, sha: str | None = None):
            files[f"/engines/{engine_id}.toml"] = text.encode()
            index = json.loads(files.get("/engines/index.json", b'{"engines": []}'))
            index["engines"].append({"id": engine_id, "file": f"{engine_id}.toml", "sha256": sha or _sha(text)})
            files["/engines/index.json"] = json.dumps(index).encode()

    instance = Site()
    instance.files, instance.redirects = files, redirects
    yield instance
    httpd.shutdown()


def test_index_of_the_shipped_engines_round_trips(tmp_path: Path) -> None:
    index = build_index(out=tmp_path)
    ids = {row["id"] for row in index["engines"]}
    assert {"claude-haiku", "local-8gb"} <= ids
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8")) == index
    assert {row["sha256"] for row in index["engines"]} == shipped_hashes()


def test_dry_run_writes_nothing_and_new_engine_is_unverified(site, tmp_path: Path) -> None:
    site.put("my-engine", FETCHED)
    rows = fetch_engines(site.url, dest=tmp_path)
    (row,) = rows
    assert (row.id, row.status, row.verified, row.written) == ("my-engine", "new", False, False)
    assert not list(tmp_path.glob("*.toml"))


def test_unverified_needs_accept_then_is_written(site, tmp_path: Path) -> None:
    site.put("my-engine", FETCHED)
    assert not fetch_engines(site.url, write=True, dest=tmp_path)[0].written
    assert fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0].written
    assert (tmp_path / "my-engine.toml").read_text(encoding="utf-8") == FETCHED
    assert fetch_engines(site.url, dest=tmp_path)[0].status == "same"


def test_engine_shipped_in_this_release_is_verified_and_written(site, tmp_path: Path, monkeypatch) -> None:
    """A file whose hash this package ships is trusted. Built-in ids are never replaced; copy one under a new id."""
    text = (_BUILTIN / "local-8gb.toml").read_text(encoding="utf-8")
    other = text.replace('id = "local-8gb"', 'id = "local-8gb-copy"')
    site.put("local-8gb-copy", other)
    monkeypatch.setattr("llm_localizator.engines.fetch.shipped_hashes", lambda: {_sha(other)})
    row = fetch_engines(site.url, write=True, dest=tmp_path)[0]
    assert row.verified and row.written


def test_builtin_ids_are_never_replaced(site, tmp_path: Path) -> None:
    site.put("claude-haiku", FETCHED.replace("my-engine", "claude-haiku"))
    row = fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0]
    assert row.status == "builtin" and not row.written and not list(tmp_path.glob("*.toml"))


def test_hash_mismatch_is_rejected(site, tmp_path: Path) -> None:
    site.put("my-engine", FETCHED, sha="0" * 64)
    row = fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0]
    assert row.status == "rejected" and "sha256" in row.detail and not list(tmp_path.glob("*.toml"))


def test_redirects_are_not_followed(site, tmp_path: Path) -> None:
    site.put("my-engine", FETCHED)
    del site.files["/engines/my-engine.toml"]
    site.redirects["/engines/my-engine.toml"] = "http://127.0.0.1:1/evil.toml"
    row = fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0]
    assert row.status == "rejected" and "redirect" in row.detail.lower()


def test_oversize_file_is_rejected(site, tmp_path: Path) -> None:
    big = FETCHED + "# " + "x" * (MAX_BYTES + 10) + "\n"
    site.put("my-engine", big)
    row = fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0]
    assert row.status == "rejected" and "larger" in row.detail


@pytest.mark.parametrize("bad", [
    '[config.privacy]\nallow_cloud = true\n',
    '[config.budget]\nmonthly_usd = 1000\n',
    "URL",
])
def test_forbidden_settings_are_rejected_even_when_hash_matches(site, tmp_path: Path, bad: str) -> None:
    # A URL goes inside the existing provider table (a second [config.provider] would be invalid TOML).
    text = (FETCHED.replace('kind = "ollama"', 'kind = "ollama"\nurl = "https://evil.example"')
            if bad == "URL" else FETCHED + bad)
    site.put("my-engine", text)
    row = fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path)[0]
    assert row.status == "rejected" and "not an engine setting" in row.detail
    assert not list(tmp_path.glob("*.toml"))


def test_bad_index_entries_and_non_https_are_refused(site, tmp_path: Path) -> None:
    site.files["/engines/index.json"] = json.dumps(
        {"engines": [{"id": "x", "file": "../escape.toml", "sha256": "0" * 64}]}).encode()
    assert fetch_engines(site.url, dest=tmp_path)[0].status == "rejected"
    with pytest.raises(EngineError, match="non-HTTPS"):
        fetch_engines("http://example.com/engines/", dest=tmp_path)


def test_fetched_engine_loads_but_never_shadows_a_builtin(site, tmp_path: Path, monkeypatch) -> None:
    from llm_localizator.engines import all_engines

    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    site.put("my-engine", FETCHED)
    fetch_engines(site.url, write=True, accept_unverified=True, dest=tmp_path / "home" / "engines")
    engines = all_engines()
    assert engines["my-engine"].source == "fetched" and engines["claude-haiku"].source == "builtin"


def test_op_engine_fetch_reports_and_never_raises(site, tmp_path: Path, monkeypatch, make_config) -> None:
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(tmp_path / "home"))
    site.put("my-engine", FETCHED)
    cfg = make_config(tmp_path)
    out = op_engine(cfg, "fetch", url=site.url)
    assert out.ok and "UNVERIFIED" in "\n".join(out.lines) and "Dry run" in "\n".join(out.lines)
    bad = op_engine(cfg, "fetch", url="http://127.0.0.1:1/engines/")
    assert not bad.ok and "fetch failed" in bad.summary
