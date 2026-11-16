"""Polish."""

from __future__ import annotations

import re

from .base import LocaleProfile, regex_check

# Masculine-personal nouns used in UIs (players, users, people). After 2–4 they
# take the collective numeral and the genitive plural: "dwóch graczy", never
# "dwa gracze". The nominative plural of these nouns ends in -cy/-dzy/-rzy/-owie
# or is listed here.
_PERSONAL_PLURALS = (
    r"gracze|użytkownicy|uczestnicy|partnerzy|przeciwnicy|obrońcy|tłumacze|"
    r"administratorzy|autorzy|operatorzy|członkowie|rozgrywający|rozdający|"
    r"\w+(?:cy|dzy|rzy|owie)"
)
# Nominative plurals of common UI nouns. After 5+ (and 12–14) Polish needs the
# genitive plural: "5 plików", never "5 pliki".
_FEW_FORMS = (
    r"pliki|modele|obrazy|obrazki|lewy|gry|punkty|karty|rozdania|zadania|"
    r"elementy|wyniki|minuty|sekundy|godziny|dni|klucze|wiersze|kolumny|strony"
)
_FIVE_PLUS = r"(?:[5-9]|1[0-9]|[2-9][05-9]|pięć|sześć|siedem|osiem|dziewięć|dziesięć|wiele|kilka)"

PROFILE = LocaleProfile(
    code="pl",
    name="Polish",
    plural_categories=("one", "few", "many", "other"),
    plural_example="{n, plural, one {# punkt} few {# punkty} many {# punktów} other {# punktu}}",
    gettext_plural_forms="nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    expansion_band=(1.1, 1.5),
    decimal_mark=",",
    inflects=True,
    suspicious_digraphs=frozenset({"ąć", "ąę", "ąń", "ćą", "ćś", "ęą", "ęł", "ęń", "łę", "ńą", "ńę", "ść", "źż", "żź"}),
    english_word_collisions=frozenset({"a", "to"}),
    informal_prompt="Address the reader informally as 'ty' (ty, ci, cię, twój).",
    formal_prompt="Address the reader formally as 'Pan/Pani' (Pan, Pani, Państwo), capitalised.",
    informal_marker=re.compile(r"\b(?:ty|cię|twój|twoja|twoje)\b", re.I),
    formal_marker=re.compile(r"(?<=[a-ząćęłńóśźż,;] )(?:Pan|Pani|Państwo|Pana|Panu|Panią)\b"),
    typography_prompt="Use „ ” for quotation marks (low opening quote, high closing quote).",
    grammar_prompt=(
        "- Numbers: 1 takes the nominative singular, 2-4 (not 12-14) the nominative plural, "
        "5+ and 12-14 the genitive plural (1 plik, 2 pliki, 5 plików). Men and mixed groups "
        "of people take the collective form with the genitive: dwóch graczy, trzech "
        "użytkowników (never 'dwa gracze').\n"
        "- Use the case the preposition or verb requires (bez pliku, do folderu, z modelem); "
        "a negated verb takes the genitive (Nie znaleziono pliku).\n"
        "- Adjectives and past-tense verbs agree with the noun's gender and number "
        "(Plik został usunięty, Gra została zapisana).\n"
        "- Labels and headings are noun phrases in the nominative; a possessor follows in "
        "the genitive (Lewy obrońców, Ustawienia konta).\n"
        "- Buttons and menu actions use the imperative (Zapisz, Pobierz, Anuluj); progress "
        "and status text uses the verbal noun (Pobieranie…, Zapisywanie…), not the first "
        "person (not 'Pobieram…').\n"
        "- A {placeholder} cannot be declined: rephrase so the value stands in the "
        "nominative, e.g. after a colon (Gracz: {name}, Za mało: {list}) or after a noun "
        "(w folderze {path}).\n"
        "- Every ICU plural needs one, few, many and other branches."
    ),
    grammar_examples=(
        ("Two players, head to head", "Dwóch graczy, jeden na jednego"),
        ("Defender tricks", "Lewy obrońców"),
        ("{n, plural, one {# file} other {# files}}",
         "{n, plural, one {# plik} few {# pliki} many {# plików} other {# pliku}}"),
        ("File not found", "Nie znaleziono pliku"),
        ("Downloading…", "Pobieranie…"),
        ("The game was saved", "Gra została zapisana"),
        ("Winner: {name}", "Zwycięzca: {name}"),
    ),
    grammar_checks=(
        regex_check(
            "pl-numeral-personal",
            rf"(?i)\b(?:dwa|trzy|cztery|[2-4])\s+(?:{_PERSONAL_PLURALS})\b",
            "after 2-4, people take the collective numeral and genitive "
            "('dwóch graczy', '2 graczy'), not 'dwa gracze'",
            good="Dwóch graczy przy stole",
            bad="Dwa gracze przy stole",
        ),
        regex_check(
            "pl-numeral-genitive",
            rf"(?i)\b{_FIVE_PLUS}\s+(?:{_FEW_FORMS})\b",
            "after 5+ (and 12-14) use the genitive plural ('5 plików', '7 lew'), "
            "not the 2-4 form",
            good="Pobrano 5 plików",
            bad="Pobrano 5 pliki",
        ),
    ),
)
