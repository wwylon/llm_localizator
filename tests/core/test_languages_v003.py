from llm_localizator.core.languages import language_for_suffix, source_languages


def test_v003_extensions_registered() -> None:
    ids = {row.id for row in source_languages()}
    assert {"kotlin", "dart", "svelte"} <= ids
    assert language_for_suffix(".kt").id == "kotlin"
    assert language_for_suffix(".dart").id == "dart"
    assert language_for_suffix(".svelte").id == "svelte"
