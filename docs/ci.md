# CI

These examples run catalogue checks only. They do not start a translation
and they are not installed as a workflow in this repository.

## GitHub Actions

```yaml
name: catalogues
on: [push]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install llm_localizator
      - run: llm-localizator validate --format github
      # add --unused to fail on keys no code references (needs [scan]; see scanners.md)
```

## Localization check

`ci-templates/` has a pull-request check for GitHub Actions and GitLab. It runs
`llm-localizator run-sync --diff --exit-nonzero --no-translate`, comments with the added and
changed keys, and fails the check while strings still need translating. It never translates
(ADR-1); translation stays a queue job.

- [ci-templates/github-localization.yml](ci-templates/github-localization.yml)
- [ci-templates/gitlab-localization.yml](ci-templates/gitlab-localization.yml)

## Release report

`llm-localizator report` writes one page with a go / no-go verdict, and exits 1 only on
no-go. Attach it to the pull request or the release so reviewers who don't use the CLI can
read it:

```bash
llm-localizator report --format html --out l10n-report.html
llm-localizator report --format md --out l10n-report.md
```

In GitHub Actions, upload `l10n-report.html` as an artifact. The Markdown file also works
as a job summary (`cat l10n-report.md >> "$GITHUB_STEP_SUMMARY"`). State lives in the
data home by default, so a fresh runner reports every value as "not recorded". Use
`data_home = "project"` if CI should see provenance ([exit-codes.md](exit-codes.md#in-ci)).

## pre-commit

```yaml
repos:
  - repo: local
    hooks:
      - id: llm-localizator
        name: validate catalogues
        entry: llm-localizator validate --format github
        language: system
        pass_filenames: false
```

## Two-lane workflow (ADR-107)

- **Lane A, extraction:** feature branch holding the code change and the new *source-locale*
  keys. CI: `llm-localizator scan --strict --lint-directives` and `llm-localizator check`.
- **Lane B, translation:** target-locale files only, on the bot branch (`[source_policy]
  target_branch`), opened with `llm-localizator open-pr`. Merge once `validate` and `check` pass.

Why two lanes: translation churn never blocks code review, and Lane B cannot conflict with
code. If lane A changes source text while lane B is open, the affected strings go `stale`
and are retranslated on the bot branch (ADR-61).
