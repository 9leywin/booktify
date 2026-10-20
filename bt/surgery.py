"""Сборка EPUB «правкой на месте».

Для EPUB на входе книгу нельзя пересобирать: читалка потеряет вёрстку, сноски,
обложку и стили. Поэтому мы открываем тот же архив, находим в каждом XHTML
ровно те элементы, что были при импорте, и меняем только их содержимое.
Всё остальное копируется байт в байт.
"""

from __future__ import annotations

import os
import posixpath
import re
import zipfile

from lxml import etree, html as lxml_html

from .epubbuild import validate_epub
from .epubutil import DC, OPF, XHTML, parse_xml
from .importers.epub import iter_block_elements
from .model import Book

DOCTYPES = {
    "html5": "<!DOCTYPE html>",
    "xhtml11": '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
               '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
}


def build_epub_surgery(
    book: Book,
    source_path: str,
    out_path: str,
    translations: dict[str, str],
    language: str = "ru",
) -> list[str]:
    """Переписывает текстовые узлы исходного EPUB. Возвращает предупреждения."""
    warnings: list[str] = []

    by_href: dict[str, list] = {}
    for section in book.sections:
        if section.href:
            by_href.setdefault(section.href, []).append(section)

    titles = _translated_titles(book, translations)
    changed: dict[str, bytes] = {}
    with zipfile.ZipFile(source_path) as src:
        for href, sections in by_href.items():
            try:
                raw = src.read(href)
            except KeyError:
                warnings.append(f"в архиве нет {href}")
                continue
            blocks = [b for section in sections for b in section.blocks]
            new_raw, replaced = _rewrite_document(raw, blocks, translations)
            if replaced:
                changed[href] = new_raw

        manifest = _manifest(src)
        for name, item in manifest.items():
            if "nav" in (item.get("properties") or "").split():
                raw = src.read(item["path"])
                updated = _retitle_nav(raw, item["path"], titles)
                if updated is not None:
                    changed[item["path"]] = updated
            elif item["type"] == "application/x-dtbncx+xml":
                raw = src.read(item["path"])
                updated = _retitle_ncx(raw, item["path"], titles)
                if updated is not None:
                    changed[item["path"]] = updated

        opf_path = _find_opf(src)
        opf_raw = src.read(opf_path)
        new_opf, opf_changed = _update_opf(opf_raw, language, book)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        tmp_path = out_path + ".tmp"
        with zipfile.ZipFile(tmp_path, "w") as dst:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            dst.writestr(info, "application/epub+zip")

            for item in src.infolist():
                name = item.filename
                if name == "mimetype":
                    continue
                if name == opf_path:
                    dst.writestr(item, new_opf if opf_changed else opf_raw)
                elif name in changed:
                    dst.writestr(item, changed[name])
                else:
                    dst.writestr(item, src.read(name))

        os.replace(tmp_path, out_path)

    warnings.extend(validate_epub(out_path))
    return warnings


def _find_opf(zf: zipfile.ZipFile) -> str:
    container = parse_xml(zf.read("META-INF/container.xml"))
    rootfile = container.find(
        ".//c:rootfile", namespaces={"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    )
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB без OPF")
    return rootfile.get("full-path")


def _manifest(zf: zipfile.ZipFile) -> dict[str, dict]:
    opf_path = _find_opf(zf)
    opf = parse_xml(zf.read(opf_path))
    base = posixpath.dirname(opf_path)

    def resolve(href: str) -> str:
        return posixpath.normpath(posixpath.join(base, href)).lstrip("/") if href else ""

    out = {}
    for item in opf.findall(".//opf:item", namespaces={"opf": OPF}):
        out[item.get("id", "")] = {
            "href": item.get("href", ""),
            "path": resolve(item.get("href", "")),
            "type": (item.get("media-type") or "").lower(),
            "properties": item.get("properties") or "",
        }
    return out


def _translated_titles(book: Book, translations: dict[str, str]) -> dict[str, str]:
    """Названия разделов на русском: из переведённого заголовка, иначе из оригинала."""
    titles: dict[str, str] = {}
    for section in book.sections:
        if not section.href:
            continue
        title = ""
        for block in section.blocks:
            if block.kind in ("h1", "h2", "h3"):
                html = translations.get(block.id)
                if html:
                    title = _plain(html)
                    break
        titles[section.href] = title or section.title
    return titles


def _plain(html: str) -> str:
    import html as html_mod

    return html_mod.unescape(re.sub(r"<[^>]+>", " ", html)).strip()


def _retitle_nav(raw: bytes, nav_path: str, titles: dict[str, str]) -> bytes | None:
    """Подписи в `nav.xhtml` — это те же названия глав, их тоже надо перевести."""
    if not titles:
        return None
    doc = parse_xml(raw)
    body = doc.find(".//x:body", namespaces={"x": XHTML})
    if body is None:
        return None

    changed = False
    for link in body.iter():
        if not isinstance(link.tag, str) or not link.tag.endswith("}a"):
            continue
        href = (link.get("href") or "").strip()
        path = href.split("#")[0]
        if not path:
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(nav_path), path))
        new_title = titles.get(target)
        if not new_title:
            continue
        if (link.text or "").strip() == new_title and len(link) == 0:
            continue
        for child in list(link):
            link.remove(child)
        link.text = new_title
        changed = True
    if not changed:
        return None
    return etree.tostring(doc.getroottree(), encoding="utf-8", xml_declaration=True)


def _retitle_ncx(raw: bytes, ncx_path: str, titles: dict[str, str]) -> bytes | None:
    """EPUB 2: подписи лежат в `toc.ncx`."""
    if not titles:
        return None
    try:
        doc = parse_xml(raw)
    except Exception:
        return None

    changed = False
    for nav_point in doc.iter():
        if not isinstance(nav_point.tag, str) or not nav_point.tag.endswith("navPoint"):
            continue
        label = None
        content = None
        for child in nav_point.iter():
            if isinstance(child.tag, str) and child.tag.endswith("navLabel"):
                label = child
            if isinstance(child.tag, str) and child.tag.endswith("content"):
                content = child
        if label is None or content is None:
            continue
        src = (content.get("src") or "").split("#")[0]
        if not src:
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(ncx_path), src))
        new_title = titles.get(target)
        if not new_title:
            continue
        text = label.find(".//{*}text")
        if text is not None and (text.text or "").strip() != new_title:
            text.text = new_title
            changed = True

    if not changed:
        return None
    return etree.tostring(doc.getroottree(), encoding="utf-8", xml_declaration=True)


def _rewrite_document(raw: bytes, blocks, translations: dict[str, str]) -> tuple[bytes, int]:
    doc = parse_xml(raw)
    body = doc.find(".//x:body", namespaces={"x": XHTML})
    if body is None:
        return raw, 0

    elements = [el for el, _ in iter_block_elements(body)]
    replaced = 0
    for block, element in zip(blocks, elements):
        new_html = translations.get(block.id)
        if not new_html or new_html == block.html:
            continue
        if _replace_content(element, new_html):
            replaced += 1

    if not replaced:
        return raw, 0

    doctype = _doctype(raw)
    tree = doc.getroottree()
    return (
        etree.tostring(tree, encoding="utf-8", xml_declaration=True, doctype=doctype),
        replaced,
    )


def _replace_content(element: etree._Element, new_html: str) -> bool:
    """Кладёт содержимое переведённого фрагмента внутрь исходного элемента.

    Обёртка и атрибуты (`class`, `id`, `epub:type`) остаются оригинальными —
    поэтому стили и сноски продолжают работать.
    """
    new_html = new_html.strip()
    try:
        fragments = lxml_html.fragments_fromstring(new_html)
    except Exception:
        return False

    nodes = [f for f in fragments if not isinstance(f, str)]
    if not nodes:
        element.text = new_html.strip()
        for child in list(element):
            element.remove(child)
        return True

    node = nodes[0]
    element.text = node.text
    for child in list(element):
        element.remove(child)
    for child in list(node):
        element.append(child)
    return True


def _doctype(raw: bytes) -> str | None:
    match = re.search(rb"<!DOCTYPE[^>]*>", raw[:4096], re.IGNORECASE)
    return match.group(0).decode("utf-8", "replace") if match else None


def _update_opf(raw: bytes, language: str, book: Book) -> tuple[bytes, bool]:
    try:
        opf = parse_xml(raw)
    except Exception:
        return raw, False

    changed = False
    lang = opf.find(".//opf:metadata/dc:language", namespaces={"opf": OPF, "dc": DC})
    if lang is None:
        metadata = opf.find(".//opf:metadata", namespaces={"opf": OPF})
        if metadata is not None:
            lang = etree.SubElement(metadata, f"{{{DC}}}language")
            changed = True
    if lang is not None and (lang.text or "") != language:
        lang.text = language
        changed = True

    if not changed:
        return raw, False
    return etree.tostring(opf, encoding="utf-8", xml_declaration=True), True
