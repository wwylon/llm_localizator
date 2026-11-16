# ADR-110 — QA marker locales (en-XX) are opt-in

**Status:** Accepted (2026-11-01)

`en-XX` / `en-XA` are review-UI QA locales for leftover hunting and length
stress — not translate targets and not `[locales].targets`. They appear in the
language picker and URL prefix only when `[web] qa_locales` lists them (e.g.
`["en-XX"]`). Default is empty so production consumers stay off. Dogfood enables
the marker; operators turn it off by clearing the list or omitting the key.
Pseudo still writes a catalogue file; routing and the picker are what this gate
controls.
