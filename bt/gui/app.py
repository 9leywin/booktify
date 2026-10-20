"""Окно приложения: четыре экрана и два диалога.

Сценарий ровно один и без развилок: кинул книгу → посмотрел, что распозналось →
нажал «Перевести» → дождался → открыл файл. Всё остальное — мелкие кнопки сбоку.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import applog, diagnostics
from ..config import MODELS, PROVIDERS, QUALITY, Settings, config_dir
from ..model import Book
from . import theme
from .widgets import CoverView, DropZone, ProgressRing, RecentsPanel, human_size
from .worker import ImportWorker, RunOutcome, RunWorker, default_cache_dir

def resource_path(*parts: str) -> str:
    """Файл рядом с приложением: в сборке — во временном каталоге PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, *parts)


def apply_icon(app: QApplication) -> None:
    icon = QIcon(resource_path("assets", "icon.png"))
    if not icon.isNull():
        app.setWindowIcon(icon)


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        applog.log("необработанная ошибка:\n" + text)
        try:
            QMessageBox.critical(
                None,
                "Что-то пошло не так",
                "Приложение столкнулось с ошибкой и записало подробности в журнал.\n\n"
                f"{applog.log_path()}\n\n{exc}",
            )
        except Exception:
            pass

    sys.excepthook = hook


# --------------------------------------------------------------------- экраны


class HomePage(QWidget):
    fileChosen = Signal(str)
    settingsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 32, 48, 32)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title = QLabel("Booktify")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch()
        settings = QPushButton(" Настройки")
        settings.setObjectName("Pill")
        settings.setCursor(Qt.PointingHandCursor)
        settings.setToolTip("Сервис, ключ и папка для готовых книг")
        gear = QIcon(resource_path("assets", "gear.png"))
        if not gear.isNull():
            settings.setIcon(gear)
            settings.setIconSize(QSize(18, 18))
        settings.clicked.connect(self.settingsRequested)
        header.addWidget(settings)
        layout.addLayout(header)

        subtitle = QLabel("Переводим книги целиком — от первой страницы до последней.")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(subtitle)

        self.welcome = QFrame()
        self.welcome.setObjectName("Card")
        welcome_layout = QHBoxLayout(self.welcome)
        welcome_layout.setContentsMargins(18, 14, 18, 14)
        welcome_text = QLabel(
            "Чтобы переводить по-настоящему, добавь ключ доступа. Без него включён демо-режим."
        )
        welcome_text.setWordWrap(True)
        welcome_layout.addWidget(welcome_text, stretch=1)
        welcome_button = QPushButton("Добавить ключ")
        welcome_button.clicked.connect(self.settingsRequested)
        welcome_layout.addWidget(welcome_button)
        self.welcome.setVisible(False)
        layout.addWidget(self.welcome)

        self.drop = DropZone()
        self.drop.fileChosen.connect(self.fileChosen)
        layout.addWidget(self.drop, stretch=1)

        self.recents = RecentsPanel()
        self.recents.fileChosen.connect(self.fileChosen)
        layout.addWidget(self.recents)

        hint = QLabel("Файлы никуда не отправляются, кроме сервиса перевода. Ключ хранится на этом компьютере.")
        hint.setObjectName("Stat")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.set_recents([])

    def set_recents(self, paths: list[str]) -> None:
        self.recents.set_recents(paths)

    def set_key_present(self, present: bool) -> None:
        self.welcome.setVisible(not present)


class BookPage(QWidget):
    backRequested = Signal()
    startRequested = Signal()
    qualityChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 28, 48, 32)
        layout.setSpacing(16)

        back = QPushButton("← Назад")
        back.setObjectName("Quiet")
        back.clicked.connect(self.backRequested)
        layout.addWidget(back, alignment=Qt.AlignLeft)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(24)

        self.cover = CoverView()
        card_layout.addWidget(self.cover, alignment=Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)
        self.title = QLabel("")
        self.title.setObjectName("H1")
        self.title.setWordWrap(True)
        info.addWidget(self.title)

        self.author = QLabel("")
        self.author.setObjectName("Subtitle")
        info.addWidget(self.author)

        self.stats = QLabel("")
        self.stats.setObjectName("Stat")
        info.addWidget(self.stats)

        self.estimate = QLabel("")
        self.estimate.setObjectName("Stat")
        info.addWidget(self.estimate)

        info.addSpacing(8)
        quality_caption = QLabel("Качество")
        quality_caption.setObjectName("Stat")
        info.addWidget(quality_caption)

        self.segments: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        row = QHBoxLayout()
        row.setSpacing(8)
        for key, meta in QUALITY.items():
            button = QPushButton(f"{meta['title']}\n{meta['hint']}")
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _=False, k=key: self._choose_quality(k))
            group.addButton(button)
            self.segments[key] = button
            row.addWidget(button)
        info.addLayout(row)

        self.output_hint = QLabel("")
        self.output_hint.setObjectName("Stat")
        info.addWidget(self.output_hint)

        info.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        self.start = QPushButton("Перевести")
        self.start.setObjectName("Primary")
        self.start.setMinimumWidth(220)
        self.start.clicked.connect(self.startRequested)
        actions.addWidget(self.start)
        info.addLayout(actions)

        card_layout.addLayout(info, stretch=1)
        layout.addWidget(card, stretch=1)

        self.book: Book | None = None
        self.path = ""
        self._settings: Settings | None = None
        self._quality = "standard"

    def _choose_quality(self, key: str) -> None:
        for name, button in self.segments.items():
            button.setChecked(name == key)
        changed = key != self._quality
        self._quality = key
        if self._settings is not None:
            self._settings.quality = key
        self.refresh_estimate()
        if changed:
            self.qualityChanged.emit(key)

    def set_book(self, book: Book, path: str, settings: Settings) -> None:
        self.book = book
        self.path = path
        self._settings = settings
        self.title.setText(book.meta.title or os.path.basename(path))
        self.author.setText(", ".join(book.meta.authors) or "автор не указан")
        chapters = len([s for s in book.sections if s.kind in ("chapter", "appendix")])
        self.stats.setText(
            f"{chapters} {plural(chapters, 'глава', 'главы', 'глав')}  ·  "
            f"{book.words} {plural(book.words, 'слово', 'слова', 'слов')}  ·  "
            f"{book.blocks} {plural(book.blocks, 'блок', 'блока', 'блоков')}"
        )

        data = book.assets.get(book.meta.cover_href or "", None)
        self.cover.set_book(book.meta.title or "", data)

        stem = os.path.splitext(os.path.basename(path))[0]
        hint = f"Получится: {stem} (RU).epub"
        self.output_hint.setText(shorten(hint, 72))
        self.output_hint.setToolTip(hint)

        self._quality = settings.quality
        for name, button in self.segments.items():
            button.setChecked(name == settings.quality)
        self.refresh_estimate()

    def refresh_estimate(self) -> None:
        if self.book is None or self._settings is None:
            return
        minutes, price = estimate(self.book.words, self._quality, self._settings.provider)
        self.estimate.setText(f"≈ {minutes} мин  ·  ≈ ${price:.2f}")


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


#: Сколько примерно идёт книга и сколько стоит — на 1000 слов оригинала.
TIME_PER_1K = {"fast": 0.7, "standard": 1.1, "max": 1.6}
PRICE_PER_1K = {"fast": 0.004, "standard": 0.008, "max": 0.03}


def estimate(words: int, quality: str, provider: str = "DeepSeek") -> tuple[int, float]:
    words = max(words, 1)
    minutes = max(1, round(words / 1000 * TIME_PER_1K.get(quality, 1.1)))
    price = words / 1000 * PRICE_PER_1K.get(quality, 0.008)
    if provider != "DeepSeek":
        price *= 3
    return minutes, price


def plural(number: int, one: str, few: str, many: str) -> str:
    """1 глава, 2 главы, 5 глав — иначе интерфейс звучит как машинный перевод."""
    n10, n100 = abs(number) % 10, abs(number) % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


class ProgressPage(QWidget):
    cancelRequested = Signal()

    #: Этап → (подпись, начало в процентах, сколько процентов занимает).
    PHASES = {
        "glossary": ("Собираем имена и термины…", 0, 5),
        "translate": ("Переводим книгу", 5, 65),
        "review": ("Вычитываем перевод", 70, 30),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        self.title = QLabel("Переводим книгу")
        self.title.setObjectName("H1")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        self.ring = ProgressRing()
        layout.addWidget(self.ring, alignment=Qt.AlignCenter)

        self.stage = QLabel("Готовимся…")
        self.stage.setObjectName("Subtitle")
        self.stage.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stage)

        self.counter = QLabel("")
        self.counter.setObjectName("Stat")
        self.counter.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.counter)

        self.eta = QLabel("")
        self.eta.setObjectName("Stat")
        self.eta.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.eta)

        layout.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel = QPushButton("Отменить")
        self.cancel.clicked.connect(self.cancelRequested)
        row.addWidget(self.cancel)
        row.addStretch()
        layout.addLayout(row)

        self._base = 0
        self._weight = 100

    def start(self, title: str) -> None:
        short = title if len(title) <= 46 else title[:43].rstrip() + "…"
        self.title.setText(f"Переводим «{short}»")
        self.title.setWordWrap(True)
        self.ring.set_value(0)
        self.stage.setText("Готовимся…")
        self.counter.setText("")
        self.eta.setText("")
        self._base, self._weight = 0, 100

    def set_phase(self, key: str) -> None:
        """Этапы идут последовательно: перевод, потом редактура.

        Кольцо показывает общий прогресс, поэтому редактура не выглядит как
        «перевод заново» с нуля.
        """
        title, base, weight = self.PHASES.get(key, ("Работаем…", 0, 100))
        self.stage.setText(title)
        self.counter.setText("")
        self._base, self._weight = base, weight

    def update_progress(self, done: int, total: int, cached: int, seconds: float) -> None:
        share = (done / total) if total else 0
        self.ring.set_value(int(self._base + self._weight * share))
        self.counter.setText(f"фрагмент {done} из {total}")
        if done > 0:
            remain = seconds / done * (total - done)
            self.eta.setText(f"в этом этапе ≈ {max(1, round(remain / 60))} мин  ·  из кэша: {cached}")

    def set_stage(self, text: str) -> None:
        self.stage.setText(text)


class DonePage(QWidget):
    openRequested = Signal()
    folderRequested = Signal()
    againRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("✅")
        icon.setStyleSheet("font-size: 64px;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("Книга готова")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.filename = QLabel("")
        self.filename.setObjectName("Subtitle")
        self.filename.setAlignment(Qt.AlignCenter)
        self.filename.setWordWrap(True)
        layout.addWidget(self.filename)

        self.details = QLabel("")
        self.details.setObjectName("Stat")
        self.details.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.details)

        self.folder = QLabel("")
        self.folder.setObjectName("Stat")
        self.folder.setAlignment(Qt.AlignCenter)
        self.folder.setWordWrap(True)
        layout.addWidget(self.folder)

        self.note = QLabel("")
        self.note.setObjectName("Stat")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        layout.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch()
        open_button = QPushButton("Открыть книгу")
        open_button.setObjectName("Primary")
        open_button.clicked.connect(self.openRequested)
        row.addWidget(open_button)

        folder = QPushButton("Показать в папке")
        folder.clicked.connect(self.folderRequested)
        row.addWidget(folder)
        row.addStretch()
        layout.addLayout(row)

        again = QPushButton("Ещё одну книгу")
        again.setObjectName("Link")
        again.clicked.connect(self.againRequested)
        layout.addWidget(again, alignment=Qt.AlignCenter)

    def set_outcome(self, outcome: RunOutcome) -> None:
        self.filename.setText(os.path.basename(outcome.path))
        minutes = max(1, round(outcome.seconds / 60))
        self.details.setText(
            f"{outcome.chunks} фрагментов  ·  {minutes} мин  ·  "
            f"правок редактуры: {outcome.applied}  ·  ≈ ${outcome.cost:.2f}"
        )
        self.folder.setText(f"Папка: {os.path.dirname(outcome.path)}")
        notes = []
        if outcome.demo:
            notes.append("Демо-режим: текст помечен, а не переведён. Добавь ключ в настройках.")
        notes.extend(outcome.warnings[:2])
        self.note.setText("\n".join(notes))


# -------------------------------------------------------------------- диалоги


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Сервис перевода"))
        self.provider = QComboBox()
        self.provider.addItems(list(PROVIDERS))
        self.provider.setCurrentText(settings.provider)
        self.provider.currentTextChanged.connect(self._provider_changed)
        layout.addWidget(self.provider)

        layout.addWidget(QLabel("Адрес сервиса"))
        self.base_url = QLineEdit(settings.base_url)
        layout.addWidget(self.base_url)

        layout.addWidget(QLabel("Ключ доступа"))
        key_row = QHBoxLayout()
        self.api_key = QLineEdit(settings.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("вставь ключ из личного кабинета сервиса")
        key_row.addWidget(self.api_key, stretch=1)
        self.show_key = QPushButton("Показать")
        self.show_key.setObjectName("Link")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self._toggle_key)
        key_row.addWidget(self.show_key)
        layout.addLayout(key_row)

        layout.addWidget(QLabel("Модель"))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(MODELS.get(settings.provider, ["deepseek-flash"]))
        self.model.setCurrentText(settings.model)
        layout.addWidget(self.model)

        self.model_hint = QLabel(
            "Актуальные имена: deepseek-flash (V4.1 Flash) и deepseek-v4-pro. "
            "Имя можно вписать вручную."
        )
        self.model_hint.setObjectName("Stat")
        self.model_hint.setWordWrap(True)
        layout.addWidget(self.model_hint)

        layout.addWidget(QLabel("Тема оформления"))
        self.theme = QComboBox()
        self.theme.addItem("Как в системе", "system")
        self.theme.addItem("Светлая", "light")
        self.theme.addItem("Тёмная", "dark")
        index = self.theme.findData(settings.theme_mode)
        self.theme.setCurrentIndex(max(0, index))
        layout.addWidget(self.theme)

        layout.addWidget(QLabel("Куда складывать готовые книги"))
        folder_row = QHBoxLayout()
        self.output_dir = QLineEdit(settings.output_dir)
        self.output_dir.setPlaceholderText("рядом с исходным файлом")
        folder_row.addWidget(self.output_dir)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        hint_text = (
            "Ключ шифруется средствами Windows и хранится только на этом компьютере.\n"
            f"Папка настроек: {config_dir()}"
        )
        if diagnostics.integrity_level() == "low":
            hint_text += (
                "\n\nПриложение запущено с ограниченными правами: Windows не даёт ему "
                "писать в AppData и Downloads. Запусти ярлык обычным двойным щелчком — "
                "тогда настройки лягут на своё место."
            )
        hint = QLabel(hint_text)
        hint.setObjectName("Stat")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _provider_changed(self, name: str) -> None:
        url = PROVIDERS.get(name, "")
        if url:
            self.base_url.setText(url)
        models = MODELS.get(name) or ["deepseek-flash"]
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(models[0])
    def _toggle_key(self, shown: bool) -> None:
        self.api_key.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self.show_key.setText("Скрыть" if shown else "Показать")

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Куда складывать книги")
        if path:
            self.output_dir.setText(path)

    def apply(self) -> Settings:
        s = self.settings
        s.provider = self.provider.currentText()
        s.base_url = self.base_url.text().strip()
        s.model = self.model.currentText().strip()
        s.theme_mode = self.theme.currentData() or "system"
        s.output_dir = self.output_dir.text().strip()
        s.set_api_key(self.api_key.text())
        try:
            s.save()
        except OSError as exc:
            applog.log(f"не удалось сохранить настройки: {exc}")
            QMessageBox.warning(
                self,
                "Настройки не сохранились на диск",
                "Ключ и параметры будут действовать до закрытия программы.\n\n"
                f"Причина: {exc}",
            )
        return s


# --------------------------------------------------------------------- окно


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings.load()
        self.setWindowTitle("Booktify")
        self.setWindowIcon(QIcon(resource_path("assets", "icon.png")))
        self.resize(1000, 720)
        self.setMinimumSize(880, 620)
        self.apply_theme()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomePage()
        self.book_page = BookPage()
        self.progress_page = ProgressPage()
        self.done_page = DonePage()
        for page in (self.home, self.book_page, self.progress_page, self.done_page):
            self.stack.addWidget(page)

        self.home.fileChosen.connect(self.open_book)
        self.home.settingsRequested.connect(self.open_settings)
        self.book_page.backRequested.connect(self.show_home)
        self.book_page.startRequested.connect(self.start_translation)
        self.book_page.qualityChanged.connect(self._quality_changed)
        self.progress_page.cancelRequested.connect(self.cancel_translation)
        self.done_page.openRequested.connect(self._open_result)
        self.done_page.folderRequested.connect(self._show_result_folder)
        self.done_page.againRequested.connect(self.show_home)

        self.import_worker: ImportWorker | None = None
        self.run_worker: RunWorker | None = None
        self.current_book: Book | None = None
        self.current_path = ""
        self.outcome: RunOutcome | None = None
        self._started_at = 0.0

        # Если разбор книги почему-то не вернул ни успех, ни ошибку, лучше
        # сказать об этом вслух, чем молча висеть на «Читаем книгу…».
        self.import_watchdog = QTimer(self)
        self.import_watchdog.setSingleShot(True)
        self.import_watchdog.timeout.connect(self._import_slow)

        self.home.set_recents(self.settings.recent)
        self.home.set_key_present(self.settings.has_key)
        self.show_home()

    # ---------------------------------------------------------------- экраны

    def apply_theme(self) -> None:
        mode = self.settings.theme_mode
        dark = theme.system_is_dark() if mode == "system" else mode == "dark"
        theme.set_mode(dark)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.qss())
        home = getattr(self, "home", None)
        if home is not None:
            home.drop.refresh_theme()

    def show_home(self) -> None:
        self.stack.setCurrentWidget(self.home)
        self.home.set_recents(self.settings.recent)

    def show_book(self) -> None:
        self.stack.setCurrentWidget(self.book_page)

    def show_progress(self) -> None:
        self.stack.setCurrentWidget(self.progress_page)

    def show_done(self) -> None:
        self.stack.setCurrentWidget(self.done_page)

    # ------------------------------------------------------------------ книга

    def open_book(self, path: str) -> None:
        if self.import_worker and self.import_worker.isRunning():
            return
        applog.log(f"открываем книгу: {path}")
        self.current_path = path
        self.progress_page.start(os.path.basename(path))
        self.progress_page.stage.setText("Читаем книгу…")
        self.show_progress()

        self.import_worker = ImportWorker(path)
        self.import_worker.done.connect(self._book_loaded)
        self.import_worker.failed.connect(self._import_failed)
        self.import_worker.start()
        self.import_watchdog.start(90_000)

    def _book_loaded(self, book: Book) -> None:
        self.import_watchdog.stop()
        applog.log(
            f"книга разобрана: разделов {len(book.sections)}, блоков {book.blocks}, "
            f"слов {book.words}"
        )
        try:
            self.current_book = book
            self.book_page.set_book(book, self.current_path, self.settings)
            self._remember(self.current_path)
            self.show_book()
        except Exception as exc:
            applog.log_exception("не удалось показать разобранную книгу")
            self.show_home()
            QMessageBox.warning(
                self,
                "Книга разобралась, но приложение споткнулось",
                f"{exc}\n\nПодробности записаны в журнал:\n{applog.log_path()}",
            )

    def _import_failed(self, message: str) -> None:
        self.import_watchdog.stop()
        applog.log(f"не удалось открыть книгу: {message}")
        self.show_home()
        QMessageBox.warning(self, "Не получилось открыть книгу", message)

    def _import_slow(self) -> None:
        if not (self.import_worker and self.import_worker.isRunning()):
            return
        applog.log("импорт идёт дольше 90 секунд — возможно, файл повреждён")
        QMessageBox.information(
            self,
            "Книга читается дольше обычного",
            "Файл большой или повреждён. Можно подождать ещё или нажать «Отменить» "
            f"и выбрать другой файл.\n\nПодробности пишутся в журнал:\n{applog.log_path()}",
        )

    def _remember(self, path: str) -> None:
        # Журнал недавних книг — не повод не открыть книгу.
        try:
            recent = [p for p in self.settings.recent if p != path]
            recent.insert(0, path)
            self.settings.recent = recent[:8]
            self.settings.last_folder = os.path.dirname(path)
            self.settings.save()
        except Exception:
            applog.log_exception("не удалось сохранить список недавних книг")

    # ------------------------------------------------------------------ запуск

    def start_translation(self, confirm_demo: bool = True) -> None:
        if not self.current_book:
            return
        out_path = self._output_path()
        demo = not self.settings.has_key

        if demo and confirm_demo:
            answer = QMessageBox.question(
                self,
                "Ключ не задан",
                "Ключа доступа нет, поэтому включён демо-режим: текст будет помечен, "
                "а не переведён.\n\nПродолжить демонстрацию?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.open_settings()
                return

        self.progress_page.start(self.current_book.meta.title)
        self.show_progress()
        applog.log(
            f"старт перевода: режим {self.settings.quality}, модель "
            f"{'демо' if demo else self.settings.effective_model()}, файл {out_path}"
        )

        self.run_worker = RunWorker(
            book=self.current_book,
            settings=self.settings,
            glossary=None,
            out_path=out_path,
            demo=demo,
            cache_dir=default_cache_dir(),
        )
        self._started_at = 0.0
        self.run_worker.stage.connect(self.progress_page.set_stage)
        self.run_worker.phase.connect(self.progress_page.set_phase)
        self.run_worker.progress.connect(self._on_progress)
        self.run_worker.done.connect(self._on_done)
        self.run_worker.failed.connect(self._on_failed)
        self.run_worker.start()

    def _on_progress(self, done: int, total: int, cached: int) -> None:
        import time

        if not self._started_at:
            self._started_at = time.time()
        self.progress_page.update_progress(done, total, cached, time.time() - self._started_at)

    def _on_done(self, outcome: RunOutcome) -> None:
        applog.log(
            f"готово: {outcome.path}, фрагментов {outcome.chunks}, "
            f"из кэша {outcome.cached}, правок {outcome.applied}, "
            f"ошибок {outcome.failed}, {outcome.seconds:.0f} с, "
            f"стоимость ≈ ${outcome.cost:.2f}"
        )
        self.outcome = outcome
        self.done_page.set_outcome(outcome)
        self.show_done()

    def _on_failed(self, message: str) -> None:
        applog.log(f"перевод не закончен: {message}")
        self.show_book()
        QMessageBox.warning(self, "Перевод не закончен", message)

    def cancel_translation(self) -> None:
        if self.run_worker:
            self.run_worker.cancel()
        self.show_book()

    def _output_path(self) -> str:
        source = self.current_path
        folder = self.settings.output_dir or os.path.dirname(source)
        stem = os.path.splitext(os.path.basename(source))[0]
        if stem.lower().endswith(".fb2"):
            stem = stem[:-4]
        candidate = os.path.join(folder, f"{stem} (RU).epub")
        counter = 2
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{stem} (RU) {counter}.epub")
            counter += 1
        return candidate

    # ------------------------------------------------------------------ прочее

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.settings = dialog.apply()
            except Exception:
                applog.log_exception("не удалось применить настройки")
                return
            self.home.set_key_present(self.settings.has_key)
            self.apply_theme()
            if self.current_book:
                self.book_page.set_book(self.current_book, self.current_path, self.settings)

    def _quality_changed(self, quality: str) -> None:
        self.settings.quality = quality
        try:
            self.settings.save()
        except OSError:
            applog.log_exception("не удалось сохранить выбранное качество")

    def _low_access(self) -> bool:
        return diagnostics.integrity_level() == "low"

    def _show_path_help(self, title: str, path: str, hint: str) -> None:
        QGuiApplication.clipboard().setText(path)
        QMessageBox.information(
            self,
            title,
            f"{hint}\n\n{path}\n\nПуть скопирован в буфер обмена — вставь его в адресную строку проводника.",
        )

    def _open_result(self) -> None:
        if not self.outcome:
            return
        if self._low_access():
            # Из ограниченного процесса Windows не даст запустить читалку.
            self._show_path_help(
                "Книга сохранена",
                self.outcome.path,
                "Приложение запущено с ограниченными правами, поэтому открыть файл само не может.",
            )
            return
        try:
            os.startfile(self.outcome.path)  # noqa: S606
        except OSError as exc:
            applog.log(f"не удалось открыть книгу: {exc}")
            self._show_path_help("Книга сохранена", self.outcome.path, "Открыть файл не получилось.")

    def _show_result_folder(self) -> None:
        if not self.outcome:
            return
        path = self.outcome.path
        folder = os.path.dirname(path)

        if self._low_access():
            # explorer.exe из такого процесса падает с 0xc0000142.
            self._show_path_help(
                "Файл лежит здесь",
                folder,
                "Приложение запущено с ограниченными правами, поэтому проводник само не откроет.",
            )
            return

        try:
            import subprocess

            subprocess.Popen(["explorer", f"/select,{path}"])
        except Exception:
            applog.log_exception("не удалось открыть проводник")
            try:
                os.startfile(folder)  # noqa: S606
            except OSError as exc:
                applog.log(f"проводник недоступен: {exc}")
                self._show_path_help("Проводник не открылся", folder, "Файл лежит здесь.")


def main() -> int:
    if sys.platform == "win32":
        try:
            # Отдельный AppUserModelID: иначе Windows показывает в панели задач
            # иконку python.exe вместо нашей.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Booktify.App.1")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Booktify")
    apply_icon(app)
    _install_excepthook()
    import platform

    parent_pid, parent_name = diagnostics.parent_process()
    applog.log(
        "=== запуск: Python %s, %s, сборка=%s, IL=%s (whoami=%s), родитель=%s(%s, %s) ==="
        % (
            platform.python_version(),
            platform.platform(),
            bool(getattr(sys, "frozen", False)),
            diagnostics.integrity_level(),
            diagnostics.whoami_integrity(),
            parent_name or "?",
            parent_pid,
            diagnostics.process_integrity(parent_pid),
        )
    )

    window = MainWindow()
    window.show()

    # Системная тема может смениться, пока приложение открыто.
    try:
        app.styleHints().colorSchemeChanged.connect(lambda *_: window.apply_theme())
    except Exception:
        pass

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
