"""Импорт FB2: главы, эпиграфы, стихи, сноски, картинки.

FB2 — это XML, поэтому структура читается точно. Сложность не в парсинге,
а в том, чтобы не потерять эпиграфы, стихи и примечания: их нельзя сваливать
в общий поток абзацев, иначе после перевода книга станет плоской.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from typing import Iterable

from lxml import etree

from ..model import Block, Book, Meta, Section, strip_tags
from ..epubutil import FB2, XLINK, localname, parse_xml

NS = {"fb": FB2, "l": XLINK}

SKIP = {"script", "style"}

#: Расширения, которые понимают читалки; всё остальное отдаём как есть.
KNOWN_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/svg+xml": ".svg"}


def import_fb2(path: str) -> Book:
    with open(path, "rb") as fh:
        raw = fh.read()
    root = parse_xml(raw)
    if not root.tag.endswith("FictionBook"):
        raise ValueError("это не FB2: корневой элемент не FictionBook")

    meta = _read_meta(root)
    images = _read_images(root)
    book = Book(meta=meta, source_format="fb2", source_path=path)

    if meta.cover_href and meta.cover_href in images:
        book.assets[meta.cover_href] = images[meta.cover_href][0]

    bodies = [b for b in root.findall("fb:body", NS)]
    main = [b for b in bodies if (b.get("name") or "") != "notes"]
    notes = [b for b in bodies if (b.get("name") or "") == "notes"]

    counter = 0
    for body in main:
        for section in _iter_sections(body):
            counter += 1
            blocks = list(_section_blocks(section, counter, images, book.assets))
            title = _section_title(section) or f"Раздел {counter}"
            book.sections.append(
                Section(id=f"s{counter:02d}", kind="chapter", title=title, blocks=blocks)
            )

    for body in notes:
        for section in _iter_sections(body):
            counter += 1
            blocks = list(_section_blocks(section, counter, images, book.assets))
            title = _section_title(section) or "Примечание"
            book.sections.append(
                Section(id=f"s{counter:02d}", kind="notes", title=title, blocks=blocks)
            )

    if not book.sections:
        raise ValueError("в FB2 не нашлось ни одного раздела с текстом")
    if not book.meta.language:
        book.warnings.append("не указан язык книги")
    return book


# --------------------------------------------------------------------- метаданные


def _text(el: etree._Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _read_meta(root: etree._Element) -> Meta:
    info = root.find("fb:description/fb:title-info", NS)
    if info is None:
        return Meta()

    authors = []
    for author in info.findall("fb:author", NS):
        parts = [
            _text(author.find("fb:first-name", NS)),
            _text(author.find("fb:middle-name", NS)),
            _text(author.find("fb:last-name", NS)),
        ]
        name = " ".join(p for p in parts if p)
        if name:
            authors.append(name)

    cover_href = None
    cover_img = info.find("fb:coverpage/fb:image", NS)
    if cover_img is not None:
        cover_href = _image_href(cover_img, "")

    return Meta(
        title=_text(info.find("fb:book-title", NS)),
        authors=authors,
        language=_text(info.find("fb:lang", NS)),
        identifier=_text(info.find("fb:src-lang", NS)),
        publisher="",
        description=_text(info.find("fb:annotation", NS)),
        cover_href=cover_href,
    )


def _read_images(root: etree._Element) -> dict[str, tuple[bytes, str]]:
    """id → (байты, имя файла внутри будущего EPUB)."""
    out: dict[str, tuple[bytes, str]] = {}
    for binary in root.findall("fb:binary", NS):
        ident = binary.get("id") or ""
        media = binary.get("content-type") or "image/jpeg"
        try:
            data = base64.b64decode("".join((binary.text or "").split()))
        except Exception:
            continue
        ext = KNOWN_EXT.get(media) or mimetypes.guess_extension(media) or ".bin"
        digest = hashlib.sha1(data).hexdigest()[:10]
        name = f"images/fb2_{digest}{ext}"
        out[ident] = (data, name)
    return out


# ------------------------------------------------------------------------ блоки


def _iter_sections(body: etree._Element) -> Iterable[etree._Element]:
    for section in body.findall("fb:section", NS):
        yield section
        yield from _iter_sections(section)


def _section_title(section: etree._Element) -> str:
    title = section.find("fb:title", NS)
    if title is None:
        return ""
    parts = [_text(p) for p in title.findall("fb:p", NS)]
    return " ".join(p for p in parts if p)


def _section_blocks(
    section: etree._Element,
    section_no: int,
    images: dict[str, tuple[bytes, str]],
    assets: dict[str, bytes],
) -> Iterable[Block]:
    counter = 0

    def emit(kind: str, html: str) -> Block:
        nonlocal counter
        counter += 1
        return Block(id=f"s{section_no:02d}.b{counter:03d}", kind=kind, html=html)

    for child in section:
        tag = localname(child.tag)
        if tag in ("section", "title"):
            continue
        if tag == "p":
            text = _inline_text(child)
            if text.strip():
                yield emit("p", f"<p>{text}</p>")
        elif tag == "subtitle":
            text = _inline_text(child)
            if text.strip():
                yield emit("h3", f"<h3 class=\"subtitle\">{text}</h3>")
        elif tag == "empty-line":
            yield emit("hr", '<hr class="sep"/>')
        elif tag == "epigraph":
            html = "".join(f"<p>{_inline_text(p)}</p>" for p in child.findall("fb:p", NS))
            if html:
                yield emit("quote", f'<blockquote class="epigraph">{html}</blockquote>')
        elif tag == "cite":
            html = "".join(f"<p>{_inline_text(p)}</p>" for p in child.findall("fb:p", NS))
            if html:
                yield emit("quote", f'<blockquote class="cite">{html}</blockquote>')
        elif tag == "poem":
            for stanza in _poem_stanzas(child):
                yield emit("poem", stanza)
        elif tag == "image":
            href = _image_href(child, "")
            if href in images:
                data, name = images[href]
                assets[name] = data
                yield emit("image", f'<img src="{name}" alt=""/>')
        elif tag in ("table",):
            html = _table_html(child)
            if html:
                yield emit("table", html)


def _poem_stanzas(poem: etree._Element) -> Iterable[str]:
    title = ""
    t = poem.find("fb:title", NS)
    if t is not None:
        title = f'<p class="poem-title">{_inline_text(t)}</p>'
    for stanza in poem.findall("fb:stanza", NS):
        lines = [_inline_text(v) for v in stanza.findall("fb:v", NS)]
        lines = [ln for ln in lines if ln.strip()]
        if not lines:
            continue
        body = "<br/>".join(lines)
        yield f'<div class="poem">{title}<p class="stanza">{body}</p></div>'
        title = ""


def _table_html(table: etree._Element) -> str:
    rows = []
    for tr in table.findall("fb:tr", NS):
        cells = []
        for td in tr:
            if localname(td.tag) not in ("td", "th"):
                continue
            cells.append(f"<td>{_inline_text(td)}</td>")
        if cells:
            rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table>{''.join(rows)}</table>" if rows else ""


def _inline_text(el: etree._Element) -> str:
    """Текст элемента с сохранением `<strong>`, `<emphasis>`, `<a>`."""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        from xml.sax.saxutils import escape

        if node.text:
            parts.append(escape(node.text))
        for child in node:
            tag = localname(child.tag)
            if tag in ("strong",):
                parts.append("<strong>")
                walk(child)
                parts.append("</strong>")
            elif tag in ("emphasis",):
                parts.append("<em>")
                walk(child)
                parts.append("</em>")
            elif tag in ("a", "style") and child.get(f"{{{XLINK}}}href"):
                href = child.get(f"{{{XLINK}}}href") or ""
                parts.append(f'<a href="{escape(href)}">')
                walk(child)
                parts.append("</a>")
            elif tag == "image":
                continue
            else:
                walk(child)
            if child.tail:
                parts.append(escape(child.tail))

    walk(el)
    return "".join(parts).strip()


def _image_href(el: etree._Element, _unused: str) -> str:
    href = el.get(f"{{{XLINK}}}href") or ""
    return href[1:] if href.startswith("#") else href
