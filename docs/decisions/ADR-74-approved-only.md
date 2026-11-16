# ADR-74: Approved-only delivery

Status: accepted (2026-10-21)

`[delivery] require = none|verified|reviewed` and `export --approved-only` (C-007).
A cell is approved when state carries `verified_at`; `reviewed` also needs no open
review ticket. Exports blank unapproved targets; `bundle_payload` falls back to the
source text and derives its ETag from the filtered payload, so a verification
invalidates caches. The source locale is never filtered. One helper,
`catalog/approval.py`, serves both paths. State keys and hashes are untouched (ADR-7).
