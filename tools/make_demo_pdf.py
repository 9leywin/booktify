"""Генерирует демонстрационный PDF с текстовым слоем.

Нужен, чтобы проверять PDF-импортёр на настоящем файле, а не только на
эвристиках в тестах. Формат PDF пишется руками: несколько страниц, колонтитулы,
номера страниц, три главы.
"""

from __future__ import annotations

import os
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "demo", "demo_book.pdf")

PAGE_W, PAGE_H = 595, 842
MARGIN_X, MARGIN_TOP, LINE_H = 72, 92, 17
FONT_SIZE = 12
CHARS_PER_LINE = 82

BOOK_TITLE = "A Short Book About Testing"
AUTHOR = "Demo Author"

CHAPTERS = [
    (
        "Chapter 1",
        [
            "The morning was cold and the road was empty. Corin Cadence walked toward the tower "
            "with a notebook under his arm and no plan at all.",
            "He had been told that the tower was dangerous, that the tests were unfair, and that "
            "nobody would help him inside. He had decided to go anyway.",
            "At the gate a guard looked at his papers, sighed, and waved him through. The corridor "
            "beyond smelled of dust and old paper.",
        ],
    ),
    (
        "Chapter 2",
        [
            "Inside, the tower was quieter than he expected. Every step echoed twice, as if the "
            "walls were repeating his decisions back at him.",
            "A woman in a grey coat waited by the stairs. She did not introduce herself. She only "
            "said that the first test had already begun and that he had failed it twice.",
            "Corin wrote that down. It seemed like the kind of thing that would matter later.",
        ],
    ),
    (
        "Chapter 3",
        [
            "The last room had no door. There was a window, a chair, and a clock that ran backwards. "
            "On the chair lay a book with his name on the cover.",
            "He opened it and found that the pages were blank except for one sentence: the story "
            "begins when the reader stops waiting for permission.",
            "He closed the book, put it in his bag, and climbed back down the stairs.",
        ],
    ),
]


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def wrap(text: str, width: int = CHARS_PER_LINE) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_pages() -> list[list[str]]:
    pages: list[list[str]] = []
    for title, paragraphs in CHAPTERS:
        lines: list[str] = [title, ""]
        for paragraph in paragraphs:
            lines.extend(wrap(paragraph))
            lines.append("")
        pages.append(lines)
    return pages


def content_stream(lines: list[str], page_no: int, total: int) -> bytes:
    parts = ["BT", f"/F1 {FONT_SIZE} Tf", f"{LINE_H} TL", f"{MARGIN_X} {PAGE_H - MARGIN_TOP} Td"]
    # Колонтитул и номер страницы — импортёр должен их выбросить.
    parts.append(f"/F1 9 Tf ({escape(BOOK_TITLE)}) Tj")
    parts.append(f"/F1 {FONT_SIZE} Tf 0 -{LINE_H * 1.6:.0f} Td")

    first = True
    for line in lines:
        if not line:
            parts.append(f"0 -{LINE_H} Td")
            continue
        if not first:
            parts.append("T*")
        else:
            first = False
        parts.append(f"({escape(line)}) Tj")

    parts.append("ET")
    parts.append("BT")
    parts.append(f"/F1 9 Tf {PAGE_W - MARGIN_X - 40} 40 Td ({page_no} of {total}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("cp1252", "replace")


def pdf_bytes() -> bytes:
    pages = build_pages()
    total = len(pages)

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # 1: catalog, 2: pages, 3: font, 4: info — заполним после, но номера фиксируем.
    objects.append(b"")  # 1
    objects.append(b"")  # 2
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"")  # 4 info

    page_ids: list[int] = []
    for index, lines in enumerate(pages, start=1):
        stream = zlib.compress(content_stream(lines, index, total))
        content_id = add(
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream"
            % (len(stream), stream)
        )
        page_id = add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_W, PAGE_H, content_id)
        )
        page_ids.append(page_id)

    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    objects[3] = (
        b"<< /Title (%s) /Author (%s) /Producer (book-translator demo) >>"
        % (escape(BOOK_TITLE).encode(), escape(AUTHOR).encode())
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 4 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_pos,
    )
    return bytes(out)


def main() -> int:
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    data = pdf_bytes()
    with open(TARGET, "wb") as fh:
        fh.write(data)
    print(f"{TARGET}: {len(data)} байт, {len(CHAPTERS)} главы")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
