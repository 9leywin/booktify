"""Выбор импортёра по расширению и формату файла."""

from __future__ import annotations

import os
import zipfile

from ..model import Book
from .epub import import_epub
from .fb2 import import_fb2
from .pdf import import_pdf

SUPPORTED = (".epub", ".fb2", ".pdf", ".fb2.zip", ".zip")


def import_book(path: str) -> Book:
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    lower = path.lower()
    if lower.endswith(".epub"):
        return import_epub(path)
    if lower.endswith(".fb2"):
        return import_fb2(path)
    if lower.endswith(".pdf"):
        return import_pdf(path)
    if lower.endswith(".zip"):
        return _import_zip(path)

    raise ValueError(
        "неизвестный формат: поддержаны EPUB, FB2, FB2.ZIP и PDF"
    )


def _import_zip(path: str) -> Book:
    """FB2 часто лежит в zip. EPUB тоже zip — отличаем по mimetype."""
    import tempfile

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "mimetype" in names:
            return import_epub(path)
        fb2 = next((n for n in names if n.lower().endswith(".fb2")), None)
        if not fb2:
            raise ValueError("в архиве нет ни EPUB, ни FB2")
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, os.path.basename(fb2))
            with open(target, "wb") as fh:
                fh.write(zf.read(fb2))
            book = import_fb2(target)
            book.source_path = path
            return book
