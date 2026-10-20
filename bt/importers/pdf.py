"""Импорт PDF с текстовым слоем.

PDF — единственный формат, где структуру приходится угадывать. Поэтому здесь
три честные эвристики (скан, колонтитулы, склейка абзацев) и явные предупреждения
вместо тихой потери текста.

Сканы не поддерживаются: приложение должно сказать «это картинки, я так не умею»,
а не выдать пустую книгу.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..model import Block, Book, Meta, Section

MIN_CHARS_PER_PAGE = 100
MAX_CHARS_PER_PAGE = 100_000

HEADING_RE = re.compile(
    r"^\s*(chapter|part|book|prologue|epilogue|appendix|глава|часть|книга|"
    r"пролог|эпилог|приложение)\b[\s.:\-–—]*[\wIVXLCDM\d]*",
    re.I,
)
NUMBERED_RE = re.compile(r"^\s*(\d{1,3})[.)]?\s+\S")
ALLCAPS_RE = re.compile(r"^[A-ZА-ЯЁ0-9 ,.'’\-–—:;!?()]{4,80}$")


def import_pdf(path: str) -> Book:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "для PDF нужен пакет pypdf: python -m pip install pypdf"
        ) from exc

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("PDF защищён паролем — такие файлы не поддерживаются") from exc

    pages_lines: list[list[str]] = []
    for page in reader.pages:
        text = _page_text(page)
        pages_lines.append([ln.rstrip() for ln in text.splitlines()])

    total_chars = sum(len("".join(lines)) for lines in pages_lines)
    page_count = max(1, len(pages_lines))
    if total_chars / page_count < MIN_CHARS_PER_PAGE:
        raise ValueError(
            "в PDF нет текстового слоя — это скан. Нужен другой файл: EPUB, FB2 "
            "или PDF, из которого можно выделить текст."
        )
    if total_chars / page_count > MAX_CHARS_PER_PAGE:
        raise ValueError("PDF выглядит повреждённым: слишком много текста на страницу")

    meta = _read_meta(reader, path)
    cleaned = _strip_running_lines(pages_lines)
    lines = [ln for page in cleaned for ln in page]

    sections: list[Section] = []
    outline = _read_outline(reader)
    if outline:
        starts = _pages_from_outline(outline, pages_lines, cleaned)
    else:
        starts = [(0, "Книга")]

    ranges: list[tuple[int, int, str]] = []
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(pages_lines)
        ranges.append((max(0, start), max(start + 1, end), title))

    if len(ranges) == 1:
        ranges = _split_by_headings(cleaned)

    counter = 0
    for start, end, title in ranges:
        chunk_lines = [ln for page in cleaned[start:end] for ln in page]
        counter += 1
        blocks = _lines_to_blocks(chunk_lines, counter)
        if not blocks:
            continue
        if not title or title == "Книга":
            title = next((b.text for b in blocks if b.kind in ("h1", "h2")), f"Раздел {counter}")
        sections.append(
            Section(id=f"s{counter:02d}", kind="chapter", title=title.strip(), blocks=blocks)
        )

    if not sections:
        raise ValueError("не удалось разобрать PDF: текст есть, но структура не читается")

    if len(sections) < 3:
        # Для книги это тревожно: без глав оглавление будет из одного пункта.
        pass

    book = Book(meta=meta, sections=sections, source_format="pdf", source_path=path)
    book.warnings.append("PDF: разбиение на главы приблизительное, проверьте оглавление")
    if page_count > 0 and len(sections) <= 2:
        book.warnings.append("PDF: главы не найдены, вся книга — один раздел")
    return book


def _page_text(page) -> str:
    """Layout-режим сохраняет пустые строки — по ним видно границы абзацев."""
    try:
        text = page.extract_text(extraction_mode="layout")
        if text and text.strip():
            return text
    except Exception:
        pass
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


# --------------------------------------------------------------------- метаданные


def _read_meta(reader, path: str) -> Meta:
    info = reader.metadata or {}
    title = str(info.get("/Title") or "").strip()
    author = str(info.get("/Author") or "").strip()
    return Meta(
        title=title,
        authors=[author] if author else [],
        language="",
        identifier=str(info.get("/Subject") or ""),
        publisher=str(info.get("/Producer") or ""),
        description="",
    )


# ------------------------------------------------------------------- эвристики


def _strip_running_lines(pages: list[list[str]]) -> list[list[str]]:
    """Убирает колонтитулы и номера страниц: строки, повторяющиеся на многих страницах."""
    if len(pages) < 3:
        return [list(p) for p in pages]

    from collections import Counter

    def norm(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    heads = Counter()
    tails = Counter()
    for lines in pages:
        nonempty = [ln for ln in lines if ln.strip()]
        if not nonempty:
            continue
        heads[norm(nonempty[0])] += 1
        if len(nonempty) > 1:
            tails[norm(nonempty[-1])] += 1

    threshold = max(3, len(pages) // 2)
    drop_first = {k for k, v in heads.items() if v >= threshold and len(k) < 120}
    drop_last = {k for k, v in tails.items() if v >= threshold and len(k) < 120}

    out = []
    for lines in pages:
        nonempty_idx = [i for i, ln in enumerate(lines) if ln.strip()]
        keep = list(lines)
        if nonempty_idx and norm(lines[nonempty_idx[0]]) in drop_first:
            keep[nonempty_idx[0]] = ""
        if len(nonempty_idx) > 1 and norm(lines[nonempty_idx[-1]]) in drop_last:
            keep[nonempty_idx[-1]] = ""
        out.append(keep)
    return out


def _read_outline(reader) -> list[tuple[int, str]]:
    try:
        raw = reader.outline
    except Exception:
        return []
    out: list[tuple[int, str]] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                page = reader.get_destination_page_number(item)
                title = (item.title or "").strip()
            except Exception:
                continue
            if title:
                out.append((page, title))

    try:
        walk(raw)
    except Exception:
        return []
    return sorted(set(out))


def _pages_from_outline(
    outline: list[tuple[int, str]], pages: list[list[str]], cleaned: list[list[str]]
) -> list[tuple[int, str]]:
    starts = [(p, t) for p, t in outline if 0 <= p < len(pages)]
    return starts or [(0, "Книга")]


def _split_by_headings(cleaned: list[list[str]]) -> list[tuple[int, int, str]]:
    """Если закладок нет — режем по строкам вида «Chapter 7» и «Глава 7»."""
    flat: list[tuple[int, str]] = []
    for pno, page in enumerate(cleaned):
        for line in page:
            flat.append((pno, line))

    marks: list[tuple[int, str]] = []
    for i, (pno, line) in enumerate(flat):
        s = line.strip()
        if not s or len(s) > 90:
            continue
        if HEADING_RE.match(s) or (ALLCAPS_RE.match(s) and i + 1 < len(flat)
                                   and flat[i + 1][1].strip() and not ALLCAPS_RE.match(flat[i + 1][1].strip())):
            marks.append((pno, s))

    # Схлопываем подряд идущие заголовки на одной странице.
    merged: list[tuple[int, str]] = []
    for pno, title in marks:
        if merged and merged[-1][0] == pno:
            continue
        merged.append((pno, title))

    if len(merged) < 2:
        return [(0, len(cleaned), "Книга")]

    out = []
    for i, (pno, title) in enumerate(merged):
        end = merged[i + 1][0] if i + 1 < len(merged) else len(cleaned)
        out.append((pno, max(pno + 1, end), title))
    return out


def _lines_to_blocks(lines: list[str], section_no: int) -> list[Block]:
    blocks: list[Block] = []
    counter = 0

    def emit(kind: str, text: str) -> None:
        nonlocal counter
        counter += 1
        blocks.append(Block(id=f"s{section_no:02d}.b{counter:03d}", kind=kind, html=f"<{kind}>{text}</{kind}>"))

    para: list[str] = []

    def flush() -> None:
        nonlocal para
        if not para:
            return
        text = " ".join(para).strip()
        para = []
        if not text:
            return
        if _is_heading(text):
            emit("h2", text)
        else:
            emit("p", text)

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if len(line) <= 90 and _is_heading(line) and not para:
            flush()
            emit("h2", line)
            continue
        para.append(line)
        # Короткая строка с точкой — почти наверняка конец абзаца.
        if len(line) < 55 and re.search(r"[.!?…][»\"']?$", line):
            flush()

    flush()
    return blocks


def _is_heading(text: str) -> bool:
    s = text.strip()
    if not s or len(s) > 90:
        return False
    if HEADING_RE.match(s):
        return True
    if ALLCAPS_RE.match(s) and any(ch.isalpha() for ch in s):
        return True
    return False
