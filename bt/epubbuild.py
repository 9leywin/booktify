"""Сборка EPUB 3 из модели книги.

Два режима:
- `build` — собрать книгу заново из блоков (FB2, PDF и предпросмотр);
- позже появится `surgery` — правка исходного EPUB на месте, без пересборки вёрстки.

Здесь только первый: он проще, его хватает для FB2/PDF и для проверки того,
что перевод доехал до читалки.
"""

from __future__ import annotations

import html as html_mod
import os
import posixpath
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lxml import etree

from .model import Book, count_words

LANG = "ru"
MEDIA_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}

CSS = """@charset "utf-8";

body {
  font-family: Georgia, "PT Serif", "Times New Roman", serif;
  line-height: 1.5;
  margin: 0 5%;
  text-align: left;
  widows: 2;
  orphans: 2;
  hyphens: auto;
}

h1 { font-size: 1.55em; line-height: 1.2; margin: 2em 0 1.2em; text-align: center; page-break-before: always; }
h2 { font-size: 1.25em; margin: 1.6em 0 0.8em; text-align: center; }
h3 { font-size: 1.1em; margin: 1.2em 0 0.6em; }
h3.subtitle { text-align: center; font-style: italic; font-weight: normal; }

p { margin: 0; text-indent: 1.3em; }
h1 + p, h2 + p, h3 + p, hr + p, blockquote + p, ul + p { text-indent: 0; }

hr.sep { border: 0; margin: 1.4em 0; text-align: center; height: 1.2em; }
hr.sep:after { content: "\\2022 \\2022 \\2022"; letter-spacing: 0.6em; color: #777; }

blockquote { margin: 1em 1.6em; font-style: italic; }
blockquote p { text-indent: 0; margin: 0.4em 0; }

div.poem { margin: 1.2em 0 1.2em 2em; }
div.poem p.stanza { text-indent: 0; margin: 0.7em 0; line-height: 1.35; }
p.poem-title { text-indent: 0; font-style: italic; margin-bottom: 0.6em; }

ul, ol { margin: 0.8em 0 0.8em 1.6em; }
li { margin: 0.25em 0; text-indent: 0; }

img { max-width: 100%; }
figure { margin: 1.2em 0; text-align: center; }

table { border-collapse: collapse; margin: 1em auto; font-size: 0.95em; }
td, th { border: 1px solid #aaa; padding: 0.25em 0.5em; }

section.titlepage { margin-top: 22%; text-align: center; }
p.tp-author { font-size: 1.2em; letter-spacing: 0.14em; text-indent: 0; margin-bottom: 2em; }
h1.tp-title { font-size: 2em; margin: 0 0 0.5em; page-break-before: avoid; }
p.tp-note { font-size: 0.85em; color: #555; text-indent: 0; margin-top: 3em; }
"""

PAGE = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
{body}
</body>
</html>
"""


@dataclass
class BuildOptions:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    language: str = LANG
    translator_note: bool = True
    translator_label: str = "перевод с английского"
    include_glossary: bool = False
    glossary_html: str = ""


def build_epub(
    book: Book,
    out_path: str,
    translations: dict[str, str] | None = None,
    options: BuildOptions | None = None,
) -> list[str]:
    """Собирает EPUB. Возвращает список предупреждений (пустой — всё хорошо)."""
    translations = translations or {}
    opts = options or BuildOptions()
    warnings: list[str] = []

    title = opts.title or book.meta.title or "Без названия"
    authors = opts.authors or book.meta.authors
    sections = [s for s in book.sections if s.blocks]

    if not sections:
        raise ValueError("нечего собирать: в книге нет блоков")

    files: dict[str, bytes] = {}
    manifest: list[str] = []
    spine: list[str] = []
    nav_items: list[tuple[str, str]] = []

    files["styles/style.css"] = CSS.encode("utf-8")
    manifest.append('<item id="css" href="styles/style.css" media-type="text/css"/>')

    # --- обложка
    cover_key = book.meta.cover_href if book.meta.cover_href in book.assets else None
    if cover_key:
        ext = os.path.splitext(cover_key)[1].lower() or ".jpg"
        cover_name = f"images/cover{ext}"
        files[cover_name] = book.assets[cover_key]
        media = MEDIA_EXT.get(ext, "image/jpeg")
        manifest.append(
            f'<item id="cover-image" href="{cover_name}" media-type="{media}" properties="cover-image"/>'
        )
        files["text/cover.xhtml"] = _page("Обложка", '<div style="text-align:center;"><img src="../images/cover%s" alt="%s"/></div>' % (ext, _esc(title))).encode("utf-8")
        manifest.append('<item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover"/>')
    else:
        warnings.append("у книги нет обложки — читалка покажет заглушку")

    # --- титул
    tp = ['<section class="titlepage">']
    if authors:
        tp.append(f'<p class="tp-author">{_esc(", ".join(authors))}</p>')
    tp.append(f'<h1 class="tp-title">{_esc(title)}</h1>')
    if opts.translator_note:
        tp.append(f'<p class="tp-note">{_esc(opts.translator_label)}</p>')
    tp.append("</section>")
    files["text/titlepage.xhtml"] = _page(title, "\n".join(tp)).encode("utf-8")
    manifest.append('<item id="titlepage" href="text/titlepage.xhtml" media-type="application/xhtml+xml"/>')
    spine.append('<itemref idref="titlepage"/>')
    nav_items.append(("Титул", "text/titlepage.xhtml"))

    # --- картинки (кроме обложки)
    used_assets: dict[str, str] = {}
    for section in sections:
        for block in section.blocks:
            for src in re.findall(r'src="([^"]+)"', block.html):
                if src in book.assets and src not in used_assets and not src.startswith(".."):
                    name = _safe_asset_name(src, used_assets)
                    used_assets[src] = name
                    files[name] = book.assets[src]
                    media = MEDIA_EXT.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
                    manifest.append(
                        f'<item id="img-{len(used_assets)}" href="{name}" media-type="{media}"/>'
                    )

    # --- разделы
    for index, section in enumerate(sections, start=1):
        slug = section.id
        body = _render_blocks(section.blocks, translations, used_assets, warnings)
        heading = ""
        if not any(b.kind in ("h1", "h2") for b in section.blocks):
            heading = f"<h1>{_esc(section.title or f'Раздел {index}')}</h1>\n"
        html = _page(section.title or title, heading + body)
        href = f"text/{slug}.xhtml"
        files[href] = html.encode("utf-8")
        manifest.append(f'<item id="{slug}" href="{href}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{slug}"/>')
        nav_items.append((section.title or f"Раздел {index}", href))

    # --- глоссарий (по желанию)
    if opts.include_glossary and opts.glossary_html:
        files["text/glossary.xhtml"] = _page("Глоссарий", opts.glossary_html).encode("utf-8")
        manifest.append('<item id="glossary" href="text/glossary.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="glossary"/>')
        nav_items.append(("Глоссарий", "text/glossary.xhtml"))

    # --- навигация
    files["nav.xhtml"] = _nav(nav_items).encode("utf-8")
    manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')

    # --- OPF
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    book_id = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, book.source_path or title))
    files["content.opf"] = _opf(
        title=title, authors=authors, language=opts.language, identifier=book_id,
        modified=modified, manifest=manifest, spine=spine,
    ).encode("utf-8")
    files["META-INF/container.xml"] = _CONTAINER.encode("utf-8")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        for name, data in files.items():
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    warnings.extend(validate_epub(out_path))
    return warnings


# ------------------------------------------------------------------ рендеринг


def _render_blocks(
    blocks, translations: dict[str, str], assets: dict[str, str], warnings: list[str]
) -> str:
    out: list[str] = []
    list_open = False
    quote_open = False

    def close_quote() -> None:
        nonlocal quote_open
        if quote_open:
            out.append("</blockquote>")
            quote_open = False

    for block in blocks:
        content = _coerce(translations.get(block.id) or block.html, block.kind)
        content = _rewrite_src(content, assets)
        kind = block.kind

        if kind == "li" and not list_open:
            out.append("<ul>")
            list_open = True
        elif kind != "li" and list_open:
            out.append("</ul>")
            list_open = False

        if kind == "quote":
            # FB2 уже отдаёт цитату в <blockquote>; обёртку добавляем только если её нет.
            if not content.lstrip().startswith("<blockquote"):
                if not quote_open:
                    out.append('<blockquote class="quote">')
                    quote_open = True
            else:
                close_quote()
        else:
            close_quote()

        out.append(content)

        if _count_words(content) == 0 and kind not in ("hr", "img", "image"):
            warnings.append(f"пустой блок {block.id}")

    if list_open:
        out.append("</ul>")
    close_quote()
    return "\n".join(out)


def _coerce(content: str, kind: str) -> str:
    """Переводчик может вернуть голый текст — оборачиваем в тег блока."""
    stripped = content.strip()
    if not stripped:
        return ""
    if stripped.startswith("<"):
        return stripped
    tag = "p" if kind in ("p", "quote", "div", "section") else kind
    if tag not in ("p", "h1", "h2", "h3", "h4", "li"):
        tag = "p"
    return f"<{tag}>{stripped}</{tag}>"


def _rewrite_src(content: str, assets: dict[str, str]) -> str:
    for src, name in assets.items():
        content = content.replace(f'src="{src}"', f'src="../{name}"')
    return content


def _count_words(html: str) -> int:
    return count_words(html)


def _esc(text: str) -> str:
    return html_mod.escape(text or "", quote=False)


def _safe_asset_name(src: str, used: dict[str, str]) -> str:
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:40] or "image"
    name = f"images/{stem}{ext.lower()}"
    n = 1
    while name in used.values():
        n += 1
        name = f"images/{stem}_{n}{ext.lower()}"
    return name


def _page(title: str, body: str) -> str:
    return PAGE.format(lang=LANG, title=_esc(title), body=body)


def _nav(items: list[tuple[str, str]]) -> str:
    lis = "\n".join(f'      <li><a href="{href}">{_esc(title)}</a></li>' for title, href in items)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{LANG}" xml:lang="{LANG}">
<head><meta charset="utf-8"/><title>Содержание</title>
<link rel="stylesheet" type="text/css" href="styles/style.css"/></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>Содержание</h1>
  <ol>
{lis}
  </ol>
</nav>
</body>
</html>
"""


def _opf(title, authors, language, identifier, modified, manifest, spine) -> str:
    creators = "\n".join(
        f'    <dc:creator id="author{i}">{_esc(a)}</dc:creator>'
        for i, a in enumerate(authors, start=1)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{language}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{_esc(identifier)}</dc:identifier>
    <dc:title>{_esc(title)}</dc:title>
{creators}
    <dc:language>{language}</dc:language>
    <dc:date>{modified}</dc:date>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    {chr(10).join("    " + m for m in manifest)}
  </manifest>
  <spine>
    {chr(10).join("    " + s for s in spine)}
  </spine>
</package>
"""


_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


# ------------------------------------------------------------------- проверка

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "x": "http://www.w3.org/1999/xhtml",
}


def validate_epub(path: str) -> list[str]:
    """Структурная проверка: mimetype, container, OPF, ссылки, XHTML."""
    problems: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            names = set(zf.namelist())
            check(infos[0].filename == "mimetype", "mimetype не первый файл")
            check(infos[0].compress_type == zipfile.ZIP_STORED, "mimetype сжат")
            check(zf.read("mimetype") == b"application/epub+zip", "неверный mimetype")

            container = etree.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(".//c:rootfile", NS)
            check(rootfile is not None, "нет rootfile в container.xml")
            if rootfile is None:
                return problems
            opf_path = rootfile.get("full-path")
            check(opf_path in names, f"OPF {opf_path} отсутствует")

            opf = etree.fromstring(zf.read(opf_path))
            base = posixpath.dirname(opf_path)

            def resolve(href: str | None) -> str | None:
                if not href:
                    return href
                return posixpath.normpath(posixpath.join(base, href)) if base else href

            items = {}
            for item in opf.findall(".//opf:manifest/opf:item", NS):
                items[item.get("id")] = item.get("href")
                path = resolve(item.get("href"))
                check(path in names, f"файла {item.get('href')} нет в архиве")
            spine = [ir.get("idref") for ir in opf.findall(".//opf:spine/opf:itemref", NS)]
            check(bool(spine), "пустой spine")
            for idref in spine:
                check(idref in items, f"idref {idref} не объявлен в manifest")

            title = opf.find(".//opf:metadata/dc:title", NS)
            check(title is not None and bool(title.text), "нет dc:title")
            lang = opf.find(".//opf:metadata/dc:language", NS)
            check(lang is not None, "нет dc:language")

            for href in items.values():
                path = resolve(href)
                if path and path.endswith((".xhtml", ".html")):
                    try:
                        etree.fromstring(zf.read(path))
                    except Exception as exc:
                        problems.append(f"{href} не парсится: {exc}")
    except zipfile.BadZipFile:
        problems.append("файл не является zip-архивом")
    return problems
