"""Модель документа: книга → разделы → блоки.

Единица перевода — блок. Блок хранит свой HTML целиком (вместе с обёрткой `<p>`),
поэтому после перевода видно, куда именно вставлять текст, а проверить разметку
можно по количеству и порядку тегов.

Модель ничего не знает ни про EPUB, ни про API, ни про интерфейс: её можно
сериализовать в JSON и гонять в тестах без книги на диске.
"""

from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

#: Теги, которые считаются блочными: каждый такой элемент — отдельный блок перевода.
BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "pre", "td", "th", "dt", "dd",
    "figcaption", "div", "section", "article", "aside",
    "header", "footer", "address", "caption",
}

SECTION_KINDS = {"frontmatter", "chapter", "appendix", "notes", "backmatter"}


def strip_tags(fragment: str) -> str:
    """Текст без разметки, с раскрытыми сущностями и схлопнутыми пробелами."""
    text = TAG_RE.sub(" ", fragment or "")
    return SPACE_RE.sub(" ", html_mod.unescape(text)).strip()


def count_words(fragment: str) -> int:
    text = strip_tags(fragment)
    return len(text.split()) if text else 0


@dataclass
class Block:
    """Один абзац/заголовок/элемент списка — то, что уходит в модель одним куском."""

    id: str
    kind: str
    html: str
    #: Для EPUB: файл и XPath элемента, чтобы потом править книгу на месте.
    href: str | None = None
    xpath: str | None = None

    @property
    def text(self) -> str:
        return strip_tags(self.html)

    @property
    def words(self) -> int:
        return count_words(self.html)

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "kind": self.kind, "html": self.html}
        if self.href:
            data["href"] = self.href
        if self.xpath:
            data["xpath"] = self.xpath
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        return cls(
            id=data["id"],
            kind=data.get("kind", "p"),
            html=data.get("html", ""),
            href=data.get("href"),
            xpath=data.get("xpath"),
        )


@dataclass
class Section:
    """Глава, приложение, титульная страница — единица навигации и прогресса."""

    id: str
    kind: str
    title: str
    blocks: list[Block] = field(default_factory=list)
    href: str | None = None

    @property
    def words(self) -> int:
        return sum(b.words for b in self.blocks)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "blocks": [b.to_dict() for b in self.blocks],
        }
        if self.href:
            data["href"] = self.href
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Section":
        return cls(
            id=data["id"],
            kind=data.get("kind", "chapter"),
            title=data.get("title", ""),
            blocks=[Block.from_dict(b) for b in data.get("blocks", [])],
            href=data.get("href"),
        )


@dataclass
class Meta:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = ""
    identifier: str = ""
    publisher: str = ""
    description: str = ""
    cover_href: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": list(self.authors),
            "language": self.language,
            "identifier": self.identifier,
            "publisher": self.publisher,
            "description": self.description,
            "cover_href": self.cover_href,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Meta":
        return cls(**{k: data.get(k, v) for k, v in {
            "title": "",
            "authors": [],
            "language": "",
            "identifier": "",
            "publisher": "",
            "description": "",
            "cover_href": None,
        }.items()})


@dataclass
class Book:
    meta: Meta = field(default_factory=Meta)
    sections: list[Section] = field(default_factory=list)
    assets: dict[str, bytes] = field(default_factory=dict)
    source_format: str = ""
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(s.words for s in self.sections)

    @property
    def blocks(self) -> int:
        return sum(len(s.blocks) for s in self.sections)

    def chapter_sections(self) -> list[Section]:
        return [s for s in self.sections if s.kind in ("chapter", "appendix")]

    def to_dict(self, include_assets: bool = False) -> dict[str, Any]:
        data = {
            "meta": self.meta.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
            "source_format": self.source_format,
            "source_path": self.source_path,
            "warnings": list(self.warnings),
        }
        if include_assets:
            import base64

            data["assets"] = {
                k: base64.b64encode(v).decode("ascii") for k, v in self.assets.items()
            }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Book":
        book = cls(
            meta=Meta.from_dict(data.get("meta", {})),
            sections=[Section.from_dict(s) for s in data.get("sections", [])],
            source_format=data.get("source_format", ""),
            source_path=data.get("source_path", ""),
            warnings=list(data.get("warnings", [])),
        )
        for name, b64 in (data.get("assets") or {}).items():
            import base64

            book.assets[name] = base64.b64decode(b64)
        return book

    def summary_rows(self) -> Iterable[tuple[str, int, int, int]]:
        """(id, блоков, слов, средняя длина блока) — для таблицы в CLI и GUI."""
        for s in self.sections:
            yield s.id, len(s.blocks), s.words, (s.words // len(s.blocks) if s.blocks else 0)
