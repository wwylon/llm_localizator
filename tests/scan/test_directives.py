from llm_localizator.scan.base import HardcodedString
from llm_localizator.scan.directives import filter_hits, lint_directives


def _h(line):
    return HardcodedString(text="Hello", file="a.tsx", line=line)


def test_same_line_ignore_all_comment_styles():
    for c in ("// l10n-ignore", "# l10n-ignore", "/* l10n-ignore */",
              "<!-- l10n-ignore -->", "{/* l10n-ignore */}"):
        kept, n = filter_hits([f"x {c}"], [_h(1)])
        assert (kept, n) == ([], 1), c


def test_next_line_and_block():
    lines = ["// l10n-ignore-next-line", "a", "b", "# l10n-ignore-start", "c", "d", "# l10n-ignore-end", "e"]
    kept, n = filter_hits(lines, [_h(2), _h(3), _h(5), _h(6), _h(8)])
    assert [h.line for h in kept] == [3, 8] and n == 3


def test_ignore_file_only_in_header():
    assert filter_hits(["// l10n-ignore-file", "x"], [_h(2)]) == ([], 1)
    late = [""] * 12 + ["// l10n-ignore-file", "x"]
    assert filter_hits(late, [_h(14)])[1] == 0


def test_aliases_and_plain_text_not_a_directive():
    kept, n = filter_hits(["x // i18n-ignore", "y // eslint-disable-next-line i18next/no-literal-string", "z"],
                          [_h(1), _h(3)])
    assert n == 2 and kept == []
    kept, n = filter_hits(['text = "l10n-ignore"'], [_h(1)])
    assert n == 0


def test_lint_reports_stale_and_unbalanced():
    lines = ["// l10n-ignore", "ok", "// l10n-ignore-start"]
    out = lint_directives(lines, [])
    assert any("stale" in p for p in out) and any("without end" in p for p in out)


def test_attribute_hints_apply_to_next_hit_and_file_namespace():
    from llm_localizator.scan.directives import apply_directives

    lines = ["// l10n: namespace=checkout", '// l10n: key=pay.btn note="Pay button" max-length=20 dnt',
             "x", "y"]
    kept, n = apply_directives(lines, [_h(3), _h(4)])
    assert n == 0
    assert (kept[0].key_hint, kept[0].note, kept[0].max_length, kept[0].dnt) == ("pay.btn", "Pay button", 20, True)
    assert kept[0].namespace_hint == "checkout" and kept[1].namespace_hint == "checkout"
    assert kept[1].key_hint == ""


def test_aliases_can_be_disabled():
    assert filter_hits(["x // i18n-ignore"], [_h(1)], aliases=False)[1] == 0
    assert filter_hits(["x // l10n-ignore"], [_h(1)], aliases=False)[1] == 1


def test_lint_flags_typos_and_unknown_attributes():
    out = lint_directives(["// l10n-ignor", "// l10n: kee=a"], [])
    assert any("unknown directive" in p for p in out)
    assert any("unknown l10n: attribute" in p for p in out)


def test_scan_lint_and_suppressed_count(tmp_path):
    from llm_localizator.ops.agent_hardcoded import op_agent_hardcoded
    from llm_localizator.ops.scan import op_scan
    from llm_localizator.ops.types import AgentHardcodedRequest, ScanRequest
    from tests.synth.factory import build_project

    proj = build_project(tmp_path)
    cfg = proj.config()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.tsx").write_text(
        'export const A = () => <button>Click here now</button>; // l10n-ignore\n'
        'export const B = () => <button>Another label</button>;\n'
        '// l10n-ignore\n'
        'const x = 1;\n', encoding="utf-8")
    cfg.scan_adapter, cfg.scan_src_dirs = "source", ["src"]
    out = op_agent_hardcoded(cfg, AgentHardcodedRequest(fmt="json", catalogue_audit=False, refresh=True))
    assert out.data["suppressedByDirective"] >= 1
    assert all(h["line"] != 1 for h in out.data["hits"])
    lint = op_scan(cfg, ScanRequest(lint_directives=True))
    assert lint.exit_code == 1 and any("stale" in p for p in lint.data["problems"])


def test_user_facing_forces_a_hit_the_heuristics_missed():
    from llm_localizator.scan.directives import apply_directives

    lines = ["// l10n: user-facing", 'const label = "ok_button_text";', 'const other = "x";']
    kept, n = apply_directives(lines, [], file="a.ts")
    assert [(h.line, h.text, h.confidence) for h in kept] == [(2, "ok_button_text", "high")]
    kept, _ = apply_directives(lines, [_h(2)], file="a.ts")
    assert len(kept) == 1  # an existing hit is not duplicated
