from llm_localizator.cli.cmd_check import evaluate


def test_check_flags_missing_and_stale_but_skips_frozen() -> None:
    rows = [
        {"locale": "pl", "coverage": 0.5, "missing": 2, "stale": 1},
        {"locale": "cs", "coverage": 0.1, "missing": 9, "stale": 3, "frozen": True},
        {"locale": "de", "coverage": 1.0, "missing": 0, "stale": 0},
    ]
    problems = evaluate(rows, min_coverage=1.0, allow_stale=False)
    assert len(problems) == 2 and all(p.startswith("pl") for p in problems)
    assert evaluate(rows, min_coverage=0.5, allow_stale=True) == []


def test_check_is_a_cli_subcommand() -> None:
    from llm_localizator.cli.main import build_parser

    assert build_parser().parse_args(["check", "--min-coverage", "0.9"]).min_coverage == 0.9
