import os
import shutil
import unittest

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:  # pragma: no cover - зависит от окружения
    HAS_PYPDF = False

from bt.epubbuild import build_epub, validate_epub
from bt.importers.pdf import import_pdf
from bt.llm import MockClient
from bt.translate import TranslationOptions, Translator
from tests.test_importers import work_dir

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PDF = os.path.join(DATA, "demo_book.pdf")


@unittest.skipUnless(HAS_PYPDF, "pypdf не установлен")
class PdfImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.book = import_pdf(PDF)

    def test_sections_found(self) -> None:
        self.assertEqual(len(self.book.sections), 3)
        self.assertEqual([s.title for s in self.book.sections], ["Chapter 1", "Chapter 2", "Chapter 3"])

    def test_paragraphs_and_headings(self) -> None:
        first = self.book.sections[0]
        self.assertEqual(first.blocks[0].kind, "h2")
        self.assertEqual(len([b for b in first.blocks if b.kind == "p"]), 3)

    def test_running_heads_and_page_numbers_dropped(self) -> None:
        text = " ".join(b.text for s in self.book.sections for b in s.blocks)
        self.assertNotIn("A Short Book About Testing", text)
        self.assertNotRegex(text, r"\b\d+ of 3\b")

    def test_metadata(self) -> None:
        self.assertEqual(self.book.meta.title, "A Short Book About Testing")
        self.assertEqual(self.book.meta.authors, ["Demo Author"])

    def test_full_pipeline_to_epub(self) -> None:
        directory = work_dir("pdf_flow")
        try:
            translator = Translator(
                MockClient(), options=TranslationOptions(jobs=1, cache_dir=os.path.join(directory, "cache"))
            )
            result = translator.run(self.book)
            out = os.path.join(directory, "ru.epub")
            warnings = build_epub(self.book, out, translations=result.blocks)
            self.assertEqual(validate_epub(out), [], warnings)
            self.assertEqual(result.chunks_failed, 0)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


@unittest.skipUnless(HAS_PYPDF, "pypdf не установлен")
class PdfScanTest(unittest.TestCase):
    def test_scan_is_rejected(self) -> None:
        from PIL import Image

        directory = work_dir("pdf_scan")
        path = os.path.join(directory, "scan.pdf")
        try:
            Image.new("RGB", (600, 800), "white").save(path, "PDF")
            with self.assertRaises(ValueError) as ctx:
                import_pdf(path)
            self.assertIn("скан", str(ctx.exception))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
