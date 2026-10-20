"""Импорт EPUB: структура, метаданные, обложка, инлайн-разметка, сноски.

Книга не пересобирается: для каждого блока запоминается файл и XPath элемента,
чтобы на выходе править исходный XHTML на месте и не терять вёрстку.
"""

from __future__ import annotations

import posixpath
import re
from typing import Iterable

from lxml import etree

from ..model import Block, Book, Meta, Section, strip_tags
from ..epubutil import (
    DC,
    EPUB_TYPE,
    OPF,
    XHTML,
    EpubArchive,
    join_href,
    localname,
    parse_xml,
)

#: Блочные элементы, которые становятся отдельными блоками перевода.
BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre",
    "td", "th", "dt", "dd", "figcaption", "div", "section", "article",
    "aside", "header", "footer", "address", "caption", "ul", "ol", "dl",
    "figure", "table", "tr",
}
SKIP_TAGS = {"script", "style", "svg", "object", "iframe", "noscript", "head"}

FRONT_RE = re.compile(
    r"^(cover|обложка|title ?page|half ?title|copyright|dedication|epigraph|"
    r"contents|table of contents|содержание|foreword|preface|предисловие|"
    r"вступление|acknowledg|благодарност)",
    re.I,
)
APPENDIX_RE = re.compile(r"^(appendix|приложение|afterword|послесловие)", re.I)
NOTES_RE = re.compile(r"^(notes|примечания|комментарии|footnotes|сноски)", re.I)
FRONT_HREF_RE = re.compile(
    r"(titlepage|title_page|title-page|copyright|colophon|cover|halftitle|dedication)", re.I
)


def import_epub(path: str) -> Book:
    with EpubArchive(path) as archive:
        container = parse_xml(archive.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", namespaces={"c": "urn:oasis:names:tc:opendocument:xmlns:container"})
        if rootfile is None or not rootfile.get("full-path"):
            raise ValueError("в EPUB нет META-INF/container.xml с rootfile")
        opf_path = rootfile.get("full-path")
        opf = parse_xml(archive.read(opf_path))

        manifest = _read_manifest(opf, opf_path)
        spine = _read_spine(opf)
        meta = _read_meta(opf)
        nav_titles = _read_nav_titles(archive, opf_path, manifest)

        cover_href = _find_cover(opf, manifest)
        if cover_href:
            meta.cover_href = cover_href

        book = Book(meta=meta, source_format="epub", source_path=path)
        assets = _read_assets(archive, manifest)
        book.assets = assets

        index = 0
        for idref, linear in spine:
            item = manifest.get(idref)
            if not item:
                continue
            if item["type"] not in ("application/xhtml+xml", "text/html"):
                continue
            if "nav" in (item["properties"] or "").split():
                continue
            if linear == "no":
                continue
            try:
                data = archive.read(item["path"])
            except KeyError as exc:
                book.warnings.append(f"пропущен файл {item['href']}: {exc}")
                continue

            doc = parse_xml(data)
            tree = doc.getroottree()
            body = doc.find(".//x:body", namespaces={"x": XHTML})
            if body is None:
                continue

            section_no = index + 1
            blocks = list(_collect_blocks(body, section_no))
            if not blocks:
                continue

            title = _section_title(doc, blocks, nav_titles.get(item["href"], ""))
            kind = _classify(title, item["href"])
            if kind == "frontmatter" and not blocks:
                continue

            index += 1
            book.sections.append(
                Section(
                    id=f"s{index:02d}",
                    kind=kind,
                    title=title or f"Раздел {index}",
                    blocks=blocks,
                    href=item["path"],
                )
            )

        _annotate_xpath(archive, book)

    if not book.sections:
        raise ValueError("в EPUB не нашлось текстовых разделов")
    if not book.meta.language:
        book.warnings.append("не указан язык книги")
    if not book.meta.cover_href:
        book.warnings.append("обложка не найдена")
    return book


# --------------------------------------------------------------------------- OPF


def _read_manifest(opf: etree._Element, opf_path: str) -> dict[str, dict]:
    """id → {href (от каталога OPF), path (путь в архиве), type, properties}."""
    out: dict[str, dict] = {}
    for item in opf.findall(".//opf:manifest/opf:item", namespaces={"opf": OPF}):
        href = item.get("href", "")
        out[item.get("id", "")] = {
            "href": href,
            "path": join_href(opf_path, href),
            "type": (item.get("media-type") or "").lower(),
            "properties": item.get("properties") or "",
        }
    return out


def _read_spine(opf: etree._Element) -> list[tuple[str, str]]:
    spine = opf.find(".//opf:spine", namespaces={"opf": OPF})
    if spine is None:
        return []
    return [(ir.get("idref", ""), ir.get("linear", "yes")) for ir in spine.findall("opf:itemref", namespaces={"opf": OPF})]


def _read_meta(opf: etree._Element) -> Meta:
    ns = {"dc": DC, "opf": OPF}

    def first(tag: str) -> str:
        el = opf.find(f".//dc:{tag}", namespaces=ns)
        return (el.text or "").strip() if el is not None else ""

    authors = [a.text.strip() for a in opf.findall(".//dc:creator", namespaces=ns) if a.text and a.text.strip()]
    return Meta(
        title=first("title"),
        authors=authors,
        language=first("language"),
        identifier=first("identifier"),
        publisher=first("publisher"),
        description=first("description"),
    )


def _find_cover(opf: etree._Element, manifest: dict[str, dict]) -> str | None:
    for item in manifest.values():
        if "cover-image" in (item["properties"] or "").split():
            return item["path"]
    meta = opf.find(".//opf:metadata/opf:meta[@name='cover']", namespaces={"opf": OPF})
    if meta is not None:
        item = manifest.get(meta.get("content", ""))
        if item:
            return item["path"]
    for item in manifest.values():
        if "cover" in item["path"].lower() and item["type"].startswith("image/"):
            return item["path"]
    return None


def _read_assets(archive: EpubArchive, manifest: dict[str, dict]) -> dict[str, bytes]:
    assets: dict[str, bytes] = {}
    total = 0
    for item in manifest.values():
        path, media = item["path"], item["type"]
        if not (media.startswith("image/") or media in ("text/css", "application/font-woff",
                                                        "font/woff", "font/woff2", "application/vnd.ms-opentype")):
            continue
        try:
            data = archive.read(path)
        except KeyError:
            continue
        if len(data) > 20_000_000 or total + len(data) > 120_000_000:
            continue
        assets[path] = data
        total += len(data)
    return assets


def _read_nav_titles(archive: EpubArchive, opf_path: str, manifest: dict[str, dict]) -> dict[str, str]:
    """Заголовки разделов из toc.ncx: нужны, когда в самом XHTML заголовка нет."""
    titles: dict[str, str] = {}
    ncx_href = next((i["href"] for i in manifest.values() if i["type"] == "application/x-dtbncx+xml"), None)
    if not ncx_href:
        return titles
    try:
        ncx = parse_xml(archive.read(ncx_href))
    except Exception:
        return titles
    for nav in ncx.findall(".//{*}navPoint"):
        label = nav.find(".//{*}text")
        content = nav.find(".//{*}content")
        if label is None or content is None or not label.text:
            continue
        src = (content.get("src") or "").split("#")[0]
        if not src:
            continue
        key = posixpath.relpath(join_href(ncx_href, src), posixpath.dirname(opf_path) or ".")
        titles.setdefault(key, label.text.strip())
    return titles


# ------------------------------------------------------------------------ blocks


def iter_block_elements(body: etree._Element) -> Iterable[tuple[etree._Element, str]]:
    """Листовые блочные элементы в порядке документа — единая точка правды.

    Импорт и последующая правка «на месте» должны видеть одни и те же элементы
    в одном и том же порядке, иначе блоки разъедутся.
    """

    def walk(el: etree._Element, quote: bool = False) -> Iterable[tuple[etree._Element, str]]:
        for child in el:
            tag = localname(child.tag)
            if not tag or tag in SKIP_TAGS:
                continue
            if tag in BLOCK_TAGS:
                if _has_block_child(child):
                    yield from walk(child, quote or tag == "blockquote")
                elif tag == "div" and not strip_tags(etree.tostring(child, encoding="unicode")):
                    continue
                else:
                    yield child, ("quote" if (quote or tag == "blockquote") else tag)
            elif tag in ("img", "hr"):
                yield child, tag
            else:
                yield from walk(child, quote)

    yield from walk(body)


#: Прежнее имя: внутренние вызовы не должны ломаться.
_iter_block_elements = iter_block_elements


def _collect_blocks(body: etree._Element, section_no: int) -> Iterable[Block]:
    for counter, (el, kind) in enumerate(_iter_block_elements(body), start=1):
        # Хвост элемента (`\n  ` между абзацами) — это разметка документа, а не
        # текст блока. Если его не убрать, он уедет в промпт и в перевод.
        tail = el.tail
        el.tail = None
        try:
            html = etree.tostring(el, encoding="unicode", method="html")
        finally:
            el.tail = tail
        yield Block(id=f"s{section_no:02d}.b{counter:03d}", kind=kind, html=html)


def _has_block_child(el: etree._Element) -> bool:
    return any(localname(c.tag) in BLOCK_TAGS for c in el)


def _section_title(doc: etree._Element, blocks: list[Block], nav_title: str) -> str:
    for b in blocks:
        if b.kind in ("h1", "h2", "h3"):
            text = strip_tags(b.html)
            if text:
                return text
    if nav_title:
        return nav_title
    t = doc.find(".//x:head/x:title", namespaces={"x": XHTML})
    return strip_tags(etree.tostring(t, encoding="unicode")) if t is not None else ""


def _classify(title: str, href: str) -> str:
    low = (title or "").strip()
    if FRONT_RE.search(low):
        return "frontmatter"
    if NOTES_RE.search(low):
        return "notes"
    if APPENDIX_RE.search(low):
        return "appendix"
    # Титул, копирайт и обложка часто названы просто «Output» или названием книги,
    # зато лежат в файле с говорящим именем.
    if FRONT_HREF_RE.search(href.rsplit("/", 1)[-1]):
        return "frontmatter"
    return "chapter"


def _annotate_xpath(archive: EpubArchive, book: Book) -> None:
    """Проставляет каждому блоку XPath в исходном документе (для сборки «на месте»)."""
    by_href: dict[str, list[Block]] = {}
    for section in book.sections:
        if section.href:
            by_href.setdefault(section.href, []).extend(section.blocks)

    for href, blocks in by_href.items():
        try:
            doc = parse_xml(archive.read(href))
        except KeyError:
            continue
        body = doc.find(".//x:body", namespaces={"x": XHTML})
        if body is None:
            continue
        elements = [el for el, _ in _iter_block_elements(body)]
        for block, el in zip(blocks, elements):
            block.href = href
            block.xpath = doc.getroottree().getpath(el)

