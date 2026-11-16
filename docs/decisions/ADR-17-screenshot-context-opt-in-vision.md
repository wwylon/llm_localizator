# ADR-17: Screenshot context is opt-in via a separate vision model

`ContextNotes.image()`/`resolve_screenshot_path()` already let a project attach
a per-key screenshot, but nothing consumed it. Wiring it in raises two
questions: which model receives the image, and how batching behaves when only
some items in a group carry one.

**Model selection.** Rather than assume the default text model can accept
images, screenshot attachment requires a new, separate `[quality] vision_model`
config key. When unset, no file is ever read and no `images` field is ever
sent — a project that hasn't opted in pays zero cost for this feature and
never risks sending an image to a model that can't use it. Ollama's
`/api/generate` accepts a plain `images: [<base64>]` list, so the wire format
needed no new dependency (`CompletionRequest.images: list[str] | None`).

**Batching.** `build_batch_prompt` merges several items' source text into one
JSON-array call; there's no way to attach an image to just one slot of that
array. Rather than split a batch item-by-item (more moving parts, more ways to
silently drop an image), any batch containing at least one image-bearing item
is routed through the existing per-key (`_translate_singles`) path in full.
Only that item's request switches `model` to `vision_model` and carries
`images`; sibling items in the same batch still use the normal text model —
they just no longer share one combined request.

Rejected: a `documents_model`-style reuse of an existing model slot — kept
separate because prompt/image pairing is a model-capability concern, not a
per-locale one, and conflating it with `improve_model`/`score_model` would
make "is this call multimodal" implicit instead of explicit.
