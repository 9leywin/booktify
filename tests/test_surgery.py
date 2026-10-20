import os
import shutil
import unittest
import zipfile

from bt.epubbuild import validate_epub
from bt.importers import import_book
from bt.llm import MockClient
from bt.surgery import build_epub_surgery
from bt.translate import TranslationOptions, Translator
from tests import fixtures
from tests.test_importers import work_dir


class SurgeryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"surg_{self.id().rsplit('.', 1)[-1]}")
        self.src = fixtures.make_epub(self.dir)
        self.book = import_book(self.src)
        self.out = os.path.join(self.dir, "ru.epub")
        self.translations = {
            block.id: self._mark(block.html)
            for section in self.book.sections
            for block in section.blocks
            if block.text.strip()
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def _mark(html: str) -> str:
        if html.startswith("<p"):
            return html.replace(">", ">ПЕРЕВОД: ", 1)
        return html

    def test_output_is_valid(self) -> None:
        warnings = build_epub_surgery(self.book, self.src, self.out, self.translations)
        self.assertEqual(validate_epub(self.out), [], warnings)

    def test_text_replaced(self) -> None:
        build_epub_surgery(self.book, self.src, self.out, self.translations)
        with zipfile.ZipFile(self.out) as zf:
            body = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
        self.assertIn("ПЕРЕВОД:", body)
        self.assertIn("<em>world</em>", body)

    def test_structure_and_assets_untouched(self) -> None:
        with zipfile.ZipFile(self.src) as src:
            css_before = src.read("OEBPS/styles/style.css")
            img_before = src.read("OEBPS/images/cover.jpg")
        build_epub_surgery(self.book, self.src, self.out, self.translations)
        with zipfile.ZipFile(self.out) as zf:
            self.assertEqual(zf.read("OEBPS/styles/style.css"), css_before)
            self.assertEqual(zf.read("OEBPS/images/cover.jpg"), img_before)
            self.assertIn("OEBPS/nav.xhtml", zf.namelist())
            self.assertIn("META-INF/container.xml", zf.namelist())

    def test_attributes_preserved(self) -> None:
        build_epub_surgery(self.book, self.src, self.out, self.translations)
        with zipfile.ZipFile(self.out) as zf:
            body = zf.read("OEBPS/ch1.xhtml").decode("utf-8")
        self.assertIn('class="intro"', body)

    def test_language_updated(self) -> None:
        build_epub_surgery(self.book, self.src, self.out, self.translations)
        with zipfile.ZipFile(self.out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        self.assertIn("<dc:language>ru</dc:language>", opf)
        self.assertIn("<dc:title>Test Book</dc:title>", opf)

    def test_mimetype_first_and_stored(self) -> None:
        build_epub_surgery(self.book, self.src, self.out, self.translations)
        with zipfile.ZipFile(self.out) as zf:
            first = zf.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)

    def test_works_with_translator(self) -> None:
        translator = Translator(
            MockClient(), options=TranslationOptions(jobs=1, cache_dir=os.path.join(self.dir, "cache"))
        )
        result = translator.run(self.book)
        build_epub_surgery(self.book, self.src, self.out, result.blocks)
        self.assertEqual(validate_epub(self.out), [])
        # Оглавление тоже должно стать русским: подписи берутся из переведённых заголовков.
        with zipfile.ZipFile(self.out) as zf:
            nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        self.assertIn("ПЕРЕВОД:", nav)

    def test_nav_titles_from_translated_headings(self) -> None:
        mapping = dict(self.translations)
        for section in self.book.sections:
            for block in section.blocks:
                if block.kind in ("h1", "h2"):
                    mapping[block.id] = f"<h2>Глава: {block.text}</h2>"
        build_epub_surgery(self.book, self.src, self.out, mapping)
        with zipfile.ZipFile(self.out) as zf:
            nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        self.assertIn("Глава: Chapter One", nav)
        self.assertIn("Глава: Chapter Two", nav)


if __name__ == "__main__":
    unittest.main()
