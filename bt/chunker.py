"""Нарезка книги на фрагменты для перевода.

Правила простые и жёсткие: абзац не режем никогда, фрагмент — 1 000–1 500 слов
исходника, к каждому фрагменту прикладывается хвост предыдущего. Без хвоста
модель на стыке теряет, кто такой «he», и начинает выдумывать.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .model import Block, Book, Section

DEFAULT_MAX_WORDS = 1300
DEFAULT_MIN_WORDS = 350

TRANSLATABLE_KINDS = ("chapter", "appendix", "notes")


@dataclass
class Chunk:
    id: str
    section_id: str
    section_title: str
    index: int
    total: int
    blocks: list[Block]
    prev_blocks: list[Block] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(b.words for b in self.blocks)

    @property
    def text(self) -> str:
        return "\n\n".join(b.html for b in self.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "index": self.index,
            "total": self.total,
            "words": self.words,
            "blocks": [b.to_dict() for b in self.blocks],
            "prev_blocks": [b.to_dict() for b in self.prev_blocks],
        }


def make_chunks(
    book: Book,
    max_words: int = DEFAULT_MAX_WORDS,
    min_words: int = DEFAULT_MIN_WORDS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in book.sections:
        if section.kind not in TRANSLATABLE_KINDS:
            continue
        groups = _split_section(section, max_words, min_words)
        for index, group in enumerate(groups, start=1):
            prev = chunks[-1].blocks[-2:] if chunks else []
            chunks.append(
                Chunk(
                    id=f"{section.id}.c{index:02d}",
                    section_id=section.id,
                    section_title=section.title,
                    index=index,
                    total=len(groups),
                    blocks=group,
                    prev_blocks=list(prev),
                )
            )
    return chunks


def _split_section(section: Section, max_words: int, min_words: int) -> list[list[Block]]:
    groups: list[list[Block]] = []
    current: list[Block] = []
    words = 0

    for block in section.blocks:
        block_words = block.words

        # Абзац длиннее лимита — отдельный фрагмент: резать его нельзя,
        # но и приклеивать к соседям незачем, иначе фрагмент распухает.
        if block_words > max_words:
            if current:
                groups.append(current)
                current = []
                words = 0
            groups.append([block])
            continue

        # Разрыв ставим перед блоком, если текущий фрагмент уже набрал минимум
        # и следующий блок выводит его за предел. Разрыв после `hr` (сцена
        # закончилась) предпочтительнее — но не в ущерб размеру.
        if current and words + block_words > max_words and words >= min_words:
            groups.append(current)
            current = []
            words = 0

        current.append(block)
        words += block_words

    if current:
        groups.append(current)

    # Последний фрагмент, который меньше минимума, приклеиваем к предыдущему:
    # кусок в 40 слов модели переводить бессмысленно. Но не к гигантскому
    # абзацу — тому соседи не нужны.
    if len(groups) > 1 and sum(b.words for b in groups[-1]) < min_words:
        if not any(b.words > max_words for b in groups[-2]):
            groups[-2].extend(groups.pop())

    return groups


def chunk_stats(chunks: Iterable[Chunk]) -> dict[str, int]:
    chunks = list(chunks)
    if not chunks:
        return {"count": 0, "words": 0, "min": 0, "max": 0, "avg": 0}
    sizes = [c.words for c in chunks]
    return {
        "count": len(chunks),
        "words": sum(sizes),
        "min": min(sizes),
        "max": max(sizes),
        "avg": round(sum(sizes) / len(sizes)),
    }
