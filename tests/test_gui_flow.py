"""Сквозной прогон интерфейса: книга → кнопка → фоновый перевод → готовый файл."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

from bt.config import Settings
from bt.epubbuild import validate_epub
from bt.importers import import_book
from tests import fixtures
from tests.test_importers import work_dir


@unittest.skipIf(QApplication is None, "PySide6 не установлен")
class GuiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = work_dir("gui_flow")
        os.environ["BT_CONFIG_DIR"] = cls.dir
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.source = fixtures.make_fb2(cls.dir)

    def test_translation_runs_to_done(self) -> None:
        from bt.gui.app import MainWindow

        settings = Settings()  # без ключа → демо-режим
        window = MainWindow(settings)
        window.current_path = self.source
        window._book_loaded(import_book(self.source))
        self.assertIs(window.stack.currentWidget(), window.book_page)

        window.start_translation(confirm_demo=False)
        self.assertIs(window.stack.currentWidget(), window.progress_page)

        loop = QEventLoop()
        error = {}

        def failed(message: str) -> None:
            error["message"] = message
            loop.quit()

        window.run_worker.done.connect(lambda _: loop.quit())
        window.run_worker.failed.connect(failed)
        QTimer.singleShot(60_000, loop.quit)
        loop.exec()

        self.assertNotIn("message", error, error.get("message"))
        self.assertIs(window.stack.currentWidget(), window.done_page)
        self.assertIsNotNone(window.outcome)
        self.assertTrue(os.path.exists(window.outcome.path))
        self.assertEqual(validate_epub(window.outcome.path), [])
        with open(window.outcome.path, "rb") as fh:
            self.assertGreater(len(fh.read()), 1000)

        window.close()

    def test_falls_back_when_output_folder_is_blocked(self) -> None:
        from bt.glossary import Glossary
        from bt.gui.worker import RunWorker

        blocked = os.path.join(self.dir, "blocked")
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("это файл, а не папка")

        book = import_book(self.source)
        worker = RunWorker(
            book=book,
            settings=Settings(),
            glossary=Glossary(),
            out_path=os.path.join(blocked, "book (RU).epub"),
            demo=True,
            cache_dir=os.path.join(self.dir, "cache-fallback"),
        )
        outcomes = []
        worker.done.connect(outcomes.append)
        worker.run()

        self.assertTrue(outcomes, "перевод не дошёл до сборки")
        produced = outcomes[0].path
        self.assertNotEqual(produced, os.path.join(blocked, "book (RU).epub"))
        self.assertTrue(os.path.exists(produced))
        self.assertEqual(validate_epub(produced), [])


if __name__ == "__main__":
    unittest.main()
