"""Перевод книги: фрагмент → запрос к модели → проверка → кэш.

Задача модуля — довести книгу до состояния «все блоки переведены», не потеряв
при этом ни одного абзаца и не заплатив дважды за один и тот же запрос.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from .chunker import Chunk, make_chunks
from .glossary import Glossary, Term
from .llm import LLMClient, LLMError, LLMResponse, Usage
from .model import Book
from .prompts import Prompt, load_prompt
from .quality import Issue, audit_block, sort_issues, summarize

ProgressFn = Callable[[int, int, int], None]

BLOCK_RE = re.compile(r'<block id="([^"]+)">(.*?)</block>', re.S)


class TranslationAborted(Exception):
    pass


@dataclass
class TranslationOptions:
    jobs: int = 3
    min_words: int = 350
    max_words: int = 1300
    temperature: float | None = None
    retries: int = 2
    cache_dir: str | None = None
    profile: dict[str, str] = field(default_factory=dict)
    recap: str = ""


@dataclass
class TranslationResult:
    blocks: dict[str, str] = field(default_factory=dict)
    new_terms: list[Term] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    chunks_total: int = 0
    chunks_done: int = 0
    chunks_cached: int = 0
    chunks_failed: int = 0
    seconds: float = 0.0

    def cost(self, model: str) -> float:
        return self.usage.cost(model)

    def summary(self) -> dict[str, Any]:
        counts = summarize(self.issues)
        return {
            "chunks": self.chunks_total,
            "done": self.chunks_done,
            "cached": self.chunks_cached,
            "failed": self.chunks_failed,
            "issues": counts,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "seconds": round(self.seconds, 1),
        }


class Translator:
    def __init__(
        self,
        client: LLMClient,
        glossary: Glossary | None = None,
        options: TranslationOptions | None = None,
        prompt: Prompt | None = None,
        progress: ProgressFn | None = None,
    ):
        self.client = client
        self.glossary = glossary or Glossary()
        self.options = options or TranslationOptions()
        self.prompt = prompt or load_prompt("translate")
        self.progress = progress
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._cache_dir = self.options.cache_dir or os.path.join(os.getcwd(), ".bt-cache")
        os.makedirs(self._cache_dir, exist_ok=True)

    # --------------------------------------------------------------------- вход

    def run(self, book: Book, limit: int | None = None) -> TranslationResult:
        started = time.time()
        chunks = make_chunks(book, max_words=self.options.max_words, min_words=self.options.min_words)
        if limit:
            chunks = chunks[:limit]

        result = TranslationResult(chunks_total=len(chunks))
        translated: dict[str, str] = {}
        done = cached = failed = 0

        self._emit_progress(0, len(chunks), 0)

        with ThreadPoolExecutor(max_workers=max(1, self.options.jobs)) as pool:
            futures = {pool.submit(self._process_chunk, chunk, translated): chunk for chunk in chunks}
            for future in as_completed(futures):
                if self._abort.is_set():
                    raise TranslationAborted("перевод остановлен")
                chunk = futures[future]
                try:
                    chunk_map, usage, issues, was_cached, ok = future.result()
                except Exception as exc:  # модель упала окончательно
                    failed += 1
                    with self._lock:
                        result.issues.append(
                            Issue(chunk.id, "critical", "chunk_failed", f"фрагмент не переведён: {exc}")
                        )
                    done += 1
                    self._emit_progress(done, len(chunks), cached)
                    continue

                with self._lock:
                    translated.update(chunk_map)
                    result.blocks.update(chunk_map)
                    result.usage.add(usage)
                    result.issues.extend(issues)
                    if was_cached:
                        cached += 1
                    if not ok:
                        failed += 1
                        result.issues.append(
                            Issue(
                                chunk.id,
                                "critical",
                                "chunk_failed",
                                "фрагмент переведён не полностью — часть текста осталась на английском",
                            )
                        )
                done += 1
                self._emit_progress(done, len(chunks), cached)

        result.chunks_done = done
        result.chunks_cached = cached
        result.chunks_failed = failed
        result.seconds = time.time() - started

        # Блоки, до которых очередь не дошла (лимит, падение), остаются как есть.
        for section in book.sections:
            for block in section.blocks:
                result.blocks.setdefault(block.id, block.html)

        result.issues = sort_issues(result.issues)
        return result

    def abort(self) -> None:
        self._abort.set()

    # ---------------------------------------------------------------- обработка

    def _process_chunk(
        self, chunk: Chunk, translated: dict[str, str]
    ) -> tuple[dict[str, str], Usage, list[Issue], bool, bool]:
        key = self._cache_key(chunk)
        cached = self._read_cache(key)
        if cached:
            mapping = dict(cached["ru"])
            usage = Usage(**cached.get("usage", {}))
            failed_ids = list(cached.get("failed") or [])
            # Старый кэш мог сохранить ответ, где модель вернула английский текст.
            # Такие блоки переводим заново, не оплачивая удачные заново.
            pending = [
                b for b in chunk.blocks
                if b.id in set(failed_ids)
                or _looks_untranslated(b.html, mapping.get(b.id, ""))
            ]
            if pending:
                extra, more_usage, failed_ids = self._translate_blocks(chunk, pending, translated, depth=0)
                usage.add(more_usage)
                mapping.update(extra)
                if not failed_ids:
                    self._write_cache(key, mapping, usage, failed=[])
            issues = self._audit(chunk, mapping)
            for block in chunk.blocks:
                mapping.setdefault(block.id, block.html)
            return mapping, usage, issues, True, not failed_ids

        mapping, usage, failed_ids = self._translate_blocks(chunk, chunk.blocks, translated, depth=0)
        for block in chunk.blocks:
            mapping.setdefault(block.id, block.html)
        issues = self._audit(chunk, mapping)

        if failed_ids:
            from . import applog

            applog.log(
                f"фрагмент {chunk.id}: не переведено блоков {len(failed_ids)} "
                f"({', '.join(failed_ids[:5])})"
            )
        else:
            self._write_cache(key, mapping, usage, failed=[])
        return mapping, usage, issues, False, not failed_ids

    def _translate_blocks(
        self,
        chunk: Chunk,
        blocks: list,
        translated: dict[str, str],
        depth: int = 0,
    ) -> tuple[dict[str, str], Usage, list[str]]:
        """Переводит набор блоков; при сбое дробит его и повторяет мелкими частями."""
        if not blocks:
            return {}, Usage(), []

        ids = {b.id for b in blocks}
        usage = Usage()
        mapping: dict[str, str] = {}

        try:
            response = self._call(chunk, blocks, translated)
            usage.add(response.usage)
            parsed, _ = _parse_blocks_lenient(response.text)
            mapping = {k: v for k, v in parsed.items() if k in ids}
            if response.finish_reason == "length":
                from . import applog

                applog.log(
                    f"фрагмент {chunk.id}: ответ обрезан по лимиту токенов "
                    f"(блоков {len(blocks)}, получено {len(mapping)})"
                )
        except (LLMError, ValueError) as exc:
            from . import applog

            applog.log(f"фрагмент {chunk.id}: сбой ответа модели: {exc}")

        # Блок, который вернулся без кириллицы, считаем непереведённым.
        missing = [
            b for b in blocks
            if b.id not in mapping or _looks_untranslated(b.html, mapping.get(b.id, ""))
        ]
        if not missing:
            return mapping, usage, []

        if depth < 3 and len(blocks) > 1:
            # Делим пополам: маленькие запросы почти никогда не обрезаются.
            middle = max(1, len(missing) // 2)
            parts = [missing[:middle], missing[middle:]] if len(missing) > 1 else [missing]
            failed: list[str] = []
            for part in parts:
                part_map, part_usage, part_failed = self._translate_blocks(
                    chunk, part, translated, depth + 1
                )
                mapping.update(part_map)
                usage.add(part_usage)
                failed.extend(part_failed)
            return mapping, usage, failed

        return mapping, usage, [b.id for b in missing]

    def _call(self, chunk: Chunk, blocks: list, translated: dict[str, str],
              feedback: Any = None) -> LLMResponse:
        text = "\n".join(b.text for b in blocks)
        matched = self.glossary.match(text)
        pool: list = []
        seen: set[str] = set()
        for term in matched + self.glossary.core():
            key = term.en.lower()
            if key not in seen:
                seen.add(key)
                pool.append(term)

        prev_en = "\n\n".join(b.text for b in chunk.prev_blocks[-2:]) or "(начало книги)"
        prev_ru = "\n\n".join(
            translated.get(b.id, "") for b in chunk.prev_blocks[-2:] if translated.get(b.id)
        ) or "(перевода ещё нет)"

        values = {
            "title": self.options.profile.get("title", ""),
            "author": self.options.profile.get("author", ""),
            "genre": self.options.profile.get("genre", "художественная проза"),
            "pov": self.options.profile.get("pov", "не определено"),
            "tense": self.options.profile.get("tense", "не определено"),
            "tone": self.options.profile.get("tone", "нейтральный"),
            "address": self.options.profile.get("address", "нет"),
            "notes": self.options.profile.get("notes", "—"),
            "recap": self.options.recap or "(начало книги)",
            "prev_en": prev_en,
            "prev_ru": prev_ru,
            "glossary": self.glossary.render(pool) if pool else "(пусто)",
            "forbidden": ", ".join(self.glossary.forbidden_variants()) or "нет",
            "chunk_no": str(chunk.index),
            "chunk_total": str(chunk.total),
            "chapter_title": chunk.section_title,
            "blocks_html": "\n".join(f'<block id="{b.id}">{b.html}</block>' for b in blocks),
        }
        system, user = self.prompt.render(**values)
        if feedback:
            user += f"\n\n## Замечание к предыдущей попытке\n{feedback}"

        # Запас по выходным токенам: русский текст длиннее английского.
        return self.client.chat(system, user, temperature=self.options.temperature,
                                max_tokens=16_000)

    def _audit(self, chunk: Chunk, mapping: dict[str, str]) -> list[Issue]:
        issues: list[Issue] = []
        for block in chunk.blocks:
            issues.extend(audit_block(block, mapping.get(block.id, ""), self.glossary))
        return issues

    # --------------------------------------------------------------------- кэш

    def _cache_key(self, chunk: Chunk) -> str:
        config = getattr(self.client, "config", None)
        model = getattr(config, "model", None) or "mock"
        payload = json.dumps(
            {
                "model": model,
                "prompt": self.prompt.version,
                "system": self.prompt.system[:200],
                "glossary": self.glossary.fingerprint(),
                "blocks": [b.html for b in chunk.blocks],
                "context": [b.html for b in chunk.prev_blocks],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(self._cache_dir, key[:2], key + ".json")

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        path = self._cache_path(key)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key: str, mapping: dict[str, str], usage: Usage,
                     failed: list[str] | None = None) -> None:
        path = self._cache_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {"ru": mapping, "usage": {"prompt_tokens": usage.prompt_tokens,
                                            "completion_tokens": usage.completion_tokens},
                   "failed": list(failed or [])}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass

    def _emit_progress(self, done: int, total: int, cached: int) -> None:
        if self.progress:
            try:
                self.progress(done, total, cached)
            except Exception:
                pass


# ---------------------------------------------------------------------- разбор


def _parse_blocks_lenient(text: str) -> tuple[dict[str, str], bool]:
    """Разбирает ответ и вытаскивает хотя бы целые блоки, если JSON обрезан.

    Возвращает (id → html, полностью_ли). При обрыве ответа модель успевает
    написать первые блоки — их не нужно переводить и оплачивать заново.
    """
    try:
        items = _parse_blocks(text)
        return {item["id"]: item["ru"] for item in items}, True
    except Exception:
        pass

    salvaged: dict[str, str] = {}
    pattern = re.compile(
        r'"id"\s*:\s*"([^"]+)"[\s,]*"ru"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S
    )
    for match in pattern.finditer(text):
        raw = match.group(2)
        try:
            value = json.loads('"' + raw + '"')
        except json.JSONDecodeError:
            value = raw.replace('\\"', '"').replace("\\n", "\n")
        if value.strip():
            salvaged[match.group(1)] = value
    return salvaged, False


def _looks_untranslated(source_html: str, translated_html: str) -> bool:
    """Блок без кириллицы при английском исходнике — почти наверняка не переведён."""
    if not translated_html or not translated_html.strip():
        return True
    if re.search(r"[А-Яа-яЁё]", translated_html):
        return False
    from .model import strip_tags

    return len(strip_tags(source_html).split()) >= 4


def _parse_blocks(text: str) -> list[dict[str, str]]:
    """Достаёт список блоков из ответа модели. Терпим к ``` и висячим запятым."""
    data = _extract_json(text)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        raise ValueError("ответ модели — не JSON-объект")

    blocks = data.get("blocks")
    if isinstance(blocks, list):
        out = []
        for item in blocks:
            if isinstance(item, dict) and item.get("id") and isinstance(item.get("ru"), str):
                out.append({"id": item["id"], "ru": item["ru"]})
        return out

    # Резервный формат: {"s01.b001": "текст"}.
    if all(isinstance(v, str) for v in data.values()):
        return [{"id": k, "ru": v} for k, v in data.items()]

    raise ValueError("в ответе нет поля blocks")


def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", cleaned)
        return json.loads(repaired)
