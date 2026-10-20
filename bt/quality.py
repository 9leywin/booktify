"""Проверки перевода: то, что можно поймать без человека.

Ни одна проверка не «понимает» текст — они ловят механику: потерянные блоки,
сломанную разметку, исчезнувшие имена, латиницу, типографику и странный объём.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .glossary import Glossary
from .model import Block, count_words, strip_tags

TAG_RE = re.compile(r"<[^>]+>")
TAG_NAME_RE = re.compile(r"</?\s*([a-zA-Z0-9]+)")
LATIN_RE = re.compile(r"[A-Za-z]{2,}")
VOID = {"img", "br", "hr", "meta", "link", "input"}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


@dataclass
class Issue:
    block_id: str
    severity: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.block_id}: {self.message}"


def audit_block(source: Block, translated_html: str, glossary: Glossary | None = None) -> list[Issue]:
    # Картинки, разделители и пустые обёртки переводить нечего — и проверять нечего.
    if not source.text.strip():
        return []

    issues: list[Issue] = []
    ru_text = strip_tags(translated_html)

    if not ru_text.strip():
        return [Issue(source.id, "critical", "empty", "перевод пустой")]

    issues.extend(_tag_issues(source.id, source.html, translated_html))
    issues.extend(_length_issues(source, translated_html))
    issues.extend(_latin_issues(source.id, translated_html))
    issues.extend(_typography_issues(source.id, translated_html))

    if glossary is not None:
        for problem in glossary.violations(source.text, ru_text):
            issues.append(Issue(source.id, "major", "glossary", problem))

    return issues


def _tag_issues(block_id: str, source_html: str, translated_html: str) -> list[Issue]:
    def tags(html: str) -> list[str]:
        return [name.lower() for name in TAG_NAME_RE.findall(html) if name.lower() not in VOID]

    src, dst = tags(source_html), tags(translated_html)
    if src == dst:
        return []
    from collections import Counter

    missing = Counter(src) - Counter(dst)
    extra = Counter(dst) - Counter(src)
    details = []
    if missing:
        details.append("потеряны: " + ", ".join(f"{k}×{v}" for k, v in missing.items()))
    if extra:
        details.append("лишние: " + ", ".join(f"{k}×{v}" for k, v in extra.items()))
    if not details:
        details.append("нарушен порядок тегов")
    return [Issue(block_id, "major", "markup", "; ".join(details))]


def _length_issues(source: Block, translated_html: str) -> list[Issue]:
    src = count_words(source.html)
    dst = count_words(translated_html)
    if src < 6:
        return []
    ratio = dst / src
    if ratio < 0.55:
        return [Issue(source.id, "major", "short", f"перевод короче оригинала в {ratio:.2f} раза")]
    if ratio > 1.7:
        return [Issue(source.id, "minor", "long", f"перевод длиннее оригинала в {ratio:.2f} раза")]
    return []


def _latin_issues(block_id: str, translated_html: str) -> list[Issue]:
    text = strip_tags(translated_html)
    words = LATIN_RE.findall(text)
    if not words:
        return []
    sample = ", ".join(words[:5])
    return [Issue(block_id, "minor", "latin", f"латиница в переводе: {sample}")]


def _typography_issues(block_id: str, translated_html: str) -> list[Issue]:
    text = strip_tags(translated_html)
    problems = []
    if '"' in text or "'" in text:
        problems.append("прямые кавычки")
    if "..." in text:
        problems.append("три точки вместо …")
    if "  " in translated_html:
        problems.append("двойные пробелы")
    if problems:
        return [Issue(block_id, "minor", "typography", ", ".join(problems))]
    return []


def summarize(issues: list[Issue]) -> dict[str, int]:
    counts = {"critical": 0, "major": 0, "minor": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.block_id))
