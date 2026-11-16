"""A project's own translation files are not hardcoded text."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_locale_catalogue_files_are_skipped_but_code_is_not(tmp_path: Path) -> None:
    _write(tmp_path, "resources/js/lang/en/form.js", "export default { save: 'Save your changes now' }\n")
    _write(tmp_path, "resources/js/lang/es.js", "export default { save: 'Guardar los cambios ahora' }\n")
    _write(tmp_path, "resources/lang/zh_cn/blog.php", "<?php return ['hello' => '欢迎回来朋友们'];\n")
    _write(tmp_path, "src/i18n/en-US.js", "export const m = { hi: 'Welcome back friend' }\n")
    _write(tmp_path, "src/lang/index.js", "const toast = 'Something went wrong here'; alert(toast)\n")
    _write(tmp_path, "src/api/client.js", "document.title = 'Loading the dashboard'\n")
    hits = build_scanner("source", tmp_path, ["resources", "src"]).scan().hardcoded
    files = {h.file for h in hits}
    assert "resources/js/lang/en/form.js" not in files
    assert "resources/js/lang/es.js" not in files
    assert "resources/lang/zh_cn/blog.php" not in files
    assert "src/i18n/en-US.js" not in files
    assert "src/lang/index.js" in files          # code that lives next to catalogues still counts
    assert "src/api/client.js" in files


def test_flutter_generated_language_classes_are_catalogues() -> None:
    from pathlib import Path

    from llm_localizator.scan.base import is_catalogue_file

    assert is_catalogue_file(Path("lib/generated/l10n/l10n_ru.dart"))
    assert is_catalogue_file(Path("lib/l10n/app_localizations_zh.dart"))
    assert is_catalogue_file(Path("lib/l10n/messages_pt_BR.dart"))
    assert not is_catalogue_file(Path("lib/l10n/l10n.dart"))
    assert not is_catalogue_file(Path("lib/screens/messages_screen.dart"))
