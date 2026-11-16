from llm_localizator.core.locale_ui import font_family, text_direction


def test_ar_is_rtl() -> None:
    assert text_direction("ar") == "rtl"
    assert text_direction("en") == "ltr"


def test_arabic_font() -> None:
    assert "Naskh" in font_family("ar")
