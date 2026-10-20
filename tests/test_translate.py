import os
import shutil
import unittest
import zipfile

from bt.epubbuild import build_epub, validate_epub
from bt.glossary import Glossary, Term
from bt.importers import import_book
from bt.llm import MockClient
from bt.translate import TranslationOptions, Translator
from tests import fixtures
from tests.test_importers import work_dir


class TranslatePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"tr_{self.id().rsplit('.', 1)[-1]}")
        self.book = import_book(fixtures.make_fb2(self.dir))
        self.cache = os.path.join(self.dir, "cache")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _translator(self, client=None, glossary=None, **kwargs) -> Translator:
        options = TranslationOptions(jobs=2, cache_dir=self.cache, **kwargs)
        return Translator(client or MockClient(), glossary=glossary, options=options)

    def test_full_book_translated(self) -> None:
        result = self._translator().run(self.book)
        self.assertGreater(result.chunks_total, 0)
        self.assertEqual(result.chunks_failed, 0)
        for section in self.book.sections:
            for block in section.blocks:
                self.assertIn(block.id, result.blocks)
                if block.kind == "p":
                    self.assertIn("ПЕРЕВОД:", result.blocks[block.id])
        critical = [i for i in result.issues if i.severity == "critical"]
        self.assertEqual(critical, [])

    def test_second_run_uses_cache(self) -> None:
        first_client = MockClient()
        first = self._translator(first_client).run(self.book)
        self.assertEqual(first.chunks_cached, 0)

        second_client = MockClient()
        second = self._translator(second_client).run(self.book)
        self.assertEqual(second.chunks_cached, second.chunks_total)
        self.assertEqual(second_client.calls, 0)
        self.assertEqual(first.blocks, second.blocks)

    def test_limit(self) -> None:
        result = self._translator().run(self.book, limit=1)
        self.assertEqual(result.chunks_total, 1)
        self.assertEqual(result.chunks_done, 1)

    def test_build_from_translations(self) -> None:
        result = self._translator().run(self.book)
        out = os.path.join(self.dir, "ru.epub")
        warnings = build_epub(self.book, out, translations=result.blocks)
        self.assertEqual(validate_epub(out), [], warnings)
        with zipfile.ZipFile(out) as zf:
            body = zf.read("text/s01.xhtml").decode("utf-8")
        self.assertIn("ПЕРЕВОД:", body)

    def test_glossary_violation_is_reported(self) -> None:
        # «paragraph» точно есть в теле главы, а мок-перевод его не заменяет на «абзац».
        glossary = Glossary([Term(en="paragraph", ru="абзац", type="term")])
        result = self._translator(glossary=glossary).run(self.book)
        codes = {i.code for i in result.issues}
        self.assertIn("glossary", codes)


if __name__ == "__main__":
    unittest.main()
