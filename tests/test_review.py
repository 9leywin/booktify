import os
import shutil
import unittest
import zipfile

from bt.chunker import Chunk
from bt.epubbuild import build_epub, validate_epub
from bt.importers import import_book
from bt.llm import MockClient, MockReviewer
from bt.model import Block
from bt.review import Reviewer, ReviewOptions, _apply_edits
from bt.translate import TranslationOptions, Translator
from tests import fixtures
from tests.test_importers import work_dir


class ReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"rev_{self.id().rsplit('.', 1)[-1]}")
        self.book = import_book(fixtures.make_fb2(self.dir))
        self.cache = os.path.join(self.dir, "cache")
        self.translator = Translator(
            MockClient(), options=TranslationOptions(jobs=1, cache_dir=self.cache)
        )
        self.translated = self.translator.run(self.book).blocks

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _reviewer(self, client=None) -> Reviewer:
        return Reviewer(
            client or MockReviewer(),
            options=ReviewOptions(jobs=1, cache_dir=self.cache),
        )

    def test_edits_applied(self) -> None:
        result = self._reviewer().run(self.book, self.translated)
        self.assertGreater(result.applied, 0)
        self.assertIn("ГОТОВО:", "\n".join(result.blocks.values()))
        self.assertNotIn("ПЕРЕВОД:", result.blocks[next(iter(result.blocks))])

    def test_cache_on_second_run(self) -> None:
        self._reviewer().run(self.book, self.translated)
        client = MockReviewer()
        second = self._reviewer(client).run(self.book, self.translated)
        self.assertEqual(second.chunks_cached, second.chunks_total)
        self.assertEqual(client.calls, 0)

    def test_result_builds(self) -> None:
        result = self._reviewer().run(self.book, self.translated)
        out = os.path.join(self.dir, "reviewed.epub")
        warnings = build_epub(self.book, out, translations=result.blocks)
        self.assertEqual(validate_epub(out), [], warnings)
        with zipfile.ZipFile(out) as zf:
            body = zf.read("text/s01.xhtml").decode("utf-8")
        self.assertIn("ГОТОВО:", body)


class ApplyEditsTest(unittest.TestCase):
    def _chunk(self, html="<p>ПЕРЕВОД: текст</p>") -> Chunk:
        block = Block(id="s01.b001", kind="p", html="<p>ПЕРЕВОД: текст</p>")
        return Chunk(
            id="s01.c01", section_id="s01", section_title="One", index=1, total=1,
            blocks=[block],
        )

    def test_valid_edit(self) -> None:
        chunk = self._chunk()
        mapping = {"s01.b001": "<p>ПЕРЕВОД: текст</p>"}
        new, applied, dropped, reasons, by_priority = _apply_edits(
            chunk, mapping,
            [{"id": "s01.b001", "find": "ПЕРЕВОД:", "replace": "ГОТОВО:", "priority": "minor"}],
            max_edits=10,
        )
        self.assertEqual(applied, 1)
        self.assertEqual(dropped, 0)
        self.assertIn("ГОТОВО:", new["s01.b001"])
        self.assertEqual(by_priority["minor"], 1)

    def test_missing_find_is_dropped(self) -> None:
        chunk = self._chunk()
        mapping = {"s01.b001": "<p>ПЕРЕВОД: текст</p>"}
        new, applied, dropped, reasons, _ = _apply_edits(
            chunk, mapping, [{"id": "s01.b001", "find": "нет такого", "replace": "x"}], 10
        )
        self.assertEqual(applied, 0)
        self.assertEqual(dropped, 1)
        self.assertTrue(reasons)

    def test_ambiguous_find_is_dropped(self) -> None:
        chunk = self._chunk()
        mapping = {"s01.b001": "<p>a a</p>"}
        new, applied, dropped, reasons, _ = _apply_edits(
            chunk, mapping, [{"id": "s01.b001", "find": "a", "replace": "b"}], 10
        )
        self.assertEqual(applied, 0)
        self.assertIn("ровно один раз", reasons[0])

    def test_markup_breaking_edit_is_dropped(self) -> None:
        chunk = self._chunk()
        mapping = {"s01.b001": "<p>ПЕРЕВОД: текст</p>"}
        new, applied, dropped, reasons, _ = _apply_edits(
            chunk, mapping,
            [{"id": "s01.b001", "find": "<p>ПЕРЕВОД: текст</p>", "replace": "<div>ПЕРЕВОД: текст</div>"}],
            10,
        )
        self.assertEqual(applied, 0)
        self.assertEqual(dropped, 1)

    def test_identical_find_replace_is_dropped(self) -> None:
        chunk = self._chunk()
        mapping = {"s01.b001": "<p>ПЕРЕВОД: текст</p>"}
        _, applied, dropped, _, _ = _apply_edits(
            chunk, mapping, [{"id": "s01.b001", "find": "текст", "replace": "текст"}], 10
        )
        self.assertEqual((applied, dropped), (0, 1))


if __name__ == "__main__":
    unittest.main()
