from llm_localizator.catalog.scores import quality_score_of


def test_quality_score_of_tolerates_bad_rows() -> None:
    assert quality_score_of(None) is None
    assert quality_score_of({}) is None
    assert quality_score_of({"quality_score": None}) is None
    assert quality_score_of({"quality_score": "nope"}) is None
    assert quality_score_of({"quality_score": 0.42}) == 0.42
    assert quality_score_of({"quality_score": "0.5"}) == 0.5
