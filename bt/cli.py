"""Командная строка: посмотреть структуру книги и нарезать её на фрагменты."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .chunker import chunk_stats, make_chunks
from .epubbuild import build_epub
from .extract import extract
from .glossary import Glossary
from .importers import import_book
from .llm import LLMClient, LLMConfig, MockClient, MockReviewer
from .review import ReviewOptions, Reviewer
from .surgery import build_epub_surgery
from .translate import TranslationOptions, Translator


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="bt",
        description="Переводчик книг: разбор книги и подготовка к переводу.",
    )
    parser.add_argument("--version", action="version", version=f"bt {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="показать структуру книги")
    p_inspect.add_argument("path")
    p_inspect.add_argument("--json", action="store_true", help="вывести модель целиком в JSON")
    p_inspect.add_argument("--chunks", action="store_true", help="показать нарезку на фрагменты")

    p_chunk = sub.add_parser("chunk", help="нарезать книгу на фрагменты для перевода")
    p_chunk.add_argument("path")
    p_chunk.add_argument("--max-words", type=int, default=1300)
    p_chunk.add_argument("--min-words", type=int, default=350)
    p_chunk.add_argument("--out", help="куда записать JSON (по умолчанию рядом с книгой)")

    p_build = sub.add_parser("build", help="собрать EPUB из модели (FB2/PDF)")
    p_build.add_argument("path")
    p_build.add_argument("--out", required=True)
    p_build.add_argument("--translations", help="JSON вида {block_id: html}")

    p_tr = sub.add_parser("translate", help="перевести книгу через API модели")
    p_tr.add_argument("path")
    p_tr.add_argument("--out", help="куда собрать EPUB")
    p_tr.add_argument("--mock", action="store_true", help="без сети: пометить текст вместо перевода")
    p_tr.add_argument("--api-key", default=os.environ.get("BT_API_KEY", ""))
    p_tr.add_argument("--model", default="deepseek-flash")
    p_tr.add_argument("--base-url", default=os.environ.get("BT_BASE_URL", "https://api.deepseek.com"))
    p_tr.add_argument("--glossary", help="JSON или markdown с глоссарием")
    p_tr.add_argument("--cache", help="каталог кэша (по умолчанию .bt-cache)")
    p_tr.add_argument("--jobs", type=int, default=3)
    p_tr.add_argument("--limit", type=int, help="перевести только первые N фрагментов")
    p_tr.add_argument("--translations", help="куда сохранить карту переводов (JSON)")
    p_tr.add_argument("--review", action="store_true",
                      help="второй проход: редактура перевода против оригинала")

    p_gl = sub.add_parser("glossary", help="собрать глоссарий книги")
    p_gl.add_argument("path")
    p_gl.add_argument("--out", required=True)
    p_gl.add_argument("--existing", help="уже готовый глоссарий (JSON или markdown)")
    p_gl.add_argument("--mock", action="store_true", help="только кандидаты, без модели")
    p_gl.add_argument("--api-key", default=os.environ.get("BT_API_KEY", ""))
    p_gl.add_argument("--model", default="deepseek-flash")
    p_gl.add_argument("--base-url", default=os.environ.get("BT_BASE_URL", "https://api.deepseek.com"))
    p_gl.add_argument("--limit", type=int, default=150)

    args = parser.parse_args(argv)

    try:
        book = import_book(args.path)
    except Exception as exc:
        print(f"Не получилось открыть книгу: {exc}", file=sys.stderr)
        return 2

    if args.command == "inspect":
        if args.json:
            json.dump(book.to_dict(), sys.stdout, ensure_ascii=False, indent=1)
            print()
            return 0
        _print_inspect(book)
        if args.chunks:
            chunks = make_chunks(book)
            _print_chunks(chunks)
        return 0

    if args.command == "chunk":
        chunks = make_chunks(book, max_words=args.max_words, min_words=args.min_words)
        stats = chunk_stats(chunks)
        out = args.out or os.path.join(
            os.path.dirname(os.path.abspath(args.path)),
            os.path.splitext(os.path.basename(args.path))[0] + ".chunks.json",
        )
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "source": os.path.abspath(args.path),
                    "meta": book.meta.to_dict(),
                    "stats": stats,
                    "chunks": [c.to_dict() for c in chunks],
                },
                fh,
                ensure_ascii=False,
                indent=1,
            )
        print(f"Фрагментов: {stats['count']}  ·  слов: {stats['words']}  ·  "
              f"средний: {stats['avg']}  ·  мин/макс: {stats['min']}/{stats['max']}")
        print(f"Записано: {out}")
        return 0

    if args.command == "build":
        if book.source_format == "epub":
            print(
                "EPUB пока собирается только «правкой на месте» — этот режим появится "
                "на следующем этапе. Пересборка из EPUB потеряла бы вёрстку.",
                file=sys.stderr,
            )
            return 3
        translations = {}
        if args.translations:
            with open(args.translations, encoding="utf-8") as fh:
                translations = json.load(fh)
        warnings = build_epub(book, args.out, translations=translations)
        if warnings:
            print("Замечания:")
            for warning in warnings:
                print(f"  ! {warning}")
        print(f"Собрано: {args.out}")
        return 0

    if args.command == "translate":
        return _run_translate(args, book)

    if args.command == "glossary":
        return _run_glossary(args, book)

    return 1


def _run_glossary(args, book) -> int:
    existing = Glossary.load(args.existing) if args.existing else None
    client = None
    if not args.mock:
        if not args.api_key:
            print(
                "Для глоссария с моделью нужен ключ (--api-key или BT_API_KEY).\n"
                "Без ключа: bt glossary book.fb2 --mock --out glossary.json",
                file=sys.stderr,
            )
            return 2
        client = LLMClient(LLMConfig(base_url=args.base_url, api_key=args.api_key, model=args.model))

    result = extract(book, client=client, existing=existing, limit=args.limit)
    payload = {
        "profile": result.profile,
        "terms": [t.to_dict() for t in result.glossary.terms],
        "candidates": [c.to_dict() for c in result.candidates],
        "uncertain": result.uncertain,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    print(f"Кандидатов: {len(result.candidates)}  ·  записей в глоссарии: {len(result.glossary)}")
    for term in result.glossary.terms[:10]:
        print(f"  {term.en} → {term.ru}")
    if len(result.glossary.terms) > 10:
        print(f"  … и ещё {len(result.glossary.terms) - 10}")
    print(f"Записано: {args.out}")
    return 0


def _run_translate(args, book) -> int:
    if args.mock:
        client = MockClient()
        model = "mock"
    else:
        if not args.api_key:
            print(
                "Нужен ключ доступа к модели. Передайте --api-key или переменную BT_API_KEY.\n"
                "Без ключа можно проверить конвейер: bt translate book.fb2 --mock --out out.epub",
                file=sys.stderr,
            )
            return 2
        client = LLMClient(
            LLMConfig(base_url=args.base_url, api_key=args.api_key, model=args.model)
        )
        model = args.model

    glossary = Glossary.load(args.glossary) if args.glossary else Glossary()
    if len(glossary):
        print(f"Глоссарий: {len(glossary)} записей")

    options = TranslationOptions(
        jobs=args.jobs,
        cache_dir=args.cache,
        profile={
            "title": book.meta.title,
            "author": ", ".join(book.meta.authors),
        },
    )

    state = {"step": -1}

    def progress(done: int, total: int, cached: int) -> None:
        percent = int(done * 100 / total) if total else 100
        step = percent // 10
        if step != state["step"] or done == total:
            state["step"] = step
            print(f"  {done}/{total} — {percent}%  (из кэша: {cached})")

    translator = Translator(client, glossary=glossary, options=options, progress=progress)
    print(f"Переводим: {book.meta.title or args.path}")
    result = translator.run(book, limit=args.limit)
    stats = result.summary()

    print(
        f"\nФрагментов: {stats['chunks']}  ·  из кэша: {stats['cached']}  ·  "
        f"с ошибками: {stats['failed']}"
    )
    print(
        f"Токенов: {stats['prompt_tokens']} вход / {stats['completion_tokens']} выход  ·  "
        f"≈ ${result.cost(model):.2f}"
    )
    counts = stats["issues"]
    print(f"Замечаний: критичных {counts['critical']}, существенных {counts['major']}, "
          f"мелких {counts['minor']}")

    for issue in result.issues:
        if issue.severity == "critical":
            print(f"  ! {issue}")
    shown = [i for i in result.issues if i.severity != "critical"][:5]
    for issue in shown:
        print(f"  · {issue}")

    if args.review:
        print("\nРедактура...")
        review_client = MockReviewer() if args.mock else client
        review_state = {"step": -1}

        def review_progress(done: int, total: int, cached: int) -> None:
            percent = int(done * 100 / total) if total else 100
            step = percent // 10
            if step != review_state["step"] or done == total:
                review_state["step"] = step
                print(f"  {done}/{total} — {percent}%  (из кэша: {cached})")

        reviewer = Reviewer(
            review_client,
            glossary=glossary,
            options=ReviewOptions(jobs=args.jobs, cache_dir=args.cache, profile=options.profile),
            progress=review_progress,
        )
        review = reviewer.run(book, result.blocks)
        result.blocks = review.blocks
        review_stats = review.summary()
        print(
            f"Правок применено: {review_stats['applied']}  ·  "
            f"отклонено: {review_stats['dropped']}  ·  "
            f"≈ ${review.usage.cost(model):.2f}"
        )
        for reason in review.dropped_reasons[:5]:
            print(f"  · {reason}")

    out_json = args.translations or (args.out + ".translations.json" if args.out else None)
    if out_json:
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(result.blocks, fh, ensure_ascii=False, indent=1)
        print(f"Переводы: {out_json}")

    if args.out:
        if book.source_format == "epub":
            warnings = build_epub_surgery(book, args.path, args.out, result.blocks)
        else:
            warnings = build_epub(book, args.out, translations=result.blocks)
        for warning in warnings:
            print(f"  ! {warning}")
        print(f"Готово: {args.out}")

    return 0


def _print_inspect(book) -> None:
    m = book.meta
    print(f"Книга:    {m.title or '(без названия)'}")
    print(f"Автор:    {', '.join(m.authors) or '(не указан)'}")
    print(f"Формат:   {book.source_format}   Язык: {m.language or '?'}")
    print(
        f"Разделов: {len(book.sections)}   Блоков: {book.blocks}   "
        f"Слов: {book.words}"
    )
    images = sum(1 for k in book.assets if k.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")))
    print(f"Обложка:  {'есть' if m.cover_href else 'нет'}   Картинок: {images}")
    print()
    print(f"{'#':>3}  {'ID':<5} {'Тип':<12} {'Слов':>7} {'Блоков':>7}  Название")
    print("-" * 78)
    for i, section in enumerate(book.sections, start=1):
        title = section.title if len(section.title) <= 44 else section.title[:41] + "…"
        print(
            f"{i:>3}  {section.id:<5} {section.kind:<12} "
            f"{section.words:>7} {len(section.blocks):>7}  {title}"
        )
    if book.warnings:
        print()
        for warning in book.warnings:
            print(f"! {warning}")


def _print_chunks(chunks) -> None:
    stats = chunk_stats(chunks)
    print()
    print(
        f"Нарезка: {stats['count']} фрагментов, средний {stats['avg']} слов, "
        f"от {stats['min']} до {stats['max']}"
    )
    for chunk in chunks[:5]:
        print(f"  {chunk.id:<10} {chunk.words:>5} слов  ·  {chunk.section_title[:48]}")
    if len(chunks) > 5:
        print(f"  … и ещё {len(chunks) - 5}")


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
