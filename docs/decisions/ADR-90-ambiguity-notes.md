# ADR-90: Ambiguity notes are advice attached to Suggest (C-033)

`suggest --ambiguity` asks the model for up to three source terms with several senses and the
sense the suggestion used (`pipeline/ambiguity.py`). The result is returned with the suggestion
and stored nowhere, like the suggestion itself (ADR-53). It feeds no score, state key or
context fingerprint (ADR-7) and never blocks a save (ADR-8). It is one extra model call, so
paying cloud projects get none, as with `--alternatives` (ADR-35).

Not done: running it during `translate` would change the output contract of every batch call,
and persisting notes next to candidates needs a store with its own staleness rules. Both can
follow if reviewers use the Suggest version.
