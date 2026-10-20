import unittest

from bt.importers.pdf import _is_heading, _lines_to_blocks, _strip_running_lines
from bt.model import Block, Book, Meta, Section


class PdfHeuristicsTest(unittest.TestCase):
    def test_heading_detection(self) -> None:
        self.assertTrue(_is_heading("Chapter 12"))
        self.assertTrue(_is_heading("CHAPTER IV"))
        self.assertTrue(_is_heading("Глава 3"))
        self.assertFalse(_is_heading("It was a dark and stormy night, and the rain kept falling."))
        self.assertFalse(_is_heading(""))

    def test_running_headers_removed(self) -> None:
        pages = []
        for i in range(10):
            pages.append(["THE BOOK TITLE", f"body text of page {i}", "42"])
        cleaned = _strip_running_lines(pages)
        self.assertEqual(cleaned[3][0], "")
        self.assertEqual(cleaned[3][1], "body text of page 3")
        # номера страниц тоже уходят
        self.assertEqual(cleaned[3][2], "")

    def test_short_document_untouched(self) -> None:
        pages = [["Title", "text"], ["Title", "text"]]
        self.assertEqual(_strip_running_lines(pages), pages)

    def test_lines_to_blocks(self) -> None:
        blocks = _lines_to_blocks(
            ["Chapter One", "", "First paragraph here.", "", "Second paragraph follows."], 1
        )
        self.assertEqual(blocks[0].kind, "h2")
        self.assertTrue(all(isinstance(b, Block) for b in blocks))
        self.assertGreaterEqual(len(blocks), 2)


class ModelTest(unittest.TestCase):
    def test_json_roundtrip(self) -> None:
        book = Book(
            meta=Meta(title="T", authors=["A"], language="en"),
            sections=[
                Section(
                    id="s01",
                    kind="chapter",
                    title="One",
                    blocks=[Block(id="s01.b001", kind="p", html="<p>Hi</p>", href="a.xhtml", xpath="/x")],
                )
            ],
            source_format="epub",
        )
        restored = Book.from_dict(book.to_dict())
        self.assertEqual(restored.meta.title, "T")
        self.assertEqual(restored.sections[0].blocks[0].html, "<p>Hi</p>")
        self.assertEqual(restored.sections[0].blocks[0].xpath, "/x")
        self.assertEqual(restored.words, 1)

    def test_assets_roundtrip(self) -> None:
        book = Book()
        book.assets["a.png"] = b"\x00\x01\x02"
        restored = Book.from_dict(book.to_dict(include_assets=True))
        self.assertEqual(restored.assets["a.png"], b"\x00\x01\x02")


if __name__ == "__main__":
    unittest.main()
