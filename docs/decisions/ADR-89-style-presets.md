# ADR-89: Style presets are an opt-in prompt line (C-002)

`[prompt] style_preset` (faithful, fluid or creative) adds one `Style:` line through
`ProjectConfig.prompt_extras_for`, next to description, audience and tone (ADR-60, ADR-68).
`[prompt.style_presets]` overrides it per locale. With no preset nothing is added, so
prompt snapshots and the context fingerprint inputs stay as they were (ADR-7).

Scope cut: the idea said per namespace or key tag. `style_for` has about fifteen call
sites that do not carry a namespace, so a per-namespace preset would touch every one of
them; project and locale cover the common case first. Making any preset the default needs
a bakeoff with the incumbent (ADR-12), so none is.
