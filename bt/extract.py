"""Заготовка глоссария: кандидаты из текста и уточнение у модели.

Механика ищет имена и термины по частотности (заглавные слова не в начале
предложения, устойчивые пары, выдуманные слова). Модель получает список
с контекстом и решает, как это писать по-русски, какого рода и склоняется ли.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from .glossary import Glossary, Term
from .model import Book

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]{1,}")
CAPITALIZED_RE = re.compile(r"[A-Z][A-Za-z'’\-]{1,}")
SENTENCE_START = set(".!?…:;—–-\"'«(\n\r\t")

DISCOURSE = {
    "maybe", "possibly", "instead", "fortunately", "unfortunately", "suddenly",
    "finally", "actually", "certainly", "probably", "obviously", "apparently",
    "meanwhile", "however", "therefore", "perhaps", "eventually",
}

COMMON = set(
    """
    the a an and or but if then than that this these those there here
    he she it they we you i his her its their our your my me him them us
    was were is are be been being have has had do does did will would could
    should may might must can shall not no yes so as at by for from in into
    of on out over under to up with without within about after before during
    before again once when where while who whom whose what which why how
    all any both each few more most other some such only own same too very
    just now then also even still yet already almost always never often
    chapter part book one two three four five six seven eight nine ten
    mr mrs ms dr sir lady lord king queen prince princess
    """.split()
)


@dataclass
class Candidate:
    en: str
    count: int
    sample: str

    def to_dict(self) -> dict[str, Any]:
        return {"en": self.en, "count": self.count, "sample": self.sample}


@dataclass
class ExtractionResult:
    profile: dict[str, str] = field(default_factory=dict)
    glossary: Glossary = field(default_factory=Glossary)
    candidates: list[Candidate] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    usage: Any = None


def candidates(book: Book, min_count: int = 2, limit: int = 150) -> list[Candidate]:
    """Механические кандидаты: частые заглавные слова и пары заглавных."""
    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}
    pairs: Counter[str] = Counter()

    for section in book.sections:
        if section.kind == "frontmatter":
            continue
        for block in section.blocks:
            text = block.text
            if not text:
                continue
            previous = ""
            for match in TOKEN_RE.finditer(text):
                token = match.group()
                start = match.start()
                is_start = start <= 0 or text[start - 1] in SENTENCE_START
                if CAPITALIZED_RE.fullmatch(token) and not is_start:
                    counts[token] += 1
                    samples.setdefault(token, text[:140])
                    if previous and CAPITALIZED_RE.fullmatch(previous):
                        pairs[f"{previous} {token}"] += 1
                previous = token

    for pair, count in pairs.items():
        if count >= min_count:
            counts[pair] = max(counts.get(pair, 0), count)
            samples.setdefault(pair, samples.get(pair.split()[0], ""))

    result = []
    for word, count in counts.most_common():
        if count < min_count or len(word) < 3:
            continue
        if "'" in word or "’" in word:
            continue  # стяжения: I'd, he's, don't
        if word.lower() in DISCOURSE:
            continue
        if word.lower() in COMMON or all(part.lower() in COMMON for part in word.split()):
            continue
        # Одно слово, входящее в устойчивую пару, не дублируем.
        if " " not in word and any(p.startswith(word + " ") for p in counts if " " in p and counts[p] >= count):
            continue
        result.append(Candidate(en=word, count=count, sample=samples.get(word, "")[:140]))
        if len(result) >= limit:
            break
    return result


def extract(
    book: Book,
    client=None,
    existing: Glossary | None = None,
    limit: int = 150,
    sample_chars: int = 6000,
) -> ExtractionResult:
    cands = candidates(book, limit=limit)
    result = ExtractionResult(candidates=cands, glossary=Glossary(existing.terms if existing else []))

    if client is None:
        return result

    text_parts = []
    for section in book.sections:
        if section.kind in ("chapter", "appendix"):
            text_parts.append(section.text)
        if sum(len(p) for p in text_parts) >= sample_chars:
            break
    full = "\n\n".join(text_parts)
    start = full[: sample_chars // 2]
    middle = full[sample_chars // 2: sample_chars]

    from .prompts import load_prompt

    prompt = load_prompt("glossary")

    def ask(subset: list[Candidate]):
        system, user = prompt.render(
            title=book.meta.title or "(без названия)",
            author=", ".join(book.meta.authors) or "(неизвестен)",
            lang=book.meta.language or "en",
            sample_start=start,
            sample_middle=middle or "(нет)",
            candidates="\n".join(f"{c.en} — {c.count} — {c.sample}" for c in subset),
            existing_glossary=result.glossary.render(result.glossary.terms) or "(пусто)",
        )
        response = client.chat(system, user, max_tokens=12_000)
        return response, _extract_json(response.text)

    try:
        response, data = ask(cands)
    except Exception:
        # Ответ мог обрезаться: повторяем с коротким списком.
        try:
            response, data = ask(cands[:40])
        except Exception as exc:
            from . import applog

            applog.log(f"глоссарий не собрался: {exc}")
            result.uncertain.append("глоссарий собрать не удалось — переводим без него")
            return result

    result.usage = getattr(response, "usage", None)

    profile = data.get("profile") or {}
    result.profile = {str(k): str(v) for k, v in profile.items()}
    result.uncertain = [str(x) for x in (data.get("uncertain") or [])]

    for item in data.get("glossary") or []:
        if not isinstance(item, dict):
            continue
        term = Term.from_dict(item)
        if not term.en or not term.ru:
            continue
        if result.glossary.terms and any(t.en.lower() == term.en.lower() for t in result.glossary.terms):
            continue
        result.glossary.add(term)

    return result


def profile_for(book: Book, profile: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "title": book.meta.title,
        "author": ", ".join(book.meta.authors),
    }
    base.update(profile or {})
    return base


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", cleaned))
        except json.JSONDecodeError:
            # Обрыв ответа: пробуем прочитать закрытые объекты из массива glossary.
            partial = re.search(r'"glossary"\s*:\s*\[(.*)', cleaned, re.S)
            if partial:
                items = []
                for item in re.finditer(r"\{[^{}]*\}", partial.group(1), re.S):
                    try:
                        items.append(json.loads(item.group(0)))
                    except json.JSONDecodeError:
                        continue
                if items:
                    return {"glossary": items}
            raise
