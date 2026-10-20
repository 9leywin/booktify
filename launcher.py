"""Точка входа для сборки: то же приложение, но без консоли.

Дополнительно умеет `--selftest <файл>`: прогоняет конвейер на встроенной
мини-книге и пишет отчёт в JSON. Нужно, чтобы проверить собранный `.exe`
там, где окно не открыть.
"""

from __future__ import annotations

import json
import os
import sys

FB2 = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description><title-info>
    <book-title>Self Test</book-title>
    <lang>en</lang>
    <author><first-name>Test</first-name><last-name>Author</last-name></author>
  </title-info></description>
  <body><section>
    <title><p>Chapter One</p></title>
    <p>Corin opened the door and looked outside.</p>
    <p>The street was empty, and the sky was grey.</p>
  </section></body>
</FictionBook>
"""


def selftest(out_path: str) -> int:
    report: dict = {}
    # Каталог рядом с отчётом: `tempfile.mkdtemp` создаёт права 0700, а под
    # песочницей в такой каталог нельзя писать.
    base = os.path.dirname(os.path.abspath(out_path)) or "."
    tmp = os.path.join(base, f".bt-selftest-{os.getpid()}")
    os.makedirs(tmp, exist_ok=True)
    # Самопроверка не должна трогать настоящие настройки и ключ пользователя.
    os.environ["BT_CONFIG_DIR"] = os.path.join(tmp, "config")
    try:
        from bt.gui.app import MainWindow  # noqa: F401  (проверяет, что PySide6 собрался)

        report["pyside6"] = True

        from bt.prompts import load_prompt

        prompt = load_prompt("translate")
        report["prompt"] = f"{prompt.name} {prompt.version}"
        report["prompt_chars"] = len(prompt.system) + len(prompt.user_template)

        from bt.config import Settings, config_dir

        folder = config_dir()
        report["config_dir"] = folder
        probe = Settings()
        probe.set_api_key("selftest-key")
        probe.save()
        report["settings_saved"] = os.path.exists(os.path.join(folder, "settings.json"))
        report["key_encrypted"] = "selftest-key" not in open(
            os.path.join(folder, "settings.json"), encoding="utf-8"
        ).read()

        source = os.path.join(tmp, "book.fb2")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(FB2)

        from bt.importers import import_book

        book = import_book(source)
        report["sections"] = len(book.sections)
        report["blocks"] = book.blocks

        from bt.llm import MockClient
        from bt.translate import TranslationOptions, Translator

        translator = Translator(
            MockClient(), options=TranslationOptions(jobs=1, cache_dir=os.path.join(tmp, "cache"))
        )
        result = translator.run(book)
        report["chunks"] = result.chunks_total
        report["translated"] = len(result.blocks)

        from bt.epubbuild import build_epub, validate_epub

        out = os.path.join(tmp, "out.epub")
        warnings = build_epub(book, out, translations=result.blocks)
        problems = validate_epub(out)
        report["epub_bytes"] = os.path.getsize(out)
        report["epub_problems"] = problems + list(warnings)
        report["ok"] = not problems
    except Exception as exc:  # noqa: BLE001 - отчёт важнее трейсбека
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return 0 if report.get("ok") else 1


def _report_crash(text: str) -> None:
    """Пишет traceback в файл и показывает окно: без консоли иначе ничего не видно."""
    try:
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "BookTranslator")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "crash.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n=== crash ===\n" + text)
    except Exception:
        path = "(не удалось записать лог)"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            f"Приложение не смогло запуститься.\n\nПодробности: {path}\n\n{text[-600:]}",
            "Переводчик книг",
            0x10,
        )
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])

    try:
        from bt.gui.app import main as gui_main
    except Exception:
        import traceback

        _report_crash(traceback.format_exc())
        return 1

    try:
        return gui_main()
    except Exception:
        import traceback

        _report_crash(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
