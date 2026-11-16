"""Authored content for the synthetic projects (ADR-4 spirit: written by rules, not captured).

``CLEAN`` is a small gold catalogue in five languages. ``DEFECTS`` replaces single values with the
breakage found in the bridge catalogue, each labelled with the check that must notice it. The
strings are short UI text written for this file, not copied from any consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOCALES = ["pl", "ar", "de", "fr", "ja"]
NBSP = " "

SOURCE: dict[str, dict[str, str]] = {
    "app": {
        "save": "Save",
        "cancel": "Cancel",
        "signIn": "Sign in",
        "greeting": "Welcome back, {name}!",
        "itemCount": "{count, plural, one {# item} other {# items}}",
        "resetHint": "If this keeps happening locally, run pnpm clean:web and restart the web server.",
        "docsLink": "Read the guide at https://example.com/help",
        "boldNote": "Click <b>here</b> to continue",
    },
    "play": {
        "tableJoin": "Join table",
        "noTables": "No open tables right now",
        "bidPrompt": "Make your bid",
        "trickCount": "Tricks won: {n}",
        "partnerLooking": "Looking for a partner",
        "boardNext": "Next board",
        "tournamentList": "Upcoming tournaments",
        "claimAction": "Claim the remaining tricks",
    },
}

GOLD: dict[str, dict[str, dict[str, str]]] = {
    "pl": {
        "app": {
            "save": "Zapisz",
            "cancel": "Anuluj",
            "signIn": "Zaloguj się",
            "greeting": "Witaj ponownie, {name}!",
            "itemCount": "{count, plural, one {# element} few {# elementy} many {# elementów} other {# elementu}}",
            "resetHint": "Jeśli problem powtarza się lokalnie, uruchom pnpm clean:web i zrestartuj serwer WWW.",
            "docsLink": "Przeczytaj poradnik na https://example.com/help",
            "boldNote": "Kliknij <b>tutaj</b>, aby kontynuować",
        },
        "play": {
            "tableJoin": "Dołącz do stołu",
            "noTables": "Brak otwartych stołów w tej chwili",
            "bidPrompt": "Złóż swoją zapowiedź",
            "trickCount": "Wygrane lewy: {n}",
            "partnerLooking": "Szukam partnera",
            "boardNext": "Następne rozdanie",
            "tournamentList": "Nadchodzące turnieje",
            "claimAction": "Zgłoś pozostałe lewy",
        },
    },
    "ar": {
        "app": {
            "save": "حفظ",
            "cancel": "إلغاء",
            "signIn": "تسجيل الدخول",
            "greeting": "مرحبًا بعودتك، {name}!",
            "itemCount": "{count, plural, zero {لا عناصر} one {عنصر واحد} two {عنصران} few {# عناصر} many {# عنصرًا} other {# عنصر}}",
            "resetHint": "إذا استمرت هذه المشكلة محليًا، شغّل pnpm clean:web وأعد تشغيل خادم الويب.",
            "docsLink": "اقرأ الدليل على https://example.com/help",
            "boldNote": "انقر <b>هنا</b> للمتابعة",
        },
        "play": {
            "tableJoin": "انضم إلى الطاولة",
            "noTables": "لا توجد طاولات مفتوحة الآن",
            "bidPrompt": "قدّم مزايدتك",
            "trickCount": "الخدع المكتسبة: {n}",
            "partnerLooking": "أبحث عن شريك",
            "boardNext": "التوزيعة التالية",
            "tournamentList": "البطولات القادمة",
            "claimAction": "أعلن عن الخدع المتبقية",
        },
    },
    "de": {
        "app": {
            "save": "Speichern",
            "cancel": "Abbrechen",
            "signIn": "Anmelden",
            "greeting": "Willkommen zurück, {name}!",
            "itemCount": "{count, plural, one {# Element} other {# Elemente}}",
            "resetHint": "Falls das Problem lokal weiterhin auftritt, führe pnpm clean:web aus und starte den Webserver neu.",
            "docsLink": "Lies die Anleitung unter https://example.com/help",
            "boldNote": "Klicke <b>hier</b>, um fortzufahren",
        },
        "play": {
            "tableJoin": "Am Tisch teilnehmen",
            "noTables": "Derzeit keine offenen Tische",
            "bidPrompt": "Gib dein Gebot ab",
            "trickCount": "Gewonnene Stiche: {n}",
            "partnerLooking": "Suche einen Partner",
            "boardNext": "Nächstes Board",
            "tournamentList": "Kommende Turniere",
            "claimAction": "Restliche Stiche beanspruchen",
        },
    },
    "fr": {
        "app": {
            "save": "Enregistrer",
            "cancel": "Annuler",
            "signIn": "Se connecter",
            "greeting": f"Bon retour, {{name}}{NBSP}!",
            "itemCount": "{count, plural, one {# élément} many {# d’éléments} other {# éléments}}",
            "resetHint": "Si le problème persiste en local, exécutez pnpm clean:web et redémarrez le serveur web.",
            "docsLink": "Lisez le guide sur https://example.com/help",
            "boldNote": "Cliquez <b>ici</b> pour continuer",
        },
        "play": {
            "tableJoin": "Rejoindre la table",
            "noTables": "Aucune table ouverte pour le moment",
            "bidPrompt": "Faites votre enchère",
            "trickCount": f"Plis gagnés{NBSP}: {{n}}",
            "partnerLooking": "Je cherche un partenaire",
            "boardNext": "Donne suivante",
            "tournamentList": "Tournois à venir",
            "claimAction": "Réclamer les plis restants",
        },
    },
    "ja": {
        "app": {
            "save": "保存",
            "cancel": "キャンセル",
            "signIn": "サインイン",
            "greeting": "お帰りなさい、{name}さん！",
            "itemCount": "{count, plural, other {#件}}",
            "resetHint": "この問題がローカルで繰り返し発生する場合は、pnpm clean:web を実行してウェブサーバーを再起動してください。",
            "docsLink": "ガイド https://example.com/help をご覧ください",
            "boldNote": "続行するには<b>こちら</b>をクリックしてください",
        },
        "play": {
            "tableJoin": "テーブルに参加",
            "noTables": "現在、開いているテーブルはありません",
            "bidPrompt": "ビッドしてください",
            "trickCount": "獲得トリック数：{n}",
            "partnerLooking": "パートナーを募集中",
            "boardNext": "次のボード",
            "tournamentList": "今後のトーナメント",
            "claimAction": "残りのトリックをクレーム",
        },
    },
}

#: Translator notes and HTML flags a well-kept project carries (V11, V19, V20 stay quiet).
CONTEXT = {
    "app": {
        "greeting": {"note": "Greets the signed-in player by name"},
        "itemCount": {"note": "How many items are in a list"},
        "boldNote": {"note": "Link text inside a sentence", "html": True},
    },
    "play": {
        "trickCount": {"note": "Number of tricks the player has won so far"},
    },
}

GLOSSARY = {
    "doNotTranslate": [],
    "terms": {
        "table": {"pl": "stół", "ar": "طاولة", "de": "Tisch", "fr": "table", "ja": "テーブル"},
        "bid": {
            "pl": "zapowiedź", "pl_forbidden": ["sztuczka"], "ar": "مزايدة",
            "de": "Gebot", "fr": "enchère", "ja": "ビッド",
        },
        "trick": {
            "pl": "lewa", "pl_forbidden": ["sztuczka", "sztuczki"], "ar": "خدعة",
            "de": "Stich", "fr": "pli", "ja": "トリック",
        },
        "partner": {"pl": "partner", "ar": "الشريك", "de": "Partner", "fr": "partenaire", "ja": "パートナー"},
        "board": {"pl": "rozdanie", "ar": "التوزيعة", "de": "Board", "fr": "donne", "ja": "ボード"},
        "tournament": {"pl": "turniej", "ar": "بطولة", "de": "Turnier", "fr": "tournoi", "ja": "トーナメント"},
    },
}


@dataclass(frozen=True)
class Defect:
    """One seeded defect: where it is, what it is, and what must notice it."""

    id: str
    locale: str
    namespace: str
    key: str
    value: str
    cls: str
    expect: tuple[str, ...]  # check ids that validate must report for this key
    hard: bool  # import must reject it
    provenance: dict = field(default_factory=dict)  # model / provider / status of the state entry


_IMPORT = {"model": "import", "provider": "import", "status": "human"}
_SMALL = {"model": "qwen2.5:7b", "provider": "local", "status": "machine"}

DEFECTS: list[Defect] = [
    Defect("backslash-cut-pl", "pl", "app", "resetHint",
           "Jeśli problem powtarza się lokalnie\\", "backslash", ("V39",), True, _IMPORT),
    Defect("backslash-mid-pl", "pl", "app", "docsLink",
           "Przeczytaj poradnik na https://example.com/help\\, aby poznać szczegóły",
           "backslash", ("V39",), False, _IMPORT),  # import repairs `\,` instead of refusing
    Defect("backslash-cut-ar", "ar", "app", "resetHint",
           "إذا استمرت هذه المشكلة محليًا\\", "backslash", ("V39",), True,
           {"model": "translategemma:4b", "provider": "local", "status": "machine"}),
    Defect("cjk-ar", "ar", "play", "tableJoin",
           "انضم إلى الطاولة 次级人员", "foreign-script", ("V21",), True, _SMALL),
    Defect("latin-ar-a", "ar", "app", "signIn",
           "Access تسجيل الدخول", "latin-leftover", ("V21",), False, _SMALL),
    Defect("latin-ar-b", "ar", "play", "noTables",
           "لا توجد Access مفتوحة الآن", "latin-leftover", ("V21",), False, _SMALL),
    Defect("placeholder-pl", "pl", "app", "greeting",
           "Witaj ponownie!", "placeholder", ("V02",), True, _SMALL),
    Defect("forbidden-pl", "pl", "play", "trickCount",
           "Wygrane sztuczki: {n}", "forbidden-term", ("V04",), True, _SMALL),
    Defect("wrong-term-pl", "pl", "play", "boardNext",
           "Następna tablica", "wrong-term", ("V13",), False, _SMALL),
    Defect("html-de", "de", "app", "boldNote",
           "Klicke hier, um fortzufahren", "html", ("V27",), True, _SMALL),
    Defect("plural-pl", "pl", "app", "itemCount",
           "{count, plural, one {# element} other {# elementów}}", "plural", ("V03",), True, _SMALL),
    Defect("literal-fr", "fr", "app", "docsLink",
           "Lisez le guide", "literal", ("V32",), True, _SMALL),
]
