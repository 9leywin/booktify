import json
import os
import re
import shutil
import unittest

from bt.chunker import Chunk
from bt.importers import import_book
from bt.llm import LLMResponse, MockClient, Usage
from bt.model import Block
from bt.translate import (
    TranslationOptions,
    Translator,
    _looks_untranslated,
    _parse_blocks_lenient,
)
from tests import fixtures
from tests.test_importers import work_dir


class TruncatingClient:
    """Обрезает ответ, если блоков больше трёх: проверяем дробление фрагмента."""

    def __init__(self, limit: int = 3):
        self.limit = limit
        self.calls = 0

    def chat(self, system: str, user: str, **kwargs) -> LLMResponse:
        self.calls += 1
        ids = re.findall(r'<block id="([^"]+)">', user)
        keep = ids[: self.limit]
        blocks = [{"id": i, "ru": f"<p>Перевод {i}</p>"} for i in keep]
        text = json.dumps({"blocks": blocks}, ensure_ascii=False)
        if len(ids) > self.limit:
            text = text[:-1]  # обрыв JSON
        return LLMResponse(text=text, usage=Usage(10, 10), finish_reason="length")


class EnglishClient:
    """Возвращает исходный английский текст — проверяем отбраковку."""

    def chat(self, system: str, user: str, **kwargs) -> LLMResponse:
        ids = re.findall(r'<block id="([^"]+)">', user)
        blocks = [{"id": i, "ru": "<p>This is still English text.</p>"} for i in ids]
        return LLMResponse(text=json.dumps({"blocks": blocks}), usage=Usage(1, 1))


class LenientParseTest(unittest.TestCase):
    def test_salvages_complete_blocks(self) -> None:
        text = '{"blocks": [{"id": "a", "ru": "<p>Раз</p>"}, {"id": "b", "ru": "<p>Два</p>"}'
        blocks, complete = _parse_blocks_lenient(text)
        self.assertFalse(complete)
        self.assertEqual(blocks, {"a": "<p>Раз</p>", "b": "<p>Два</p>"})

    def test_complete_json(self) -> None:
        text = '{"blocks": [{"id": "a", "ru": "<p>Раз</p>"}]}'
        blocks, complete = _parse_blocks_lenient(text)
        self.assertTrue(complete)

    def test_untranslated_detection(self) -> None:
        self.assertTrue(_looks_untranslated("<p>Hello world, how are you?</p>", "<p>Hello world, how are you?</p>"))
        self.assertFalse(_looks_untranslated("<p>Hello world, how are you?</p>", "<p>Привет, как дела?</p>"))
        self.assertFalse(_looks_untranslated("<p>Hi</p>", "<p>Hi</p>"))


class ResilienceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"res_{self.id().rsplit('.', 1)[-1]}")
        self.book = import_book(fixtures.make_fb2(self.dir))
        self.cache = os.path.join(self.dir, "cache")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _translator(self, client) -> Translator:
        return Translator(
            client,
            options=TranslationOptions(jobs=1, cache_dir=self.cache, max_words=600, min_words=100),
        )

    def test_truncated_response_is_split(self) -> None:
        client = TruncatingClient(limit=2)
        result = self._translator(client).run(self.book)
        self.assertEqual(result.chunks_failed, 0)
        self.assertGreater(client.calls, result.chunks_total)
        for html in result.blocks.values():
            if html.strip():
                self.assertIn("Перевод", html)

    def test_english_output_is_rejected_and_retried(self) -> None:
        result = self._translator(EnglishClient()).run(self.book)
        self.assertGreater(result.chunks_failed, 0)
        self.assertTrue(any(i.code == "chunk_failed" or i.severity == "critical" for i in result.issues))

    def test_failed_chunks_are_cached_for_retry(self) -> None:
        first = self._translator(EnglishClient()).run(self.book)
        self.assertGreater(first.chunks_failed, 0)

        second = self._translator(MockClient()).run(self.book)
        self.assertEqual(second.chunks_failed, 0)
        self.assertGreater(second.chunks_cached, 0)


class BlockSubsetTest(unittest.TestCase):
    def test_chunk_accepts_subset(self) -> None:
        block = Block(id="s01.b001", kind="p", html="<p>Hello world</p>")
        chunk = Chunk(id="s01.c01", section_id="s01", section_title="One",
                      index=1, total=1, blocks=[block])
        self.assertEqual(chunk.blocks[0].id, "s01.b001")


if __name__ == "__main__":
    unittest.main()
