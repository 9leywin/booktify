import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - зависит от окружения
    QApplication = None

from bt.config import Settings
from bt.importers import import_book
from tests import fixtures
from tests.test_importers import work_dir


@unittest.skipIf(QApplication is None, "PySide6 не установлен")
class GuiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = work_dir("gui")
        os.environ["BT_CONFIG_DIR"] = cls.dir
        cls.app = QApplication.instance() or QApplication(sys.argv)
        from bt.gui import theme

        theme.set_mode(False)
        cls.app.setStyleSheet(theme.qss())
        cls.source = fixtures.make_fb2(cls.dir)

    def setUp(self) -> None:
        from bt.gui.app import MainWindow

        self.window = MainWindow(Settings())

    def tearDown(self) -> None:
        self.window.close()

    def test_four_screens(self) -> None:
        self.assertEqual(self.window.stack.count(), 4)
        self.assertIs(self.window.stack.currentWidget(), self.window.home)

    def test_book_loaded(self) -> None:
        book = import_book(self.source)
        self.window.current_path = self.source
        self.window._book_loaded(book)
        self.assertIs(self.window.stack.currentWidget(), self.window.book_page)
        self.assertIn("Test FB2", self.window.book_page.title.text())
        self.assertIn("(RU).epub", self.window.book_page.output_hint.text())

    def test_progress_and_done(self) -> None:
        from bt.gui.worker import RunOutcome

        self.window.progress_page.start("Test")
        self.window.progress_page.update_progress(5, 10, 2, 120)
        self.assertEqual(self.window.progress_page.ring._value, 50)

        outcome = RunOutcome(path=os.path.join(self.dir, "x (RU).epub"), seconds=600,
                             chunks=10, cached=1, failed=0, applied=3)
        self.window._on_done(outcome)
        self.assertIs(self.window.stack.currentWidget(), self.window.done_page)

    def test_key_banner_toggles(self) -> None:
        self.assertFalse(self.window.home.welcome.isHidden())
        self.window.home.set_key_present(True)
        self.assertTrue(self.window.home.welcome.isHidden())
        self.window.home.set_key_present(False)
        self.assertFalse(self.window.home.welcome.isHidden())

    def test_window_has_icon(self) -> None:
        self.assertFalse(self.window.windowIcon().isNull())

    def test_book_opens_even_if_settings_cannot_be_saved(self) -> None:
        from unittest import mock

        book = import_book(self.source)
        self.window.current_path = self.source
        with mock.patch("bt.config.Settings.save", side_effect=PermissionError("denied")):
            with mock.patch("bt.gui.app.QMessageBox.warning") as warning:
                self.window._book_loaded(book)
        self.assertIs(self.window.stack.currentWidget(), self.window.book_page)
        warning.assert_not_called()

    def test_show_key_toggle(self) -> None:
        from PySide6.QtWidgets import QLineEdit

        from bt.gui.app import SettingsDialog

        dialog = SettingsDialog(Settings(), self.window)
        self.assertEqual(dialog.api_key.echoMode(), QLineEdit.Password)
        dialog.show_key.setChecked(True)
        self.assertEqual(dialog.api_key.echoMode(), QLineEdit.Normal)
        self.assertEqual(dialog.show_key.text(), "Скрыть")
        dialog.close()

    def test_progress_title_is_shortened(self) -> None:
        self.window.progress_page.start("Очень длинное название книги " * 6)
        self.assertLess(len(self.window.progress_page.title.text()), 70)

    def test_log_file_is_written(self) -> None:
        from bt import applog

        applog.log("проверка журнала")
        path = applog.log_path()
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fh:
            self.assertIn("проверка журнала", fh.read())

    def test_import_watchdog_is_safe_without_worker(self) -> None:
        self.window.import_worker = None
        self.window._import_slow()  # не должно ни падать, ни показывать окно

    def test_progress_phases_share_one_ring(self) -> None:
        page = self.window.progress_page
        page.start("Test")
        page.set_phase("translate")
        page.update_progress(10, 10, 0, 60)
        self.assertEqual(page.ring._value, 70)
        page.set_phase("review")
        page.update_progress(5, 10, 0, 60)
        self.assertEqual(page.ring._value, 85)
        self.assertIn("Вычитываем", page.stage.text())

    def test_show_folder_opens_the_book_folder(self) -> None:
        from unittest import mock

        from bt.gui.worker import RunOutcome

        outcome = RunOutcome(path=os.path.join(self.dir, "x (RU).epub"),
                             seconds=1, chunks=1, cached=0, failed=0)
        self.window.outcome = outcome
        with mock.patch("bt.diagnostics.integrity_level", return_value="medium"), \
                mock.patch("os.startfile") as startfile:
            self.window._show_result_folder()
        startfile.assert_called_once_with(self.dir)

    def test_low_integrity_does_not_spawn_explorer(self) -> None:
        from unittest import mock

        from bt.gui.worker import RunOutcome

        outcome = RunOutcome(path=os.path.join(self.dir, "x (RU).epub"),
                             seconds=1, chunks=1, cached=0, failed=0)
        self.window.outcome = outcome
        with mock.patch("bt.diagnostics.integrity_level", return_value="low"), \
                mock.patch("bt.gui.app.QMessageBox.information") as info, \
                mock.patch("subprocess.Popen") as popen:
            self.window._show_result_folder()
        popen.assert_not_called()
        info.assert_called_once()

    def test_dark_theme_changes_palette(self) -> None:
        from bt.gui import theme

        theme.set_mode(False)
        light = theme.qss()
        theme.set_mode(True)
        dark = theme.qss()

        self.assertNotEqual(light, dark)
        self.assertIn(theme.BG, dark)
        self.assertNotIn("#F5F7FB", dark)

        theme.set_mode(False)
        self.app.setStyleSheet(theme.qss())

    def test_recents_are_collapsed_by_default(self) -> None:
        panel = self.window.home.recents
        panel.set_recents([self.source])

        self.assertEqual(panel.body.maximumHeight(), 0)
        self.assertGreater(panel._target_height(), 0)
        self.assertIn("1", panel.header.text())

    def test_settings_have_theme_and_no_jobs(self) -> None:
        from bt.gui.app import SettingsDialog

        dialog = SettingsDialog(Settings(), self.window)
        self.assertEqual(dialog.theme.currentData(), "system")
        self.assertFalse(hasattr(dialog, "jobs"))
        self.assertFalse(hasattr(dialog, "model_hint"))
        self.assertEqual(dialog.provider.count(), 3)
        self.assertIn("DeepSeek", [dialog.provider.itemText(i) for i in range(3)])

        dialog.theme.setCurrentIndex(2)
        self.assertEqual(dialog.theme.currentData(), "dark")
        dialog.close()

    def test_models_fill_combo_after_key_check(self) -> None:
        from bt.gui.app import SettingsDialog

        dialog = SettingsDialog(Settings(), self.window)
        dialog.model.setCurrentText("deepseek-flash")
        dialog._models_loaded(["deepseek-flash", "deepseek-v4-pro", "other-model"])
        self.assertEqual(dialog.model.count(), 3)
        self.assertEqual(dialog.model.currentText(), "deepseek-flash")
        self.assertIn("Ключ работает", dialog.key_status.text())
        dialog.close()

    def test_version_is_shown_in_status_bar(self) -> None:
        from PySide6.QtWidgets import QLabel

        from bt import __version__

        labels = self.window.statusBar().findChildren(QLabel)
        self.assertTrue(any(__version__ in label.text() for label in labels))

    def test_plural(self) -> None:
        from bt.gui.app import plural

        self.assertEqual(plural(1, "глава", "главы", "глав"), "глава")
        self.assertEqual(plural(2, "глава", "главы", "глав"), "главы")
        self.assertEqual(plural(5, "глава", "главы", "глав"), "глав")
        self.assertEqual(plural(11, "глава", "главы", "глав"), "глав")
        self.assertEqual(plural(21, "глава", "главы", "глав"), "глава")

    def test_quality_switch_updates_estimate(self) -> None:
        from tests import fixtures

        book = fixtures.make_book(block_count=200, words_per_block=100)  # 20 000 слов
        self.window.current_path = os.path.join(self.dir, "big.epub")
        self.window._book_loaded(book)

        self.window.book_page._choose_quality("fast")
        fast_text = self.window.book_page.estimate.text()

        self.window.book_page._choose_quality("max")
        max_text = self.window.book_page.estimate.text()

        self.assertNotEqual(fast_text, max_text)
        self.assertIn("мин", max_text)
        self.assertEqual(self.window.settings.quality, "max")

    def test_estimate_helper_is_mode_aware(self) -> None:
        from bt.gui.app import estimate

        fast = estimate(100_000, "fast")
        standard = estimate(100_000, "standard")
        maximum = estimate(100_000, "max")

        self.assertLess(fast[0], standard[0])
        self.assertLess(standard[0], maximum[0])
        self.assertLess(fast[1], standard[1])
        self.assertLess(standard[1], maximum[1])

    def test_output_hint_is_shortened(self) -> None:
        from bt.gui.app import shorten

        long_text = "Получится: " + "очень длинное имя " * 10 + "(RU).epub"
        self.assertLessEqual(len(shorten(long_text, 72)), 72)
        self.assertTrue(shorten(long_text, 72).endswith("…"))


if __name__ == "__main__":
    unittest.main()
