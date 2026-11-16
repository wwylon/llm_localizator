"""Shared fixtures.

A deliberate divergence from the taskqueue exemplar, which has no conftest
(ADR-6). The ported suites all need the same "a project on disk plus a fake
provider" setup, and copying it four times is how the original tests ended up
with four subtly different versions of it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_localizator.catalog import JsonNestedCatalog
from llm_localizator.projects.config import ProjectConfig, ProviderConfig
from llm_localizator.providers import CompletionRequest, NullProvider

# fsync is the production default; it triples suite time on Windows.
os.environ.setdefault("LLM_LOCALIZE_FSYNC", "0")
os.environ.setdefault("LLM_LOCALIZE_SCRYPT_N", "1024")  # fast password hashing in tests

CATALOG_TEMPLATE = "messages/{locale}/{namespace}.json"


def _fast_shutdown_servers() -> None:
    """Tests run ``serve_forever`` in a thread and call ``shutdown()``, which waits up to one poll interval.

    The stdlib default of 0.5 s cost about half a second per server test (M5); 0.05 s keeps the same behaviour.
    """
    import socketserver

    original = socketserver.BaseServer.serve_forever
    if getattr(original, "_llm_fast", False):
        return

    def serve_forever(self, poll_interval: float = 0.05):
        return original(self, poll_interval)

    serve_forever._llm_fast = True
    socketserver.BaseServer.serve_forever = serve_forever


_fast_shutdown_servers()


@pytest.fixture(autouse=True)
def _isolate_engine_data_home(tmp_path_factory, monkeypatch):
    """Keep ADR-112 engine sidecars out of the real ~/.llm_localize during tests."""
    home = tmp_path_factory.mktemp("llm_localizator_home")
    monkeypatch.setenv("LLM_LOCALIZE_HOME", str(home))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_project(root: Path, source: dict, *, namespace: str = "app",
                  existing: dict | None = None, locale: str = "pl") -> None:
    write_json(root / "messages" / "en" / f"{namespace}.json", source)
    if existing is not None:
        write_json(root / "messages" / locale / f"{namespace}.json", existing)


def tagged(request: CompletionRequest) -> str:
    """Translate by tagging: batch requests return a JSON array, singles a string."""
    from llm_localizator.providers.null import _numbered_lines

    if "back to English" in request.prompt:
        line = request.prompt.strip().splitlines()[-1]
        if line.startswith("[xx] "):
            return line[5:].strip()
        return line.strip()

    if request.schema is not None:
        return json.dumps([f"[xx] {s}" for s in _numbered_lines(request.prompt)],
                          ensure_ascii=False)
    return "[xx] " + request.prompt.strip().splitlines()[-1]


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """An empty project with the standard layout."""
    (tmp_path / "messages" / "en").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def make_config():
    """Build a ProjectConfig pointing at a temp project."""

    def _make(root: Path, **overrides) -> ProjectConfig:
        defaults = dict(
            root=root,
            name="testproj",
            source_locale="en",
            # Keep sidecars inside the temp project (ADR-112 production default is engine).
            data_home="project",
            catalog_format="json-nested",
            catalog_path=CATALOG_TEMPLATE,
            targets=["pl"],
            models={"default": "testmodel"},
            provider=ProviderConfig(kind="null"),
            domain="a test application",
            state_dir=root / "messages" / ".state",
            # Hermetic suites translate tiny catalogues; production default is 50.
            translate_min_keys=0,
            # The fake provider answers in tagged English; a soft retry would double its calls.
            translate_soft_retry=False,
            translate_max_consecutive_rejects=0,
        )
        defaults.update(overrides)
        return ProjectConfig(**defaults)

    return _make


@pytest.fixture
def make_catalog():
    def _make(cfg: ProjectConfig) -> JsonNestedCatalog:
        return JsonNestedCatalog(cfg.root, cfg.catalog_path, cfg.source_locale)

    return _make


@pytest.fixture
def null_provider() -> NullProvider:
    """Echoes each source string back, so routing and plumbing are observable."""
    return NullProvider()


@pytest.fixture
def silent():
    """A reporter that swallows pipeline progress output."""
    return lambda _msg: None


@pytest.fixture
def mini_fixture() -> Path:
    """The curated hermetic catalogue committed under tests/fixtures/mini."""
    return Path(__file__).parent / "fixtures" / "mini"
