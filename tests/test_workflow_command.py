"""``llm-localizator workflow`` CLI wiring."""

from llm_localizator.cli.main import build_parser


def test_workflow_parses_flags():
    a = build_parser().parse_args(
        ["workflow", "--name", "nightly", "--locales", "pl,de", "--dry-run", "--route-only", "--resume", "r1"]
    )
    assert (a.workflow_name, a.locales, a.dry_run, a.route_only, a.resume) == (
        "nightly", ["pl", "de"], True, True, "r1",
    )


def test_workflow_defaults_to_default_name():
    assert build_parser().parse_args(["workflow"]).workflow_name == "default"
