import os
import shutil
import unittest

from bt.importers import import_book
from tests import fixtures

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_work")


def work_dir(name: str) -> str:
    """Каталог под фикстуру.

    `tempfile.mkdtemp` создаёт каталог с правами 0700, а песочница не даёт в него
    писать; `os.makedirs` с обычными правами работает.
    """
    path = os.path.join(WORK, name)
    os.makedirs(path, exist_ok=True)
    return path


class EpubImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_name = self.id().rsplit(".", 1)[-1]
        self.dir = work_dir(f"epub_{self.tmp_name}")
        self.path = fixtures.make_epub(self.dir)
        self.book = import_book(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_metadata(self) -> None:
        meta = self.book.meta
        self.assertEqual(meta.title, "Test Book")
        self.assertEqual(meta.authors, ["Jane Doe"])
        self.assertEqual(meta.language, "en")
        self.assertTrue(meta.cover_href and meta.cover_href.endswith("cover.jpg"))

    def test_spine_and_nav(self) -> None:
        # nav-документ не должен попасть в перевод
        hrefs = [s.href for s in self.book.sections]
        self.assertNotIn("OEBPS/nav.xhtml", hrefs)
        self.assertEqual(len(self.book.sections), 3)

    def test_kinds(self) -> None:
        kinds = [s.kind for s in self.book.sections]
        self.assertEqual(kinds, ["frontmatter", "chapter", "chapter"])

    def test_blocks_keep_inline_markup(self) -> None:
        ch1 = self.book.sections[1]
        html = "\n".join(b.html for b in ch1.blocks)
        self.assertIn("<em>world</em>", html)
        self.assertIn("<strong>bold text</strong>", html)
        self.assertIn("noteref", html)
        # Цитата сохраняет тип блока; обёртку <blockquote> собирает EPUB-сборщик.
        self.assertEqual([b.kind for b in ch1.blocks].count("quote"), 1)

    def test_block_structure(self) -> None:
        ch1 = self.book.sections[1]
        kinds = [b.kind for b in ch1.blocks]
        self.assertEqual(kinds[0], "h1")
        self.assertIn("quote", kinds)
        self.assertEqual(kinds.count("li"), 2)
        self.assertEqual(kinds[-1], "hr")

    def test_assets(self) -> None:
        self.assertIn("OEBPS/images/cover.jpg", self.book.assets)
        self.assertIn("OEBPS/styles/style.css", self.book.assets)

    def test_surgery_refs(self) -> None:
        for block in self.book.sections[1].blocks:
            self.assertEqual(block.href, "OEBPS/ch1.xhtml")
            self.assertTrue(block.xpath and block.xpath.startswith("/"))

    def test_words_counted(self) -> None:
        self.assertGreater(self.book.words, 30)
        self.assertGreater(len(self.book.sections[1].blocks), 4)

    def test_block_html_has_no_tail(self) -> None:
        # Хвост элемента (`\n  ` между абзацами) не должен попадать в блок:
        # иначе он уезжает в промпт и ломает разбор ответа модели.
        for section in self.book.sections:
            for block in section.blocks:
                self.assertEqual(block.html, block.html.strip())
                self.assertFalse(block.html.endswith("\n"))


class Fb2ImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_name = self.id().rsplit(".", 1)[-1]
        self.dir = work_dir(f"fb2_{self.tmp_name}")
        self.path = fixtures.make_fb2(self.dir)
        self.book = import_book(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_metadata(self) -> None:
        self.assertEqual(self.book.meta.title, "Test FB2")
        self.assertEqual(self.book.meta.authors, ["Ivan Petrov"])
        self.assertEqual(self.book.meta.language, "en")

    def test_sections_and_notes(self) -> None:
        kinds = [s.kind for s in self.book.sections]
        self.assertEqual(kinds[:2], ["chapter", "chapter"])
        self.assertEqual(kinds[-1], "notes")
        titles = [s.title for s in self.book.sections]
        self.assertIn("Chapter One", titles)
        self.assertIn("Subsection", titles)

    def test_epigraph_and_poem(self) -> None:
        ch1 = self.book.sections[0]
        html = "\n".join(b.html for b in ch1.blocks)
        self.assertIn("epigraph", html)
        self.assertIn("<em>emphasis</em>", html)

        ch2 = next(s for s in self.book.sections if s.title == "Chapter Two")
        poem = "\n".join(b.html for b in ch2.blocks)
        self.assertIn("poem", poem)
        self.assertIn("First line", poem)

    def test_images(self) -> None:
        self.assertTrue(any(k.startswith("images/") for k in self.book.assets))
        self.assertTrue(self.book.meta.cover_href)


if __name__ == "__main__":
    unittest.main()
