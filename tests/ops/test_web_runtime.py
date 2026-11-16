"""`llm-localizator runtime` and `check-keys` (plan Part C, C5; ADR-118)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.catalog import build_catalog
from llm_localizator.ops.source_ops import op_pseudo
from llm_localizator.ops.types import PseudoRequest
from llm_localizator.ops.web_runtime import op_check_keys, op_runtime
from llm_localizator.projects import load_config
from llm_localizator.web_runtime import RUNTIME_FILE, runtime_version, shipped_version

SOURCE = {
    "nav.search": "Search",
    "nav.help": "Help",
    "docs.count": "{n, plural, one {# doc} other {# docs}}",
    "filter.kind.image": "Images",
    "filter.kind.video": "Videos",
    "never.used": "Orphan",
}

APP_JS = """/* Usage examples in a doc comment do not count:
 *   i18n.t('doc.example.key')
 */
// games/*.js load first; this line comment must not open a block comment
const a = i18n.t('nav.search');
const b = i18n.t("docs.count", { n });
const c = t('nav.missing_one');
const d = i18n.t(`filter.kind.${kind}`);
const e = i18n.t(name);
const f = t('plain');  // bare t() with an undotted key is not a key
el.setAttribute('data-i18n-title', 'nav.help');
"""

INDEX_HTML = """<!-- <b data-i18n="comment.key"></b> -->
<button data-i18n="nav.search">Search</button>
<input data-i18n-placeholder="nav.gone" placeholder="Find">
"""


@pytest.fixture
def consumer(tmp_path: Path, make_config):
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "app.js").write_text(APP_JS, encoding="utf-8")
    (web / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    cfg = make_config(
        tmp_path,
        name="demo",
        catalog_format="json-flat",
        catalog_path="locales/{locale}.json",
        targets=["pl"],
        frozen=["zh"],
        scan_src_dirs=["web"],
        web_runtime_path="web/js",
        state_dir=tmp_path / ".state",
    )
    return cfg


# ----------------------------------------------------------------- runtime


def test_shipped_runtime_has_a_version_header() -> None:
    text = RUNTIME_FILE.read_text(encoding="utf-8")
    assert runtime_version(text) == shipped_version()
    assert f"var VERSION = '{shipped_version()}'" in text


def test_install_writes_runtime_and_config_once(consumer) -> None:
    result = op_runtime(consumer, "install")
    assert result.ok and result.exit_code == 0, result.summary
    target = consumer.root / "web" / "js" / "i18n.js"
    assert target.read_bytes() == RUNTIME_FILE.read_bytes()
    config = consumer.root / "web" / "js" / "i18n.config.js"
    text = config.read_text(encoding="utf-8")
    assert "storageKey: 'demo_lang'" in text
    assert "locales: ['en', 'pl', 'zh']" in text
    assert "project: 'demo'" in text
    config.write_text("// mine\n", encoding="utf-8")
    again = op_runtime(consumer, "install")
    assert again.ok and "already up to date" in again.summary
    assert config.read_text(encoding="utf-8") == "// mine\n"


def test_check_reports_missing_modified_outdated_and_current(consumer) -> None:
    assert op_runtime(consumer, "check").exit_code == 1
    assert op_runtime(consumer, "check").data["state"] == "missing"
    op_runtime(consumer, "install")
    assert op_runtime(consumer, "check").exit_code == 0
    target = consumer.root / "web" / "js" / "i18n.js"
    # A CRLF checkout of the same file is not a local edit.
    target.write_bytes(RUNTIME_FILE.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert op_runtime(consumer, "check").data["state"] == "current"
    target.write_text(target.read_text(encoding="utf-8") + "\n// local hack\n", encoding="utf-8")
    assert op_runtime(consumer, "check").data["state"] == "modified"
    old = RUNTIME_FILE.read_text(encoding="utf-8").replace(
        f"web runtime v{shipped_version()}", "web runtime v0.0.1", 1)
    target.write_text(old, encoding="utf-8")
    check = op_runtime(consumer, "check")
    assert check.exit_code == 1 and check.data["installed"] == "0.0.1"
    assert "v0.0.1 installed" in check.summary
    update = op_runtime(consumer, "update")
    assert update.ok and "was v0.0.1" in update.summary
    assert op_runtime(consumer, "check").exit_code == 0


def test_foreign_file_needs_force_and_update_needs_install(consumer) -> None:
    assert op_runtime(consumer, "update").exit_code == 1
    target = consumer.root / "web" / "js" / "i18n.js"
    target.parent.mkdir(parents=True)
    target.write_text("window.i18n = {};\n", encoding="utf-8")
    assert op_runtime(consumer, "check").data["state"] == "foreign"
    refused = op_runtime(consumer, "install")
    assert refused.exit_code == 1 and "--force" in refused.summary
    assert target.read_text(encoding="utf-8") == "window.i18n = {};\n"
    assert op_runtime(consumer, "install", force=True).ok
    assert op_runtime(consumer, "check").exit_code == 0


def test_runtime_path_must_be_configured_and_inside_root(consumer, make_config, tmp_path) -> None:
    bare = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json")
    assert op_runtime(bare, "check").exit_code == 2
    escape = op_runtime(consumer, "install", path="../outside.js")
    assert escape.exit_code == 2 and "outside" in escape.summary
    explicit = op_runtime(consumer, "install", path="static/runtime.js")
    assert explicit.ok and (consumer.root / "static" / "runtime.js").is_file()


def test_runtime_path_is_read_from_toml(tmp_path: Path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text("{}", encoding="utf-8")
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text(
        '[project]\nname = "t"\nsource_locale = "en"\n[catalog]\nformat = "json-flat"\n'
        'path = "locales/{locale}.json"\n[locales]\ntargets = ["pl"]\n[web]\nruntime_path = "static/js"\n',
        encoding="utf-8",
    )
    assert load_config(toml).web_runtime_path == "static/js"


# -------------------------------------------------------------- check-keys


def test_check_keys_reports_missing_unused_and_dynamic(consumer) -> None:
    result = op_check_keys(consumer, qa=False)
    data = result.data
    assert set(data["missing"]) == {"nav.missing_one", "nav.gone"}
    assert data["missing"]["nav.gone"] == ["web/index.html:3"]
    # Comment examples and undotted bare t() calls are not usage.
    assert "doc.example.key" not in data["missing"] and "comment.key" not in data["missing"]
    assert "plain" not in data["missing"]
    # The template-literal prefix covers both filter.kind.* keys.
    assert data["dynamic_prefixes"] == ["filter.kind."]
    assert data["unused"] == ["never.used"]
    assert len(data["dynamic_sites"]) == 1
    assert result.exit_code == 1 and not result.ok


def test_check_keys_passes_when_clean_and_strict_fails_on_unused(consumer) -> None:
    (consumer.root / "web" / "app.js").write_text(
        "i18n.t('nav.search'); i18n.t('nav.help'); i18n.t('docs.count', {n});\n"
        "i18n.t('filter.kind.' + kind); i18n.t('never.used');\n", encoding="utf-8")
    (consumer.root / "web" / "index.html").write_text("<p>x</p>\n", encoding="utf-8")
    clean = op_check_keys(consumer, qa=False)
    assert clean.ok and clean.exit_code == 0, clean.lines
    assert clean.data["dynamic_prefixes"] == ["filter.kind."]
    (consumer.root / "web" / "app.js").write_text("i18n.t('nav.search');\n", encoding="utf-8")
    assert op_check_keys(consumer, qa=False).exit_code == 0
    assert op_check_keys(consumer, qa=False, strict=True).exit_code == 1


def test_installed_runtime_is_not_counted_as_usage(consumer) -> None:
    op_runtime(consumer, "install")
    data = op_check_keys(consumer, qa=False).data
    assert not any(site.startswith("web/js/") for sites in data["missing"].values() for site in sites)


def test_qa_locale_staleness(consumer) -> None:
    consumer.qa_locales = ["en-XX"]
    missing = op_check_keys(consumer).data["qa"]
    assert missing[0]["state"] == "missing"
    assert op_pseudo(consumer, PseudoRequest(locale="en-XX")).ok
    current = op_check_keys(consumer).data["qa"][0]
    assert current["state"] == "current", current
    # en.json grows: the key set differs.
    grown = dict(SOURCE, **{"nav.new": "New"})
    (consumer.root / "locales" / "en.json").write_text(json.dumps(grown), encoding="utf-8")
    row = op_check_keys(consumer).data["qa"][0]
    assert row["state"] == "stale" and row["missing"] == 1
    # Same keys, changed English text: the content differs.
    assert op_pseudo(consumer, PseudoRequest(locale="en-XX")).ok
    grown["nav.help"] = "Help and support"
    (consumer.root / "locales" / "en.json").write_text(json.dumps(grown), encoding="utf-8")
    row = op_check_keys(consumer).data["qa"][0]
    assert row["state"] == "stale" and row["changed"] == 1 and row["missing"] == 0


def test_unconfigured_qa_locale_without_a_file_is_skipped(consumer) -> None:
    catalog = build_catalog(consumer.catalog_format, consumer.root, consumer.catalog_path, "en")
    assert catalog.load("en-XX", None) == {}
    assert op_check_keys(consumer).data["qa"] == []


def test_check_keys_needs_src_dirs(consumer) -> None:
    consumer.scan_src_dirs = []
    assert op_check_keys(consumer).exit_code == 2


def test_check_keys_reads_android_and_swift_usage(tmp_path: Path, make_config) -> None:
    res = tmp_path / "app" / "src" / "main"
    (res / "res" / "values-en").mkdir(parents=True)
    (res / "res" / "layout").mkdir(parents=True)
    (res / "res" / "values-en" / "strings.xml").write_text(
        '<resources>\n<string name="app_name">Demo</string>\n<string name="save">Save</string>\n'
        '<string name="orphan">Never used</string>\n</resources>\n', encoding="utf-8")
    (res / "java").mkdir()
    (res / "java" / "Main.kt").write_text(
        'fun f() { Text(stringResource(R.string.app_name)); toast(getString(R.string.gone)) }\n', encoding="utf-8")
    (res / "res" / "layout" / "main.xml").write_text('<Button android:text="@string/save"/>\n', encoding="utf-8")
    cfg = make_config(tmp_path, name="droid", catalog_format="android-xml",
                      catalog_path="app/src/main/res/values-{locale}/{namespace}.xml",
                      scan_src_dirs=["app/src/main"], state_dir=tmp_path / ".state")
    data = op_check_keys(cfg, qa=False).data
    assert set(data["missing"]) == {"gone"}
    assert data["unused"] == ["strings.orphan"] or data["unused"] == ["orphan"]
