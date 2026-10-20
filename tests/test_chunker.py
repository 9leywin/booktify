import unittest

from bt.chunker import chunk_stats, make_chunks
from bt.model import Block, Book, Meta, Section, count_words, strip_tags
from tests import fixtures


class ChunkerTest(unittest.TestCase):
    def test_splits_by_word_limit(self) -> None:
        book = fixtures.make_book(block_count=10, words_per_block=100)
        chunks = make_chunks(book, max_words=300, min_words=100)
        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(c.words <= 300 for c in chunks))
        self.assertEqual([b.id for c in chunks for b in c.blocks], [b.id for b in book.sections[0].blocks])

    def test_tail_goes_to_next_chunk(self) -> None:
        book = fixtures.make_book(block_count=6, words_per_block=100)
        chunks = make_chunks(book, max_words=200, min_words=100)
        self.assertEqual(chunks[0].prev_blocks, [])
        self.assertTrue(chunks[1].prev_blocks)
        # хвост — последние два блока предыдущего фрагмента
        self.assertEqual(
            [b.id for b in chunks[1].prev_blocks],
            [b.id for b in chunks[0].blocks[-2:]],
        )

    def test_tiny_last_chunk_is_merged(self) -> None:
        book = fixtures.make_book(block_count=5, words_per_block=100)
        chunks = make_chunks(book, max_words=400, min_words=300)
        self.assertEqual(len(chunks), 1)

    def test_paragraph_never_split(self) -> None:
        blocks = [
            Block(id=f"s01.b{i:03d}", kind="p", html="<p>" + "x " * n + "</p>")
            for i, n in enumerate([50, 2000, 50], start=1)
        ]
        book = Book(sections=[Section(id="s01", kind="chapter", title="One", blocks=blocks)])
        chunks = make_chunks(book, max_words=300, min_words=100)
        # огромный абзац целиком лежит ровно в одном фрагменте
        big = [c for c in chunks if any(b.id == "s01.b002" for b in c.blocks)]
        self.assertEqual(len(big), 1)
        self.assertEqual([b.id for b in big[0].blocks if b.id == "s01.b002"], ["s01.b002"])
        self.assertEqual(len(big[0].blocks), 1)

    def test_frontmatter_not_translated(self) -> None:
        book = fixtures.make_book(3, 50)
        book.sections.insert(
            0,
            Section(id="s00", kind="frontmatter", title="Title",
                    blocks=[Block(id="s00.b001", kind="h1", html="<h1>Title</h1>")]),
        )
        chunks = make_chunks(book)
        self.assertTrue(all(c.section_id != "s00" for c in chunks))

    def test_stats(self) -> None:
        book = fixtures.make_book(4, 100)
        stats = chunk_stats(make_chunks(book, max_words=300, min_words=100))
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["words"], 400)
        self.assertEqual(stats["max"], 300)


class TextUtilsTest(unittest.TestCase):
    def test_strip_tags(self) -> None:
        self.assertEqual(strip_tags("<p>Hello <em>big</em> world&nbsp;!</p>"), "Hello big world !")

    def test_count_words(self) -> None:
        self.assertEqual(count_words("<p>one two three</p>"), 3)
        self.assertEqual(count_words(""), 0)


if __name__ == "__main__":
    unittest.main()
