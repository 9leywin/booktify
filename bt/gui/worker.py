"""Фоновые задачи: импорт книги и перевод.

Интерфейс не должен подвисать ни на разборе большого EPUB, ни на запросах
к модели. Поэтому обе операции живут в отдельных потоках и общаются сигналами.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from ..config import Settings
from ..epubbuild import build_epub
from ..extract import extract
from ..glossary import Glossary
from ..importers import import_book
from ..llm import LLMClient, LLMConfig, MockClient, MockReviewer
from ..model import Book
from ..quality import Issue
from ..review import ReviewOptions, Reviewer
from ..surgery import build_epub_surgery
from ..translate import TranslationOptions, Translator
from ..paths import safe_output_path


@dataclass
class RunOutcome:
    path: str
    seconds: float
    chunks: int
    cached: int
    failed: int
    applied: int = 0
    issues: list[Issue] = field(default_factory=list)
    cost: float = 0.0
    demo: bool = False
    warnings: list[str] = field(default_factory=list)


class ImportWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            from .. import applog

            applog.log(f"импорт начат: {self.path}")
            book = import_book(self.path)
            applog.log(f"импорт завершён: разделов {len(book.sections)}")
        except BaseException as exc:  # noqa: BLE001 - поток не должен умирать молча
            from .. import applog

            applog.log_exception("импорт упал")
            self.failed.emit(_human_error(exc))
            return
        self.done.emit(book)


class ModelsWorker(QThread):
    """Проверяет ключ и забирает список моделей у провайдера."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self) -> None:
        from ..models_api import fetch_models

        try:
            models = fetch_models(self.base_url, self.api_key, timeout=8.0)
        except PermissionError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.done.emit(models)


class GlossaryWorker(QThread):
    """Просит модель предложить, как писать имена и термины по-русски."""

    done = Signal(dict, object)
    failed = Signal(str)

    def __init__(self, book: Book, settings: Settings, parent=None):
        super().__init__(parent)
        self.book = book
        self.settings = settings

    def run(self) -> None:
        try:
            client = None
            if self.settings.has_key:
                client = LLMClient(
                    LLMConfig(
                        base_url=self.settings.base_url,
                        api_key=self.settings.api_key,
                        model=self.settings.effective_model(),
                    )
                )
            result = extract(self.book, client=client, limit=120)
            self.done.emit(result.profile, result.glossary)
        except Exception as exc:
            from .. import applog

            applog.log_exception("глоссарий упал")
            self.failed.emit(_human_error(exc))


class RunWorker(QThread):
    progress = Signal(int, int, int)
    stage = Signal(str)
    phase = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        book: Book,
        settings: Settings,
        glossary: Glossary | None,
        out_path: str,
        demo: bool,
        cache_dir: str,
        profile: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.book = book
        self.settings = settings
        self.glossary = glossary or Glossary()
        self.out_path = out_path
        self.demo = demo
        self.cache_dir = cache_dir
        self.profile = profile or {}
        self.blocks_cache: dict[str, str] = {}
        self._translator: Translator | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._translator is not None:
            self._translator.abort()

    def run(self) -> None:
        started = time.time()
        demo = self.demo or not self.settings.has_key
        client = MockClient() if demo else LLMClient(
            LLMConfig(
                base_url=self.settings.base_url,
                api_key=self.settings.api_key,
                model=self.settings.effective_model(),
            )
        )
        model = "mock" if demo else self.settings.effective_model()

        try:
            # Глоссарий собирает сама модель: пользователю не нужно ничего заполнять.
            profile = dict(self.profile)
            if not demo and not len(self.glossary):
                self.phase.emit("glossary")
                try:
                    extraction = extract(self.book, client=client, limit=120)
                    self.glossary = extraction.glossary
                    profile = {**extraction.profile, **profile}
                    applog_line = f"глоссарий собран автоматически: {len(self.glossary)} записей"
                    from .. import applog

                    applog.log(applog_line)
                except Exception:
                    from .. import applog

                    applog.log_exception("не удалось собрать глоссарий, переводим без него")

            self.phase.emit("translate")
            options = TranslationOptions(
                jobs=self.settings.jobs,
                cache_dir=self.cache_dir,
                profile={
                    **profile,
                    "title": self.book.meta.title,
                    "author": ", ".join(self.book.meta.authors),
                },
            )
            translator = Translator(client, glossary=self.glossary, options=options,
                                    progress=self.progress.emit)
            self._translator = translator
            result = translator.run(self.book)

            applied = 0
            if self.settings.needs_review:
                self.phase.emit("review")
                reviewer = Reviewer(
                    MockReviewer() if demo else client,
                    glossary=self.glossary,
                    options=ReviewOptions(
                        jobs=self.settings.jobs,
                        cache_dir=self.cache_dir,
                        profile=options.profile,
                    ),
                    progress=self.progress.emit,
                )
                review = reviewer.run(self.book, result.blocks)
                result.blocks = review.blocks
                applied = review.applied
                result.usage.add(review.usage)

            if self._cancelled:
                self.failed.emit("Перевод остановлен")
                return

            self.stage.emit("Собираем EPUB…")
            self.blocks_cache = result.blocks
            target, moved = safe_output_path(self.out_path, self._fallback_dir())
            try:
                warnings = self._build(target)
            except OSError:
                from .. import applog

                applog.log_exception("не удалось записать книгу рядом с исходником")
                target = os.path.join(self._fallback_dir(), os.path.basename(self.out_path))
                moved = True
                warnings = self._build(target)

            if moved:
                warnings.insert(
                    0,
                    "Windows не разрешил запись рядом с книгой — файл сохранён в "
                    + os.path.dirname(target),
                )
            if result.chunks_failed:
                warnings.insert(
                    0,
                    f"Не переведено фрагментов: {result.chunks_failed}. "
                    "Открой книгу заново и нажми «Перевести» — докачает только их, "
                    "остальное возьмёт из кэша.",
                )

            self.done.emit(
                RunOutcome(
                    path=target,
                    seconds=time.time() - started,
                    chunks=result.chunks_total,
                    cached=result.chunks_cached,
                    failed=result.chunks_failed,
                    applied=applied,
                    issues=result.issues,
                    cost=result.usage.cost(model),
                    demo=demo,
                    warnings=warnings,
                )
            )
        except Exception as exc:
            from .. import applog

            applog.log_exception("перевод упал")
            self.failed.emit(_human_error(exc))

    def _build(self, target: str) -> list[str]:
        if self.book.source_format == "epub":
            return build_epub_surgery(self.book, self.book.source_path, target, self.blocks_cache)
        return build_epub(self.book, target, translations=self.blocks_cache)

    def _fallback_dir(self) -> str:
        from ..config import config_dir

        return os.path.join(config_dir(), "books")


def _human_error(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if isinstance(exc, PermissionError) or "permission denied" in low or "errno 13" in low:
        return (
            "Windows не разрешил записать файл в эту папку. "
            "Выбери другую папку для готовых книг в настройках."
        )
    if "скан" in low or "текстового слоя" in low:
        return text
    if "401" in text or "invalid" in low and "key" in low:
        return "Сервис не принял ключ доступа. Проверь ключ в настройках."
    if "timed out" in low or "таймаут" in low or "сеть" in low:
        return "Не получилось связаться с сервисом. Проверь интернет и повтори."
    if "не найдено" in low or "no such file" in low:
        return "Файл не найден. Возможно, его переместили."
    return f"Не получилось: {text}"


def default_cache_dir() -> str:
    from ..config import config_dir

    path = os.path.join(config_dir(), "cache")
    os.makedirs(path, exist_ok=True)
    return path
