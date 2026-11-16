# ADR-75: Tag-filtered runs

Status: accepted (2026-10-21)

`tags` is a list on a key's context note (C-035), normalised to lower-case
`[a-z0-9_-]`, at most 12 per key. `translate --tag` and `improve --tag` resolve tags
to an explicit `namespace.key` list in `ops/tags.py` before anything else runs, so the
taskqueue overrides, cloud gate and inline path all see the ordinary `keys` list (with
`keys` also given, the two are intersected). No match is a clean no-op. Tags are not
part of `context_fingerprint`, so tagging never makes a translation stale (ADR-7).
Not done: a Tags filter in the Ops drawer beyond the generated option.
