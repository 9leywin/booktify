"""Второй проход: редактура перевода против оригинала.

Модель получает пары «оригинал — черновик» и возвращает точечные правки.
Применяются только те, что нашлись дословно и не сломали разметку; остальные
уходят в отчёт, а не «примерно туда».
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from .chunker import Chunk, make_chunks
from .glossary import Glossary
from .llm import Usage
from .model import Book
from .prompts import Prompt, load_prompt
from .quality import Issue, _tag_issues, audit_block, sort_issues, summarize

ProgressFn = Any

PRIORITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


@dataclass
class ReviewOptions:
    jobs: int = 3
    min_words: int = 350
    max_words: int = 1300
    cache_dir: str | None = None
    profile: dict[str, str] = field(default_factory=dict)
    max_edits: int = 40


@dataclass
class ReviewResult:
    blocks: dict[str, str] = field(default_factory=dict)
    applied: int = 0
    dropped: int = 0
    by_priority: dict[str, int] = field(default_factory=dict)
    dropped_reasons: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    chunks_total: int = 0
    chunks_cached: int = 0
    seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        counts = summarize(self.issues)
        return {
            "applied": self.applied,
            "dropped": self.dropped,
            "by_priority": dict(self.by_priority),
            "issues": counts,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "seconds": round(self.seconds, 1),
        }


class Reviewer:
    def __init__(
        self,
        client,
        glossary: Glossary | None = None,
        options: ReviewOptions | None = None,
        prompt: Prompt | None = None,
        progress: ProgressFn | None = None,
    ):
        self.client = client
        self.glossary = glossary or Glossary()
        self.options = options or ReviewOptions()
        self.prompt = prompt or load_prompt("review")
        self.progress = progress
        self._lock = threading.Lock()
        self._cache_dir = self.options.cache_dir or os.path.join(os.getcwd(), ".bt-cache")
        os.makedirs(self._cache_dir, exist_ok=True)

    def run(self, book: Book, translations: dict[str, str]) -> ReviewResult:
        started = time.time()
        chunks = make_chunks(book, max_words=self.options.max_words, min_words=self.options.min_words)
        result = ReviewResult(chunks_total=len(chunks), blocks=dict(translations))
        done = 0

        self._emit(0, len(chunks), 0)

        with ThreadPoolExecutor(max_workers=max(1, self.options.jobs)) as pool:
            futures = {
                pool.submit(self._review_chunk, chunk, translations): chunk for chunk in chunks
            }
            for future in as_completed(futures):
                try:
                    new_map, usage, applied, dropped, reasons, by_priority, cached = future.result()
                except Exception as exc:
                    with self._lock:
                        result.issues.append(
                            Issue(futures[future].id, "minor", "review_failed", f"редактура не удалась: {exc}")
                        )
                    done += 1
                    self._emit(done, len(chunks), result.chunks_cached)
                    continue

                with self._lock:
                    result.blocks.update(new_map)
                    result.usage.add(usage)
                    result.applied += applied
                    result.dropped += dropped
                    result.dropped_reasons.extend(reasons)
                    for key, value in by_priority.items():
                        result.by_priority[key] = result.by_priority.get(key, 0) + value
                    if cached:
                        result.chunks_cached += 1
                done += 1
                self._emit(done, len(chunks), result.chunks_cached)

        result.seconds = time.time() - started
        self._reaudit(book, result)
        result.issues = sort_issues(result.issues)
        return result

    # ------------------------------------------------------------------ фрагмент

    def _review_chunk(self, chunk: Chunk, translations: dict[str, str]):
        key = self._cache_key(chunk, translations)
        cached = self._read_cache(key)
        if cached:
            return (
                cached["blocks"],
                Usage(**cached.get("usage", {})),
                cached.get("applied", 0),
                cached.get("dropped", 0),
                [],
                {},
                True,
            )

        pairs = "\n\n".join(
            f"### Блок {b.id}\nEN: {b.text}\nRU: {translations.get(b.id, b.html)}"
            for b in chunk.blocks
            if b.text.strip()
        )
        matched = self.glossary.match("\n".join(b.text for b in chunk.blocks))
        values = {
            "title": self.options.profile.get("title", ""),
            "author": self.options.profile.get("author", ""),
            "genre": self.options.profile.get("genre", "художественная проза"),
            "pov": self.options.profile.get("pov", "не определено"),
            "tense": self.options.profile.get("tense", "не определено"),
            "tone": self.options.profile.get("tone", "нейтральный"),
            "chapter": chunk.section_title,
            "glossary": self.glossary.render(matched) if matched else "(не требуется)",
            "pairs": pairs,
        }
        system, user = self.prompt.render(**values)
        response = self.client.chat(system, user)

        new_map, applied, dropped, reasons, by_priority = _apply_edits(
            chunk, translations, _parse_edits(response.text), self.options.max_edits
        )
        self._write_cache(key, new_map, response.usage, applied, dropped)
        return new_map, response.usage, applied, dropped, reasons, by_priority, False

    def _reaudit(self, book: Book, result: ReviewResult) -> None:
        for section in book.sections:
            for block in section.blocks:
                html = result.blocks.get(block.id)
                if not html:
                    continue
                for issue in audit_block(block, html, self.glossary):
                    if issue.code in ("empty", "markup"):
                        result.issues.append(issue)

    # --------------------------------------------------------------------- кэш

    def _cache_key(self, chunk: Chunk, translations: dict[str, str]) -> str:
        config = getattr(self.client, "config", None)
        payload = json.dumps(
            {
                "kind": "review",
                "model": getattr(config, "model", "mock"),
                "prompt": self.prompt.version,
                "glossary": self.glossary.fingerprint(),
                "pairs": [[b.id, translations.get(b.id, "")] for b in chunk.blocks],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(self._cache_dir, key[:2], key + ".json")

    def _read_cache(self, key: str):
        try:
            with open(self._cache_path(key), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key: str, blocks: dict[str, str], usage: Usage, applied: int, dropped: int) -> None:
        path = self._cache_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "blocks": blocks,
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens},
            "applied": applied,
            "dropped": dropped,
        }
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass

    def _emit(self, done: int, total: int, cached: int) -> None:
        if self.progress:
            try:
                self.progress(done, total, cached)
            except Exception:
                pass


# ---------------------------------------------------------------------- правки


def _parse_edits(text: str) -> list[dict[str, Any]]:
    from .translate import _extract_json

    try:
        data = _extract_json(text)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    edits = data.get("edits")
    return [e for e in edits if isinstance(e, dict)] if isinstance(edits, list) else []


def _apply_edits(
    chunk: Chunk,
    translations: dict[str, str],
    edits: list[dict[str, Any]],
    max_edits: int,
) -> tuple[dict[str, str], int, int, list[str], dict[str, int]]:
    current = {b.id: translations.get(b.id, b.html) for b in chunk.blocks}
    by_id = {b.id: b for b in chunk.blocks}
    applied = dropped = 0
    reasons: list[str] = []
    by_priority: dict[str, int] = {"critical": 0, "major": 0, "minor": 0}

    edits = sorted(edits, key=lambda e: PRIORITY_ORDER.get(str(e.get("priority", "minor")), 9))
    for edit in edits[:max_edits]:
        block_id = str(edit.get("id") or "")
        find = edit.get("find")
        replace = edit.get("replace")
        block = by_id.get(block_id)
        if not block or not isinstance(find, str) or not isinstance(replace, str):
            dropped += 1
            reasons.append(f"{block_id}: правка без id/find/replace")
            continue
        if not find.strip() or find == replace:
            dropped += 1
            reasons.append(f"{block_id}: пустая правка")
            continue

        html = current[block_id]
        if html.count(find) != 1:
            dropped += 1
            reasons.append(f"{block_id}: фрагмент не найден ровно один раз")
            continue

        candidate = html.replace(find, replace)
        if _tag_issues(block_id, block.html, candidate):
            dropped += 1
            reasons.append(f"{block_id}: правка ломает разметку")
            continue
        if len(candidate) > len(html) * 2 + 200 or len(candidate) < len(html) * 0.5:
            dropped += 1
            reasons.append(f"{block_id}: подозрительный объём после правки")
            continue

        current[block_id] = candidate
        applied += 1
        priority = str(edit.get("priority", "minor"))
        by_priority[priority] = by_priority.get(priority, 0) + 1

    return current, applied, dropped, reasons, by_priority
