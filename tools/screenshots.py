"""Скриншоты интерфейса без открытия окна: offscreen-рендер в PNG."""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BT_CONFIG_DIR", os.path.join(tempfile.gettempdir(), "bt-shot-config"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from bt.config import Settings  # noqa: E402
from bt.gui import theme  # noqa: E402
from bt.gui.app import MainWindow, SettingsDialog  # noqa: E402
from bt.gui.worker import RunOutcome  # noqa: E402
from bt.importers import import_book  # noqa: E402


def save(widget, path: str) -> None:
    widget.grab().save(path)
    print("сохранено:", path)


def main() -> int:
    out_dir = os.path.join(ROOT, "demo", "gui")
    os.makedirs(out_dir, exist_ok=True)

    app = QApplication(sys.argv)
    theme.set_mode(False)
    app.setStyleSheet(theme.qss())

    settings = Settings()
    settings.theme_mode = "light"
    window = MainWindow(settings)
    window.resize(1000, 720)
    window.show()

    window.show_home()
    app.processEvents()
    save(window, os.path.join(out_dir, "1-home.png"))

    source = os.path.join(ROOT, "demo", "sam_en_ch1.fb2")
    if not os.path.exists(source):
        source = os.path.join(ROOT, "demo", "test.fb2")
    book = import_book(source)
    window.current_path = source
    window._book_loaded(book)
    app.processEvents()
    save(window, os.path.join(out_dir, "2-book.png"))

    # Свёрнутый/раскрытый список недавних книг.
    from PySide6.QtCore import QEventLoop, QTimer

    window.show_home()
    window.home.recents.header.click()
    loop = QEventLoop()
    QTimer.singleShot(400, loop.quit)
    loop.exec()
    save(window, os.path.join(out_dir, "1-home-recents.png"))
    window.home.recents.header.click()

    window.progress_page.start(book.meta.title)
    window.progress_page.update_progress(37, 149, 12, 14 * 60)
    window.show_progress()
    app.processEvents()
    save(window, os.path.join(out_dir, "3-progress.png"))

    window.outcome = RunOutcome(
        path=os.path.join(os.path.dirname(source), "Test (RU).epub"),
        seconds=2520, chunks=149, cached=3, failed=0, applied=41,
    )
    window.done_page.set_outcome(window.outcome)
    window.show_done()
    app.processEvents()
    save(window, os.path.join(out_dir, "4-done.png"))

    dialog = SettingsDialog(settings, window)
    dialog.resize(560, 640)
    dialog.show()
    app.processEvents()
    save(dialog, os.path.join(out_dir, "6-settings.png"))
    dialog.close()

    # Тёмная тема: те же экраны, другая палитра.
    window.settings.theme_mode = "dark"
    window.apply_theme()
    app.processEvents()
    window.show_home()
    app.processEvents()
    save(window, os.path.join(out_dir, "1-home-dark.png"))
    window.show_book()
    app.processEvents()
    save(window, os.path.join(out_dir, "2-book-dark.png"))
    dark_settings = SettingsDialog(settings, window)
    dark_settings.resize(560, 640)
    dark_settings.show()
    app.processEvents()
    save(dark_settings, os.path.join(out_dir, "6-settings-dark.png"))
    dark_settings.close()

    theme.set_mode(False)
    app.setStyleSheet(theme.qss())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
