import os
import shutil
import unittest
import zipfile

from bt.epubbuild import build_epub, validate_epub
from bt.importers import import_book
from tests.test_importers import work_dir
from tests import fixtures


class EpubBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"build_{self.id().rsplit('.', 1)[-1]}")
        self.src = fixtures.make_fb2(self.dir)
        self.book = import_book(self.src)
        self.out = os.path.join(self.dir, "out.epub")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_build_is_valid(self) -> None:
        warnings = build_epub(self.book, self.out)
        self.assertTrue(os.path.exists(self.out))
        self.assertEqual(validate_epub(self.out), [], warnings)

    def test_text_inside(self) -> None:
        build_epub(self.book, self.out)
        with zipfile.ZipFile(self.out) as zf:
            text = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xhtml")).decode("utf-8")
        self.assertIn("First paragraph of the book", text)
        self.assertIn("Chapter One", text)

    def test_cover_and_nav(self) -> None:
        build_epub(self.book, self.out)
        with zipfile.ZipFile(self.out) as zf:
            nav = zf.read("nav.xhtml").decode("utf-8")
            names = zf.namelist()
        self.assertIn("Chapter One", nav)
        self.assertTrue(any(n.startswith("images/cover") for n in names))

    def test_translations_applied(self) -> None:
        section = next(s for s in self.book.sections if s.title == "Chapter One")
        target = section.blocks[0] if section.blocks[0].kind == "p" else section.blocks[1]
        build_epub(self.book, self.out, translations={target.id: "<p>ПЕРЕВОД.</p>"})
        with zipfile.ZipFile(self.out) as zf:
            body = zf.read("text/s01.xhtml").decode("utf-8")
        self.assertIn("ПЕРЕВОД.", body)

    def test_bare_text_wrapped(self) -> None:
        section = next(s for s in self.book.sections if s.title == "Chapter One")
        target = section.blocks[1]
        build_epub(self.book, self.out, translations={target.id: "Просто текст перевода"})
        with zipfile.ZipFile(self.out) as zf:
            body = zf.read("text/s01.xhtml").decode("utf-8")
        self.assertIn("<p>Просто текст перевода</p>", body)

    def test_epigraph_not_double_wrapped(self) -> None:
        build_epub(self.book, self.out)
        with zipfile.ZipFile(self.out) as zf:
            body = zf.read("text/s01.xhtml").decode("utf-8")
        self.assertEqual(body.count("<blockquote"), 1)


if __name__ == "__main__":
    unittest.main()
