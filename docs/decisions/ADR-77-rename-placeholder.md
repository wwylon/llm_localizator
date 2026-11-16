# ADR-77: Placeholder rename

Status: accepted (2026-10-21)

`core/placeholders.rename_placeholder` is a brace-depth aware, pure rewrite of one message. `ops/placeholder_rename` applies it to the source and all targets under the project mutation lock, then refreshes `src_text`, `src_sha` and `structure_sig` only for state entries that matched the old source, so status, model and verification survive and nothing turns stale (ADR-7 formats unchanged). History gets a `placeholder-rename` event. Without `--confirm` it only reports. Keys whose source already has the new name are skipped. The TM is not rewritten. UI is the generated Ops form; a dedicated editor modal is not built.
