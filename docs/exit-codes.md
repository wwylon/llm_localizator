# Exit codes

Every command exits with one of these. Scripts and CI should branch on the number, not on
the text.

| Code | Name | Meaning | Typical commands |
|---|---|---|---|
| `0` | OK | Done, nothing to fix. Also returned when there was nothing to do (everything translated, or a locale below `min_keys` in an automated chain). | all |
| `1` | errors | Findings to fix, or the run failed: validation errors, a provider error, the mutation lock held by another process, an I/O error. | `validate`, `check`, `agent-hardcoded`, `translate`, `check-keys` |
| `2` | warnings / bad input | For `validate` and `check`: only warnings remain (for example V01 in a frozen locale). For a few config-editing commands (`engine`, `queue-engine`, `approach`, `set`, `review-risk`, `import-review`): the input was rejected. | `validate`, `check`, `engine`, `approach` |
| `3` | needs evidence | `engine apply` refused an unbenchmarked engine (ADR-12). Pass `--accept-unbenchmarked` to override. | `engine` |
| `64` | usage | Bad arguments or bad configuration: unknown option, invalid config file, unknown reason or locale. | all |
| `77` | permission | The web or MCP actor's role may not run this operation (role matrix, ADR-39). | web `/api/ops/*`, MCP |
| `130` | interrupted | Ctrl+C. | all |

## In CI

`validate` exits `2` when only warnings remain. Most CI systems treat any non-zero exit as
failure, so decide which you want:

```bash
llm-localizator validate --locale pl
status=$?
[ "$status" -eq 0 ] || [ "$status" -eq 2 ]   # fail on errors, pass on warnings
```

Pass `--locale` with your active targets, so frozen locales don't affect the result.
State lives in the data home by default, and a fresh CI runner has none. Use
`data_home = "project"` if CI needs staleness checks
([adding_localization.md §14](adding_localization.md#14-state-files-and-git)).

## Ops JSON

Web and MCP calls return the same number in the JSON result as `exit_code`, next to `ok`.
See [agent-contract.md](agent-contract.md).
