"""Human-language matrix: the same five UI phrases in many languages, grouped by writing-system type.

The scanner must find a Polish, Thai or Arabic label as reliably as the English one. Each language gives:
``label`` (one word on a button), ``action`` (two or three words), ``sentence``, ``question`` (with the language's own
question mark) and ``greet`` (a greeting). Groups name what is peculiar about the writing system.
"""

from __future__ import annotations

KINDS = ("label", "action", "sentence", "question", "greet")

#: group -> what is peculiar
GROUPS: dict[str, str] = {
    "latin-plain": "ASCII letters only, capitalised words, spaces, ASCII punctuation",
    "latin-diacritics": "accented capitals and lower-case (Ł, Ś, É, Ü, İ), Spanish inverted marks, French spaced punctuation, German noun capitals",
    "cyrillic-greek-armenian-georgian": "cased or partly cased non-Latin scripts, Greek question mark, Armenian full stop, Georgian without case",
    "rtl-abjad": "right-to-left, no case, Arabic question mark and comma, optional diacritics, zero-width joiners (Persian)",
    "indic-abugida": "Devanagari, Bengali, Tamil: spaces between words, combining vowel signs, danda as full stop, no case",
    "cjk": "Han and kana without spaces, full-width punctuation, Hangul with spaces, honorific suffixes after interpolation",
    "sea-unsegmented": "Thai, Lao, Khmer, Burmese: no spaces between words, no sentence-end punctuation (Thai), combining marks",
    "ethiopic": "Ethiopic syllabary with its own full stop and spaces",
}

LANGS: dict[str, tuple[str, dict[str, str]]] = {
    "en": ("latin-plain", {"label": "Save", "action": "Save changes", "sentence": "Your session has expired.",
                           "question": "Do you want to delete this file?", "greet": "Welcome back to the app!"}),
    "nl": ("latin-plain", {"label": "Opslaan", "action": "Wijzigingen opslaan", "sentence": "Uw sessie is verlopen.",
                           "question": "Wilt u dit bestand verwijderen?", "greet": "Welkom terug in de app!"}),
    "sv": ("latin-plain", {"label": "Spara", "action": "Spara ändringar", "sentence": "Din session har gått ut.",
                           "question": "Vill du ta bort den här filen?", "greet": "Välkommen tillbaka till appen!"}),
    "es": ("latin-diacritics", {"label": "Guardar", "action": "Guardar cambios", "sentence": "Su sesión ha caducado.",
                                "question": "¿Desea eliminar este archivo?", "greet": "¡Bienvenido de nuevo a la aplicación!"}),
    "fr": ("latin-diacritics", {"label": "Enregistrer", "action": "Enregistrer les modifications", "sentence": "Votre session a expiré.",
                                "question": "Voulez-vous supprimer ce fichier ?", "greet": "Bon retour dans notre application !"}),
    "de": ("latin-diacritics", {"label": "Speichern", "action": "Änderungen speichern", "sentence": "Ihre Sitzung ist abgelaufen.",
                                "question": "Möchten Sie diese Datei löschen?", "greet": "Willkommen zurück in der App!"}),
    "pl": ("latin-diacritics", {"label": "Zapisz", "action": "Zapisz zmiany", "sentence": "Twoja sesja wygasła.",
                                "question": "Czy chcesz usunąć ten plik?", "greet": "Witaj ponownie w aplikacji!"}),
    "pl2": ("latin-diacritics", {"label": "Błąd", "action": "Łączenie z serwerem", "sentence": "Nie udało się zapisać pliku.",
                                 "question": "Czy na pewno chcesz wyjść?", "greet": "Ścieżka została zapisana!"}),
    "cs": ("latin-diacritics", {"label": "Uložit", "action": "Uložit změny", "sentence": "Vaše relace vypršela.",
                                "question": "Chcete smazat tento soubor?", "greet": "Vítejte zpět v aplikaci!"}),
    "tr": ("latin-diacritics", {"label": "Kaydet", "action": "Değişiklikleri kaydet", "sentence": "Oturumunuzun süresi doldu.",
                                "question": "Bu dosyayı silmek istiyor musunuz?", "greet": "Uygulamaya tekrar hoş geldiniz!"}),
    "tr2": ("latin-diacritics", {"label": "İptal", "action": "Ürünü sepete ekle", "sentence": "Şifre en az sekiz karakter olmalı.",
                                 "question": "Çıkış yapmak istiyor musunuz?", "greet": "Işık seviyesi ayarlandı!"}),
    "vi": ("latin-diacritics", {"label": "Lưu", "action": "Lưu thay đổi", "sentence": "Phiên của bạn đã hết hạn.",
                                "question": "Bạn có muốn xóa tệp này không?", "greet": "Chào mừng bạn quay lại ứng dụng!"}),
    "ru": ("cyrillic-greek-armenian-georgian", {"label": "Сохранить", "action": "Сохранить изменения", "sentence": "Ваш сеанс истёк.",
                                                "question": "Вы хотите удалить этот файл?", "greet": "С возвращением в приложение!"}),
    "uk": ("cyrillic-greek-armenian-georgian", {"label": "Зберегти", "action": "Зберегти зміни", "sentence": "Ваш сеанс завершився.",
                                                "question": "Ви хочете видалити цей файл?", "greet": "З поверненням у застосунок!"}),
    "el": ("cyrillic-greek-armenian-georgian", {"label": "Αποθήκευση", "action": "Αποθήκευση αλλαγών", "sentence": "Η συνεδρία σας έληξε.",
                                                "question": "Θέλετε να διαγράψετε αυτό το αρχείο;", "greet": "Καλώς ήρθατε ξανά στην εφαρμογή!"}),
    "hy": ("cyrillic-greek-armenian-georgian", {"label": "Պահպանել", "action": "Պահպանել փոփոխությունները", "sentence": "Ձեր նիստը ավարտվել է։",
                                                "question": "Ցանկանու՞մ եք ջնջել այս ֆայլը։", "greet": "Բարի վերադարձ հավելված!"}),
    "ka": ("cyrillic-greek-armenian-georgian", {"label": "შენახვა", "action": "ცვლილებების შენახვა", "sentence": "თქვენი სესია ამოიწურა.",
                                                "question": "გსურთ ამ ფაილის წაშლა?", "greet": "კეთილი იყოს თქვენი დაბრუნება!"}),
    "ar": ("rtl-abjad", {"label": "حفظ", "action": "حفظ التغييرات", "sentence": "انتهت جلستك.",
                         "question": "هل تريد حذف هذا الملف؟", "greet": "مرحباً بعودتك إلى التطبيق!"}),
    "fa": ("rtl-abjad", {"label": "ذخیره", "action": "ذخیره تغییرات", "sentence": "نشست شما منقضی شده است.",
                         "question": "آیا می‌خواهید این فایل را حذف کنید؟", "greet": "به برنامه خوش آمدید!"}),
    "ur": ("rtl-abjad", {"label": "محفوظ", "action": "تبدیلیاں محفوظ کریں", "sentence": "آپ کا سیشن ختم ہو گیا ہے۔",
                         "question": "کیا آپ یہ فائل حذف کرنا چاہتے ہیں؟", "greet": "ایپ میں دوبارہ خوش آمدید!"}),
    "he": ("rtl-abjad", {"label": "שמור", "action": "שמור שינויים", "sentence": "ההפעלה שלך פגה.",
                         "question": "האם ברצונך למחוק קובץ זה?", "greet": "ברוך שובך לאפליקציה!"}),
    "hi": ("indic-abugida", {"label": "सहेजें", "action": "परिवर्तन सहेजें", "sentence": "आपका सत्र समाप्त हो गया है।",
                             "question": "क्या आप इस फ़ाइल को हटाना चाहते हैं?", "greet": "ऐप में वापसी पर स्वागत है!"}),
    "bn": ("indic-abugida", {"label": "সংরক্ষণ", "action": "পরিবর্তন সংরক্ষণ করুন", "sentence": "আপনার সেশন শেষ হয়ে গেছে।",
                             "question": "আপনি কি এই ফাইলটি মুছতে চান?", "greet": "অ্যাপে আবার স্বাগতম!"}),
    "ta": ("indic-abugida", {"label": "சேமி", "action": "மாற்றங்களைச் சேமி", "sentence": "உங்கள் அமர்வு காலாவதியானது.",
                             "question": "இந்தக் கோப்பை நீக்க விரும்புகிறீர்களா?", "greet": "பயன்பாட்டிற்கு மீண்டும் வருக!"}),
    "zh": ("cjk", {"label": "保存", "action": "保存更改", "sentence": "您的会话已过期。",
                   "question": "您要删除此文件吗？", "greet": "欢迎回到应用！"}),
    "zh-Hant": ("cjk", {"label": "儲存", "action": "儲存變更", "sentence": "您的工作階段已過期。",
                        "question": "您要刪除此檔案嗎？", "greet": "歡迎回到應用程式！"}),
    "ja": ("cjk", {"label": "保存", "action": "変更を保存", "sentence": "セッションの有効期限が切れました。",
                   "question": "このファイルを削除しますか？", "greet": "アプリへおかえりなさい！"}),
    "ja-kana": ("cjk", {"label": "キャンセル", "action": "ファイルを開く", "sentence": "ネットワークに接続できません。",
                        "question": "本当に終了しますか？", "greet": "ようこそ、アプリへ！"}),
    "ko": ("cjk", {"label": "저장", "action": "변경 사항 저장", "sentence": "세션이 만료되었습니다.",
                   "question": "이 파일을 삭제하시겠습니까?", "greet": "앱에 다시 오신 것을 환영합니다!"}),
    "th": ("sea-unsegmented", {"label": "บันทึก", "action": "บันทึกการเปลี่ยนแปลง", "sentence": "เซสชันของคุณหมดอายุแล้ว",
                               "question": "คุณต้องการลบไฟล์นี้หรือไม่", "greet": "ยินดีต้อนรับกลับสู่แอป"}),
    "lo": ("sea-unsegmented", {"label": "ບັນທຶກ", "action": "ບັນທຶກການປ່ຽນແປງ", "sentence": "ເຊດຊັນຂອງທ່ານໝົດອາຍຸແລ້ວ",
                               "question": "ທ່ານຕ້ອງການລຶບໄຟລ໌ນີ້ບໍ", "greet": "ຍິນດີຕ້ອນຮັບກັບມາສູ່ແອັບ"}),
    "km": ("sea-unsegmented", {"label": "រក្សាទុក", "action": "រក្សាទុកការផ្លាស់ប្តូរ", "sentence": "សម័យរបស់អ្នកបានផុតកំណត់ហើយ។",
                               "question": "តើអ្នកចង់លុបឯកសារនេះទេ?", "greet": "សូមស្វាគមន៍ត្រឡប់មកវិញ"}),
    "my": ("sea-unsegmented", {"label": "သိမ်းဆည်းပါ", "action": "ပြောင်းလဲမှုများကို သိမ်းဆည်းပါ", "sentence": "သင့်စက်ရှင် သက်တမ်းကုန်သွားပါပြီ။",
                               "question": "ဤဖိုင်ကို ဖျက်လိုပါသလား။", "greet": "အက်ပ်သို့ ပြန်လည်ကြိုဆိုပါတယ်"}),
    "am": ("ethiopic", {"label": "አስቀምጥ", "action": "ለውጦችን አስቀምጥ", "sentence": "ክፍለ ጊዜዎ አብቅቷል።",
                        "question": "ይህን ፋይል መሰረዝ ይፈልጋሉ?", "greet": "እንኳን ደህና መጡ!"}),
}

#: Host snippets; ``@P@`` is the phrase. Every host puts text where a person reads it.
HOSTS: dict[str, tuple[str, str]] = {
    "html": ("page.html", '<button>@P@</button>'),
    "js": ("app.js", 'alert("@P@");'),
    "python": ("app.py", 'flash("@P@")'),
    "kotlin": ("App.kt", 'Toast.makeText(ctx, "@P@", Toast.LENGTH_SHORT).show()'),
    "swift": ("View.swift", 'Text("@P@")'),
    "vue": ("Page.vue", '<template><p>@P@</p></template>'),
    "tsx": ("Page.tsx", 'export const A = () => <button>@P@</button>;'),
    "java": ("Main.java", 'JOptionPane.showMessageDialog(null, "@P@");'),
    "csharp": ("Main.cs", 'MessageBox.Show("@P@");'),
    "dart": ("main.dart", "final w = Text('@P@');"),
    "go": ("main.go", 'http.Error(w, "@P@", 400)'),
    "php": ("page.php", 'echo "@P@";'),
    "ruby": ("app.rb", 'flash[:alert] = "@P@"'),
    "rust": ("main.rs", 'println!("@P@");'),
    "xaml": ("Main.xaml", '<Button Content="@P@" />'),
    "erb": ("page.erb", '<p>@P@</p>'),
}

#: Developer-only uses of the same sentences: the scanner must stay silent. ``@P@`` is the language's sentence.
NEGATIVE_HOSTS: dict[str, tuple[str, dict[str, str]]] = {
    "js": ("app.js", {"comment": "// @P@\nconst x = 1;", "log": 'console.log("@P@");'}),
    "python": ("app.py", {"comment": "# @P@\nx = 1", "log": 'logger.info("@P@")'}),
    "kotlin": ("App.kt", {"comment": "// @P@\nval x = 1", "log": 'Log.d(TAG, "@P@")'}),
    "swift": ("View.swift", {"comment": "// @P@\nlet x = 1", "log": 'logger.info("@P@")'}),
    "java": ("Main.java", {"comment": "// @P@\nint x = 1;", "log": 'logger.info("@P@");'}),
    "go": ("main.go", {"comment": "// @P@\nvar x = 1", "log": 'log.Printf("@P@")'}),
    "rust": ("main.rs", {"comment": "// @P@\nlet x = 1;", "log": 'info!("@P@");'}),
    "csharp": ("Main.cs", {"comment": "// @P@\nvar x = 1;", "log": '_logger.LogInformation("@P@");'}),
    "php": ("page.php", {"comment": "// @P@\n$x = 1;", "log": 'error_log("@P@");'}),
    "html": ("page.html", {"comment": "<!-- @P@ -->\n<div></div>", "log": '<script>console.log("@P@");</script>'}),
}

#: Peculiarities beyond the five phrase shapes. Each is derived from a language's phrases. ``@P@`` is the text.
EXTRA_KINDS = ("interp", "mixed", "digits", "nfd", "char1")
CHAR1 = {"zh": "删", "zh-Hant": "刪", "ja": "戻", "ko": "예"}
NATIVE_DIGITS = {"ar": "٣٠", "fa": "۳۰", "ur": "۳۰", "hi": "३०", "bn": "৩০", "my": "၃၀", "th": "๓๐", "km": "៣០", "lo": "໓໐"}

#: host -> (file, template with ``@P@`` and ``@I@`` = the host's interpolation of ``name``)
EXTRA_HOSTS: dict[str, tuple[str, str, str]] = {
    "js": ("app.js", 'alert(`@P@`);', "${name}"),
    "python": ("app.py", 'flash(f"@P@")', "{name}"),
    "kotlin": ("App.kt", 'Toast.makeText(ctx, "@P@", Toast.LENGTH_SHORT).show()', "$name"),
    "swift": ("View.swift", 'Text("@P@")', r"\(name)"),
    "html": ("page.html", "<p>@P@</p>", "{{ name }}"),
}
