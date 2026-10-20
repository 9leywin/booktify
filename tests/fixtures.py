"""Синтетические книги для тестов: не зависим от файлов на диске."""

from __future__ import annotations

import os
import textwrap
import zipfile

from bt.model import Block, Book, Meta, Section

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:11111111-2222-3333-4444-555555555555</dc:identifier>
    <dc:title>Test Book</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Test Press</dc:publisher>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="styles/style.css" media-type="text/css"/>
    <item id="cover-img" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
  </manifest>
  <spine>
    <itemref idref="title"/>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
    <itemref idref="nav" linear="no"/>
  </spine>
</package>
"""

TITLE_PAGE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Title Page</title></head>
<body><h1>Title Page</h1><p>Test Book, written by Jane Doe.</p></body>
</html>
"""

CH1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Chapter One</title></head>
<body>
  <h1>Chapter One</h1>
  <p>Hello <em>world</em>, this is a test paragraph with enough words to count.</p>
  <p class="intro">Second paragraph with <strong>bold text</strong> and a note<a epub:type="noteref" href="notes.xhtml#n1">1</a>.</p>
  <blockquote><p>A quoted line from somewhere else entirely.</p></blockquote>
  <ul><li>First item in a list</li><li>Second item in the same list</li></ul>
  <hr/>
</body>
</html>
"""

CH2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter Two</title></head>
<body>
  <h2>Chapter Two</h2>
  <p>The second chapter begins here and keeps going for a while.</p>
  <img src="images/cover.jpg" alt="picture"/>
</body>
</html>
"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body><nav epub:type="toc"><ol>
<li><a href="ch1.xhtml">Chapter One</a></li>
<li><a href="ch2.xhtml">Chapter Two</a></li>
</ol></nav></body>
</html>
"""

FB2 = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
             xmlns:l="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <genre>sf</genre>
      <author><first-name>Ivan</first-name><last-name>Petrov</last-name></author>
      <book-title>Test FB2</book-title>
      <lang>en</lang>
      <coverpage><image l:href="#cover.jpg"/></coverpage>
    </title-info>
    <document-info><id>123</id></document-info>
  </description>
  <body>
    <section>
      <title><p>Chapter One</p></title>
      <epigraph><p>An epigraph line.</p></epigraph>
      <p>First paragraph of the book with <emphasis>emphasis</emphasis> inside.</p>
      <p>Second paragraph.</p>
      <section>
        <title><p>Subsection</p></title>
        <p>Nested text lives here.</p>
      </section>
    </section>
    <section>
      <title><p>Chapter Two</p></title>
      <poem><title><p>A Poem</p></title>
        <stanza><v>First line</v><v>Second line</v></stanza>
      </poem>
      <image l:href="#pic.png"/>
    </section>
  </body>
  <body name="notes">
    <section id="n1"><title><p>1</p></title><p>A note text.</p></section>
  </body>
  <binary id="cover.jpg" content-type="image/jpeg">/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==</binary>
  <binary id="pic.png" content-type="image/png">iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==</binary>
</FictionBook>
"""


def make_epub(directory: str) -> str:
    path = os.path.join(directory, "test.epub")
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/title.xhtml", TITLE_PAGE)
        zf.writestr("OEBPS/ch1.xhtml", CH1)
        zf.writestr("OEBPS/ch2.xhtml", CH2)
        zf.writestr("OEBPS/nav.xhtml", NAV)
        zf.writestr("OEBPS/styles/style.css", "body { font-family: serif; }")
        zf.writestr("OEBPS/images/cover.jpg", b"\xff\xd8\xff\xe0" + b"0" * 64)
    return path


def make_fb2(directory: str) -> str:
    path = os.path.join(directory, "test.fb2")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(FB2))
    return path


def make_book(block_count: int = 10, words_per_block: int = 100) -> Book:
    blocks = [
        Block(
            id=f"s01.b{i:03d}",
            kind="p",
            html="<p>" + " ".join(["word"] * words_per_block) + "</p>",
        )
        for i in range(1, block_count + 1)
    ]
    return Book(
        meta=Meta(title="Synthetic", authors=["Test"], language="en"),
        sections=[Section(id="s01", kind="chapter", title="One", blocks=blocks)],
        source_format="test",
    )
