"""Собирает демо-книгу FB2 из английской главы проекта.

Нужна для скриншотов и ручных проверок: настоящий английский текст, настоящие
имена, но маленький файл, который переводится за минуту.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "..", "book", "en", "ch_i_chapter_i_entry.txt")
TARGET = os.path.join(ROOT, "demo", "sam_en_ch1.fb2")

TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
             xmlns:l="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <genre>fantasy</genre>
      <author><first-name>Andrew</first-name><last-name>Rowe</last-name></author>
      <book-title>Sufficiently Advanced Magic — Chapter I</book-title>
      <lang>en</lang>
      <annotation><p>Demo chapter for the translator app.</p></annotation>
    </title-info>
    <document-info><id>demo-sam-ch1</id></document-info>
  </description>
  <body>
    <section>
      <title><p>Chapter I — Entry</p></title>
{paragraphs}
    </section>
  </body>
</FictionBook>
"""


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> int:
    with open(SOURCE, encoding="utf-8") as fh:
        raw = fh.read()

    paragraphs = []
    for block in raw.split("\n\n"):
        text = block.strip().lstrip("#").strip()
        if not text:
            continue
        paragraphs.append(f"      <p>{escape(text)}</p>")

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE.format(paragraphs="\n".join(paragraphs)))

    words = sum(len(p.split()) for p in paragraphs)
    print(f"{TARGET}: {len(paragraphs)} абзацев, {words} слов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
