"""next-intl scanner.

The hardcoded-string detector must stay conservative: the false-positive cases
below are pinned so a future regex tweak cannot quietly start crying wolf.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.scan import NextIntlScanner, build_scanner


def scan_source(tmp_path: Path, source: str, name: str = "Comp.tsx"):
    src = tmp_path / "app"
    src.mkdir(parents=True, exist_ok=True)
    (src / name).write_text(source, encoding="utf-8")
    return NextIntlScanner(tmp_path, ["app"]).scan()


# ---- usage backreferences --------------------------------------------------

def test_single_namespace_file_resolves_bare_keys(tmp_path: Path) -> None:
    result = scan_source(tmp_path, """
export function LoginForm() {
  const t = useTranslations('auth');
  return <button>{t('signIn')}</button>;
}
""")
    assert [(u.namespace, u.key) for u in result.usages] == [("auth", "signIn")]
    assert result.usages[0].component == "LoginForm"


def test_dotted_key_carries_its_own_namespace(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "const x = t('play.claim');")
    assert [(u.namespace, u.key) for u in result.usages] == [("play", "claim")]


def test_ambiguous_bare_key_with_two_namespaces_is_skipped(tmp_path: Path) -> None:
    """Two namespaces and no prefix: guessing would produce a wrong backref."""
    result = scan_source(tmp_path, """
const t = useTranslations('auth');
const n = useTranslations('nav');
const label = t('signIn');
""")
    assert result.usages == []


def test_get_translations_counts_as_a_namespace_source(tmp_path: Path) -> None:
    result = scan_source(tmp_path, """
const t = await getTranslations('clubs');
const label = t('roster');
""")
    assert [(u.namespace, u.key) for u in result.usages] == [("clubs", "roster")]


def test_line_numbers_are_one_based(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "const t = useTranslations('nav');\nconst a = t('home');\n")
    assert result.usages[0].line == 2


def test_grouping_produces_the_artefact_shape(tmp_path: Path) -> None:
    result = scan_source(tmp_path, """
const t = useTranslations('nav');
const a = t('home');
const b = t('home');
const c = t('away');
""")
    grouped = result.by_namespace()
    assert set(grouped["nav"]) == {"home", "away"}
    assert len(grouped["nav"]["home"]) == 2


# ---- hardcoded strings -----------------------------------------------------

def test_detects_hardcoded_jsx_text(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<button>Sign in now</button>")
    assert [h.text for h in result.hardcoded] == ["Sign in now"]


def test_set_height_does_not_suppress_hardcoded_jsx(tmp_path: Path) -> None:
    """``setHeight(`` contains the letters t( but is not a ``t(`` call."""
    result = scan_source(
        tmp_path,
        '<button onClick={() => setHeight(true)}>Sign in now</button>',
    )
    assert any(h.text == "Sign in now" for h in result.hardcoded)


def test_detects_hardcoded_placeholder_attribute(tmp_path: Path) -> None:
    result = scan_source(tmp_path, '<input placeholder="Search clubs" />')
    assert result.hardcoded and "Search clubs" in result.hardcoded[0].text


@pytest.mark.parametrize("attr", ["title", "alt", "aria-label"])
def test_detects_other_user_visible_attributes(tmp_path: Path, attr: str) -> None:
    result = scan_source(tmp_path, f'<img {attr}="A photo of the table" />')
    assert result.hardcoded


def test_translated_text_is_not_flagged(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<button>{t('signIn')}</button>")
    assert result.hardcoded == []


# ---- false positives that must stay silent ---------------------------------

@pytest.mark.parametrize("source", [
    "<code>npm install</code>",
    "<pre>some literal block</pre>",
    "// Sign in to continue",
    "<div>{value}</div>",
    "<span>42</span>",
    '<Foo bar="x" />',
    "<div>Bridge</div>",              # single capitalised word: likely an identifier
    '<a href="https://example.com">{t("link")}</a>',
])
def test_conservative_cases_are_not_flagged(tmp_path: Path, source: str) -> None:
    assert scan_source(tmp_path, source).hardcoded == []


def test_sentence_punctuation_makes_a_single_word_prose(tmp_path: Path) -> None:
    assert scan_source(tmp_path, "<p>Loading...</p>").hardcoded


# ---- §4 already-routed wrappers --------------------------------------------

@pytest.mark.parametrize("source", [
    "<Trans>Sign in</Trans>",
    "<FormattedMessage id='auth.signIn' />",
    "const label = $t('auth.signIn')",
    "I18n.t('auth.sign_in')",
    "{{ 'sign_in' | translate }}",
])
def test_already_routed_wrappers_are_not_flagged(tmp_path: Path, source: str) -> None:
    assert scan_source(tmp_path, source).hardcoded == []


# ---- §1 single-word JSX widget labels --------------------------------------

def test_single_word_button_label_is_flagged(tmp_path: Path) -> None:
    assert scan_source(tmp_path, "<button>Save</button>").hardcoded


def test_single_word_div_is_still_silent(tmp_path: Path) -> None:
    assert scan_source(tmp_path, "<div>Bridge</div>").hardcoded == []


def test_single_word_option_label_is_flagged(tmp_path: Path) -> None:
    assert scan_source(tmp_path, "<option>Weekly</option>").hardcoded


# ---- §2 mixed-content JSX fragments ----------------------------------------

def test_trailing_fragment_after_expression(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<p>{user.name} joined the club</p>")
    assert any("joined the club" in h.text for h in result.hardcoded)


def test_leading_fragment_before_expression(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<p>Welcome back, {user.name}</p>")
    assert any("Welcome back" in h.text for h in result.hardcoded)


# ---- §7 confidence tiers ---------------------------------------------------

def test_confidence_high_for_multiword_jsx_text(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<button>Sign in now</button>")
    assert all(h.confidence == "high" for h in result.hardcoded)


def test_confidence_medium_for_single_word_label(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<button>Save</button>")
    assert result.hardcoded
    assert all(h.confidence == "medium" for h in result.hardcoded)


# ---- plumbing --------------------------------------------------------------

def test_build_scanner_rejects_unknown_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown scan adapter"):
        build_scanner("nope", tmp_path, ["app"])


@pytest.mark.parametrize("name", [
    "Tooltip.test.tsx", "Tooltip.spec.tsx", "Button.stories.tsx", "types.d.ts",
])
def test_non_shipped_files_are_skipped(tmp_path: Path, name: str) -> None:
    """A literal in a test is an assertion, not a missing translation.

    Skipping `__tests__/` alone misses the co-located convention, which is at
    least as common -- bridge has 9 findings in one `Tooltip.test.tsx`.
    """
    result = scan_source(tmp_path, "<button>Sign in now</button>", name=name)
    assert result.files_scanned == 0
    assert result.hardcoded == []


def test_ordinary_components_are_still_scanned(tmp_path: Path) -> None:
    result = scan_source(tmp_path, "<button>Sign in now</button>", name="Tooltip.tsx")
    assert result.files_scanned == 1
    assert result.hardcoded


def test_t_call_with_variables_is_a_usage(tmp_path: Path) -> None:
    result = scan_source(tmp_path, """
const t = useTranslations('auth');
const label = t('signIn', { name: 'Ada' });
""")
    assert [(u.namespace, u.key) for u in result.usages] == [("auth", "signIn")]


def test_multiline_attribute_is_hardcoded(tmp_path: Path) -> None:
    result = scan_source(tmp_path, """
<input
  placeholder="Sign in now"
/>
""")
    assert any("Sign in now" in h.text for h in result.hardcoded)


def test_node_modules_is_skipped(tmp_path: Path) -> None:
    nm = tmp_path / "app" / "node_modules"
    nm.mkdir(parents=True)
    (nm / "Vendor.tsx").write_text("<button>Vendor text here</button>", encoding="utf-8")
    result = NextIntlScanner(tmp_path, ["app"]).scan()
    assert result.files_scanned == 0
