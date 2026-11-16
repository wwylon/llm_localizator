"""Every catalog adapter, held to the same contract.

The parametrised suite is the point: a new adapter that passes these is
interchangeable with the others as far as the pipeline is concerned. Format-
specific behaviour (gettext plural slots, Android escaping, ARB metadata) gets
its own section below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.catalog import KNOWN_FORMATS, build_catalog

# (format, path template). Each is exercised against the shared contract.
FORMATS = [
    ("json-nested", "messages/{locale}/{namespace}.json"),
    ("json-flat", "locales/{locale}/{namespace}.json"),
    ("yaml", "config/locales/{locale}/{namespace}.yml"),
    ("po", "locale/{locale}/LC_MESSAGES/{namespace}.po"),
    ("arb", "lib/l10n/{namespace}_{locale}.arb"),
    ("android-xml", "res/values-{locale}/{namespace}.xml"),
]
IDS = [f[0] for f in FORMATS]

PLURAL_PL = "{n, plural, one {# lewa} few {# lewy} many {# lew} other {# lewy}}"
PLURAL_EN = "{n, plural, one {# trick} other {# tricks}}"


@pytest.fixture(params=FORMATS, ids=IDS)
def adapter(request, tmp_path: Path):
    fmt, template = request.param
    return fmt, build_catalog(fmt, tmp_path, template, "en")


# ---- the shared contract ---------------------------------------------------

def test_missing_file_loads_as_empty(adapter) -> None:
    _, cat = adapter
    assert cat.load("pl", "app") == {}


def test_save_then_load_round_trips_plain_strings(adapter) -> None:
    _, cat = adapter
    data = {"greet": "Hello", "bye": "Goodbye"}
    cat.save("pl", "app", data)
    assert cat.load("pl", "app") == data


def test_save_creates_parent_directories(adapter) -> None:
    _, cat = adapter
    cat.save("pl", "app", {"a": "A"})
    assert cat.path_for("pl", "app").exists()


def test_namespaces_discovered_from_source_locale(adapter) -> None:
    _, cat = adapter
    for ns in ("play", "auth", "nav"):
        cat.save("en", ns, {"k": "v"})
    assert cat.namespaces() == ["auth", "nav", "play"]


def test_unicode_survives_round_trip(adapter) -> None:
    _, cat = adapter
    data = {"ar": "خدعة واحدة", "pl": "Zaakceptuj", "emoji": "Deal 🃏"}
    cat.save("pl", "app", data)
    assert cat.load("pl", "app") == data


def test_icu_plural_survives_round_trip(adapter) -> None:
    """Every format must represent an ICU plural, natively or by translation."""
    fmt, cat = adapter
    cat.save("en", "app", {"tricks": PLURAL_EN})
    cat.save("pl", "app", {"tricks": PLURAL_PL})

    from llm_localizator.core.icu import extract_plural_categories

    loaded = cat.load("pl", "app")["tricks"]
    assert extract_plural_categories(loaded) == {"one", "few", "many", "other"}


def test_placeholders_survive_round_trip(adapter) -> None:
    _, cat = adapter
    data = {"welcome": "Witaj {name}, masz {count} wiadomości"}
    cat.save("pl", "app", data)

    from llm_localizator.core.icu import extract_placeholders

    assert extract_placeholders(cat.load("pl", "app")["welcome"]) == {"name", "count"}


def test_overwriting_replaces_rather_than_appends(adapter) -> None:
    _, cat = adapter
    cat.save("pl", "app", {"a": "first"})
    cat.save("pl", "app", {"a": "second"})
    assert cat.load("pl", "app") == {"a": "second"}


def test_load_entries_defaults_to_the_string_view(adapter) -> None:
    _, cat = adapter
    cat.save("pl", "app", {"a": "A"})
    entries = cat.load_entries("pl", "app")
    assert set(entries) == {"a"}
    assert entries["a"].value == "A"


def test_locales_present_discovers_targets_and_excludes_source(adapter) -> None:
    """Locale discovery must work whether the locale lives in a directory, a
    filename, or a prefixed resource dir."""
    _, cat = adapter
    for locale in ("en", "pl", "de"):
        cat.save(locale, "app", {"a": "A"})
    assert cat.locales_present() == ["de", "pl"]


def test_locales_present_ignores_hidden_directories(tmp_path: Path) -> None:
    from llm_localizator.catalog.json_nested import JsonNestedCatalog

    cat = JsonNestedCatalog(tmp_path, "messages/{locale}/{namespace}.json", "en")
    cat.save("en", "app", {"a": "A"})
    cat.save("pl", "app", {"a": "A"})
    hidden = tmp_path / "messages" / ".state"
    hidden.mkdir()
    (hidden / "pl.json").write_text("{}", encoding="utf-8")
    assert cat.locales_present() == ["pl"]


def test_locales_present_handles_a_region_subtag(adapter) -> None:
    _, cat = adapter
    cat.save("en", "app", {"a": "A"})
    cat.save("pt-BR", "app", {"a": "A"})
    assert "pt-BR" in cat.locales_present()


# ---- registry --------------------------------------------------------------

def test_every_known_format_builds(tmp_path: Path) -> None:
    for name in KNOWN_FORMATS:
        assert build_catalog(name, tmp_path, "x/{locale}/{namespace}.txt", "en")


def test_framework_aliases_resolve_to_adapters(tmp_path: Path) -> None:
    from llm_localizator.catalog import GettextPoCatalog, JsonNestedCatalog

    t = "x/{locale}/{namespace}.txt"
    assert isinstance(build_catalog("next-intl", tmp_path, t), JsonNestedCatalog)
    assert isinstance(build_catalog("gettext", tmp_path, t), GettextPoCatalog)


def test_unknown_format_lists_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown catalog format"):
        build_catalog("sqlite", tmp_path, "x/{locale}.db")


# ---- single-file layouts ---------------------------------------------------

@pytest.mark.parametrize("fmt,template", [
    ("json-flat", "locales/{locale}.json"),
    ("yaml", "locales/{locale}.yml"),
    ("po", "locale/{locale}.po"),
])
def test_namespaceless_template_yields_one_unnamed_namespace(
    tmp_path: Path, fmt: str, template: str
) -> None:
    cat = build_catalog(fmt, tmp_path, template, "en")
    assert cat.multi_namespace is False
    cat.save("en", None, {"a": "A"})
    assert cat.namespaces() == [""]
    assert cat.load("en", None) == {"a": "A"}


# ---- gettext ---------------------------------------------------------------

class TestGettext:
    def build(self, tmp_path: Path):
        return build_catalog("po", tmp_path, "locale/{locale}/{namespace}.po", "en")

    def test_plural_maps_onto_indexed_slots(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("en", "app", {"tricks": PLURAL_EN})
        cat.save("pl", "app", {"tricks": PLURAL_PL})

        text = cat.path_for("pl", "app").read_text(encoding="utf-8")
        assert "msgstr[0]" in text and "msgstr[1]" in text and "msgstr[2]" in text
        assert "nplurals=3" in text, "Polish header must declare three forms"

    def test_arabic_gets_six_slots(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        arabic = ("{n, plural, zero {# خدعة} one {خدعة} two {خدعتان} "
                  "few {# خدع} many {# خدعة} other {# خدعة}}")
        cat.save("ar", "app", {"tricks": arabic})
        text = cat.path_for("ar", "app").read_text(encoding="utf-8")
        assert "msgstr[5]" in text
        assert "nplurals=6" in text

    def test_icu_hash_becomes_printf_and_back(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"tricks": PLURAL_PL})
        raw = cat.path_for("pl", "app").read_text(encoding="utf-8")
        assert "%(n)s" in raw, "gettext has no '#' concept"
        assert "#" not in raw.split("msgstr[0]")[1].split("\n")[0]
        assert cat.load("pl", "app")["tricks"].count("#") == 4

    def test_translator_comments_survive_a_write(self, tmp_path: Path) -> None:
        """The thing that matters most: never destroy a translator's work."""
        path = tmp_path / "locale" / "pl" / "app.po"
        path.parent.mkdir(parents=True)
        path.write_text(
            'msgid ""\nmsgstr "Language: pl\\n"\n\n'
            "# a human wrote this\n"
            "#. extracted from source\n"
            "#: src/app.py:42\n"
            'msgid "Hello"\nmsgstr "Witaj"\n',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"Hello": "Czesc"})

        text = path.read_text(encoding="utf-8")
        assert "# a human wrote this" in text
        assert "#. extracted from source" in text
        assert "#: src/app.py:42" in text
        assert "Czesc" in text

    def test_blank_line_between_comment_and_msgid_keeps_the_comment(self) -> None:
        from llm_localizator.catalog.gettext_po import parse_po, render_po

        text = '#. Comment for foo\n\nmsgid "foo"\nmsgstr "bar"\n'
        entries = [entry for entry in parse_po(text) if entry.msgid == "foo"]
        assert len(entries) == 1
        assert entries[0].extracted == ["Comment for foo"]
        assert entries[0].msgstr == "bar"
        separated = parse_po('msgid "a"\nmsgstr "b"\n\nmsgid "c"\nmsgstr "d"\n')
        assert [entry.msgid for entry in separated if entry.msgid] == ["a", "c"]
        assert render_po(entries).endswith("\n")

    def test_fuzzy_flag_is_cleared_after_retranslation(self, tmp_path: Path) -> None:
        path = tmp_path / "locale" / "pl" / "app.po"
        path.parent.mkdir(parents=True)
        path.write_text('#, fuzzy\nmsgid "Hello"\nmsgstr "stary"\n', encoding="utf-8")
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"Hello": "Witaj"})
        assert "fuzzy" not in path.read_text(encoding="utf-8")

    def test_extracted_comment_is_exposed_as_a_note(self, tmp_path: Path) -> None:
        path = tmp_path / "locale" / "en" / "app.po"
        path.parent.mkdir(parents=True)
        path.write_text(
            "#. Button on the bidding box\n" 'msgid "Bid"\nmsgstr "Bid"\n',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        assert cat.carries_notes
        assert cat.load_entries("en", "app")["Bid"].note == "Button on the bidding box"

    def test_msgctxt_disambiguates_identical_source_text(self, tmp_path: Path) -> None:
        path = tmp_path / "locale" / "pl" / "app.po"
        path.parent.mkdir(parents=True)
        path.write_text(
            'msgctxt "verb"\nmsgid "Pass"\nmsgstr "Pasuj"\n\n'
            'msgctxt "noun"\nmsgid "Pass"\nmsgstr "Pas"\n',
            encoding="utf-8",
        )
        loaded = self.build(tmp_path).load("pl", "app")
        assert loaded == {"verb\x04Pass": "Pasuj", "noun\x04Pass": "Pas"}

    def test_header_and_obsolete_entries_are_not_translatable(self, tmp_path: Path) -> None:
        path = tmp_path / "locale" / "pl" / "app.po"
        path.parent.mkdir(parents=True)
        path.write_text(
            'msgid ""\nmsgstr "Language: pl\\n"\n\n'
            "#~ msgid \"Gone\"\n#~ msgstr \"Zniknelo\"\n\n"
            'msgid "Hi"\nmsgstr "Czesc"\n',
            encoding="utf-8",
        )
        assert self.build(tmp_path).load("pl", "app") == {"Hi": "Czesc"}

    def test_header_has_no_trailing_empty_line(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"Hello": "Witaj"})
        lines = cat.path_for("pl", "app").read_text(encoding="utf-8").splitlines()
        header_end = next(i for i, l in enumerate(lines) if l.strip() == "")
        assert lines[header_end - 1] != '""', "header must not end in a stray empty string"

    def test_generated_header_declares_the_locale_plural_forms(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"Hello": "Witaj"})
        text = cat.path_for("pl", "app").read_text(encoding="utf-8")
        assert "Language: pl" in text
        assert "nplurals=3" in text

    def test_source_references_are_carried_into_a_new_target(self, tmp_path: Path) -> None:
        """A fresh target file inherits the source's comments and references."""
        src = tmp_path / "locale" / "en" / "app.po"
        src.parent.mkdir(parents=True)
        src.write_text(
            "#. Button on the bidding box\n#: src/table.py:42\n"
            'msgid "Claim"\nmsgstr "Claim"\n',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"Claim": "Rozgrywaj"})

        text = cat.path_for("pl", "app").read_text(encoding="utf-8")
        assert "#. Button on the bidding box" in text
        assert "#: src/table.py:42" in text

    def test_escaped_quotes_round_trip(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"q": 'He said "no"'})
        assert cat.load("pl", "app") == {"q": 'He said "no"'}

    def test_extra_nplurals_keeps_all_categories(self, tmp_path: Path) -> None:
        # nplurals=3 for English (which has 2 CLDR categories: one, other).
        # The third slot maps to a synthetic "other_2" key so no plural form
        # is silently lost.  No warning is emitted because there are no
        # duplicate category names.
        import warnings

        cat = self.build(tmp_path)
        path = cat.path_for("en", "app")
        path.parent.mkdir(parents=True)
        path.write_text(
            'msgid ""\n'
            'msgstr ""\n'
            '"Plural-Forms: nplurals=3; plural=(n != 1);\\n"\n'
            "\n"
            'msgid "trick"\n'
            'msgid_plural "tricks"\n'
            'msgstr[0] "one trick"\n'
            'msgstr[1] "other tricks"\n'
            'msgstr[2] "more tricks"\n',
            encoding="utf-8",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            loaded = cat.load("en", "app")
            again = cat.load("en", "app")
        # All three plural forms must be present under distinct keys.
        assert "one" in loaded["trick"] and "other" in loaded["trick"]
        assert "other_2" in loaded["trick"], "third plural slot must not be silently dropped"
        assert again["trick"] == loaded["trick"]
        # No nplurals warning expected: synthetic keys prevent duplicates.
        hits = [w for w in caught if "nplurals" in str(w.message)]
        assert len(hits) == 0


# ---- Android ---------------------------------------------------------------

class TestAndroid:
    def build(self, tmp_path: Path):
        return build_catalog("android-xml", tmp_path, "res/values-{locale}/{namespace}.xml", "en")

    def test_region_locale_uses_android_qualifier(self, tmp_path: Path) -> None:
        from llm_localizator.catalog import android_qualifier

        assert android_qualifier("pt-BR") == "pt-rBR"
        assert android_qualifier("pl") == "pl"
        cat = self.build(tmp_path)
        assert "values-pt-rBR" in str(cat.path_for("pt-BR", "strings"))

    def test_plural_uses_quantity_items(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"tricks": PLURAL_PL})
        text = cat.path_for("pl", "strings").read_text(encoding="utf-8")
        assert '<plurals name="tricks">' in text
        assert '<item quantity="few">' in text
        assert "%d" in text, "Android uses %d, not ICU '#'"

    def test_apostrophes_are_escaped(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("fr", "strings", {"x": "L'heure"})
        assert "\\'" in cat.path_for("fr", "strings").read_text(encoding="utf-8")
        assert cat.load("fr", "strings") == {"x": "L'heure"}

    def test_leading_at_sign_is_escaped(self, tmp_path: Path) -> None:
        """An unescaped leading @ would be read as a resource reference."""
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"x": "@home"})
        assert "\\@" in cat.path_for("pl", "strings").read_text(encoding="utf-8")
        assert cat.load("pl", "strings") == {"x": "@home"}

    def test_leading_at_with_apostrophe_is_escaped(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"x": "@it's"})
        text = cat.path_for("pl", "strings").read_text(encoding="utf-8")
        assert "\\@" in text
        assert cat.load("pl", "strings") == {"x": "@it's"}

    def test_untranslatable_resources_are_never_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "res" / "values-en" / "strings.xml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><resources>'
            '<string name="app_name" translatable="false">BridgeApp</string>'
            '<string name="greet">Hello</string></resources>',
            encoding="utf-8",
        )
        assert self.build(tmp_path).load("en", "strings") == {"greet": "Hello"}

    def test_untranslatable_resources_are_carried_into_targets(self, tmp_path: Path) -> None:
        path = tmp_path / "res" / "values-en" / "strings.xml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><resources>'
            '<string name="app_name" translatable="false">BridgeApp</string>'
            '<string name="greet">Hello</string></resources>',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"greet": "Witaj"})
        out = cat.path_for("pl", "strings").read_text(encoding="utf-8")
        assert "app_name" in out and "BridgeApp" in out

    def test_positional_arguments_are_preserved(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"x": "Witaj %1$s, masz %2$d"})
        assert cat.load("pl", "strings") == {"x": "Witaj %1$s, masz %2$d"}

    def test_comment_above_a_string_is_a_note(self, tmp_path: Path) -> None:
        path = tmp_path / "res" / "values-en" / "strings.xml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
            "    <!-- Shown on the table screen -->\n"
            '    <string name="claim">Claim</string>\n</resources>\n',
            encoding="utf-8",
        )
        entries = self.build(tmp_path).load_entries("en", "strings")
        assert entries["claim"].note == "Shown on the table screen"

    def test_untranslatable_ampersand_is_not_escaped_twice(self, tmp_path: Path) -> None:
        path = tmp_path / "res" / "values-en" / "strings.xml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><resources>'
            '<string name="app_name" translatable="false">Bridge &amp; Co</string>'
            '<string name="greet">Hello</string></resources>',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        cat.save("pl", "strings", {"greet": "Witaj"})
        out = cat.path_for("pl", "strings").read_text(encoding="utf-8")
        assert "Bridge &amp; Co" in out
        assert "&amp;amp;" not in out

    def test_rejects_a_name_that_breaks_the_attribute(self, tmp_path: Path) -> None:
        cat = self.build(tmp_path)
        path = cat.path_for("pl", "strings")
        with pytest.raises(ValueError, match="bad"):
            cat.save("pl", "strings", {'bad"name': "Witaj"})
        assert not path.exists()
        cat.save("pl", "strings", {"q": 'He said "no"'})
        assert cat.load("pl", "strings") == {"q": 'He said "no"'}


# ---- ARB -------------------------------------------------------------------

class TestArb:
    def build(self, tmp_path: Path):
        return build_catalog("arb", tmp_path, "lib/l10n/{namespace}_{locale}.arb", "en")

    def test_metadata_keys_are_not_translatable(self, tmp_path: Path) -> None:
        path = tmp_path / "lib" / "l10n" / "app_en.arb"
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"@@locale": "en", "greet": "Hello", '
            '"@greet": {"description": "Greeting on the home screen"}}',
            encoding="utf-8",
        )
        assert self.build(tmp_path).load("en", "app") == {"greet": "Hello"}

    def test_description_becomes_a_note(self, tmp_path: Path) -> None:
        path = tmp_path / "lib" / "l10n" / "app_en.arb"
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"greet": "Hello", "@greet": {"description": "Greeting on the home screen"}}',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        assert cat.carries_notes
        assert cat.load_entries("en", "app")["greet"].note == "Greeting on the home screen"

    def test_metadata_is_carried_into_the_target_bundle(self, tmp_path: Path) -> None:
        src = tmp_path / "lib" / "l10n" / "app_en.arb"
        src.parent.mkdir(parents=True)
        src.write_text(
            '{"greet": "Hello", "@greet": {"description": "Greeting", '
            '"placeholders": {"name": {"type": "String"}}}}',
            encoding="utf-8",
        )
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"greet": "Witaj"})

        import json

        out = json.loads((tmp_path / "lib" / "l10n" / "app_pl.arb").read_text(encoding="utf-8"))
        assert out["@@locale"] == "pl"
        assert out["@greet"]["description"] == "Greeting"
        assert out["@greet"]["placeholders"]["name"]["type"] == "String"


# ---- YAML ------------------------------------------------------------------

class TestYaml:
    def build(self, tmp_path: Path):
        return build_catalog("yaml", tmp_path, "config/locales/{locale}/{namespace}.yml", "en")

    def test_locale_root_wrapper_is_stripped_and_restored(self, tmp_path: Path) -> None:
        path = tmp_path / "config" / "locales" / "en" / "app.yml"
        path.parent.mkdir(parents=True)
        path.write_text("en:\n  nav:\n    home: Home\n", encoding="utf-8")

        cat = self.build(tmp_path)
        assert cat.load("en", "app") == {"nav.home": "Home"}

        cat.save("pl", "app", {"nav.home": "Start"})
        out = (tmp_path / "config" / "locales" / "pl" / "app.yml").read_text(encoding="utf-8")
        assert out.lstrip().startswith("pl:"), "the wrapper convention must be preserved"

    def test_file_without_a_wrapper_stays_unwrapped(self, tmp_path: Path) -> None:
        path = tmp_path / "config" / "locales" / "en" / "app.yml"
        path.parent.mkdir(parents=True)
        path.write_text("nav:\n  home: Home\n", encoding="utf-8")

        cat = self.build(tmp_path)
        cat.save("pl", "app", {"nav.home": "Start"})
        out = (tmp_path / "config" / "locales" / "pl" / "app.yml").read_text(encoding="utf-8")
        assert not out.lstrip().startswith("pl:")

    @pytest.mark.parametrize("value", ["No", "Yes", "on", "off", "1.0", "null", "~"])
    def test_yaml_truthy_strings_do_not_become_booleans(
        self, tmp_path: Path, value: str
    ) -> None:
        """A translation of 'No' must survive as the string 'No'."""
        cat = self.build(tmp_path)
        cat.save("pl", "app", {"answer": value})
        assert cat.load("pl", "app") == {"answer": value}
