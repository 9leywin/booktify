import json
import unittest

from bt.extract import candidates, extract
from bt.glossary import Glossary, Term
from bt.llm import LLMResponse, Usage
from bt.model import Block, Book, Meta, Section


def make_book() -> Book:
    blocks = [
        Block(id="s01.b001", kind="p", html="<p>Corin Cadence opened the door. The room was empty.</p>"),
        Block(id="s01.b002", kind="p", html="<p>Later Corin Cadence met Selys in the hall.</p>"),
        Block(id="s01.b003", kind="p", html="<p>Then Selys smiled, and Corin Cadence bowed.</p>"),
        Block(id="s01.b004", kind="p", html="<p>The attunement glowed. Another attunement appeared.</p>"),
    ]
    return Book(
        meta=Meta(title="Test", authors=["Author"], language="en"),
        sections=[Section(id="s01", kind="chapter", title="One", blocks=blocks)],
    )


class FakeGlossaryClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.user = ""

    def chat(self, system: str, user: str, **_) -> LLMResponse:
        self.user = user
        return LLMResponse(text=json.dumps(self.payload, ensure_ascii=False), usage=Usage(10, 10))


class FlakyGlossaryClient:
    """Первый ответ обрезан, второй (с коротким списком) — нормальный."""

    def __init__(self):
        self.calls = 0
        self.candidate_counts = []

    def chat(self, system: str, user: str, **_) -> LLMResponse:
        self.calls += 1
        self.candidate_counts.append(user.count(" — "))
        if self.calls == 1:
            return LLMResponse(
                text='{"profile": {"genre": "фэнтези"}, "glossary": [{"en": "Corin',
                usage=Usage(1, 1),
            )
        return LLMResponse(
            text=json.dumps({"glossary": [{"en": "Corin Cadence", "ru": "Корин Кейденс"}]},
                            ensure_ascii=False),
            usage=Usage(1, 1),
        )


class GlossaryRobustnessTest(unittest.TestCase):
    def test_retries_after_truncated_answer(self) -> None:
        client = FlakyGlossaryClient()
        result = extract(make_book(), client=client, limit=120)
        self.assertEqual(client.calls, 2)
        self.assertLessEqual(client.candidate_counts[1], client.candidate_counts[0])
        self.assertEqual(len(result.glossary), 1)
        self.assertEqual(result.glossary.terms[0].ru, "Корин Кейденс")

    def test_truncated_json_returns_partial_terms(self) -> None:
        from bt.extract import _extract_json

        text = '{"glossary": [{"en": "Selys", "ru": "Селис"}, {"en": "Cor'
        data = _extract_json(text)
        self.assertEqual(data["glossary"][0]["en"], "Selys")


class CandidatesTest(unittest.TestCase):
    def test_finds_names(self) -> None:
        found = {c.en for c in candidates(make_book(), min_count=2)}
        self.assertIn("Corin Cadence", found)
        self.assertIn("Selys", found)

    def test_skips_sentence_start_and_common(self) -> None:
        found = {c.en for c in candidates(make_book(), min_count=2)}
        self.assertNotIn("The", found)
        self.assertNotIn("Later", found)

    def test_counts(self) -> None:
        found = {c.en: c.count for c in candidates(make_book(), min_count=2)}
        self.assertEqual(found["Selys"], 2)

    def test_limit(self) -> None:
        self.assertLessEqual(len(candidates(make_book(), min_count=1, limit=2)), 2)


class ExtractTest(unittest.TestCase):
    def test_without_client_returns_candidates(self) -> None:
        result = extract(make_book(), client=None)
        self.assertTrue(result.candidates)
        self.assertEqual(len(result.glossary), 0)

    def test_with_client_merges_terms(self) -> None:
        client = FakeGlossaryClient(
            {
                "profile": {"genre": "фэнтези", "pov": "третье лицо"},
                "glossary": [
                    {"en": "Corin Cadence", "ru": "Корин Кейденс", "type": "person", "gender": "m"},
                    {"en": "Selys", "ru": "Селис", "type": "person", "gender": "f"},
                    {"en": "attunement", "ru": "созвучие", "type": "term", "gender": "n"},
                ],
                "uncertain": ["Selys — богиня или город?"],
            }
        )
        result = extract(make_book(), client=client, limit=50)
        self.assertEqual(result.profile["genre"], "фэнтези")
        self.assertEqual(len(result.glossary), 3)
        self.assertEqual(result.glossary.terms[0].ru, "Корин Кейденс")
        self.assertTrue(result.uncertain)
        self.assertIn("Corin Cadence", client.user)

    def test_existing_wins(self) -> None:
        existing = Glossary([Term(en="Selys", ru="Селис (старое)", type="person")])
        client = FakeGlossaryClient(
            {"glossary": [{"en": "Selys", "ru": "Сейлис", "type": "person"}]}
        )
        result = extract(make_book(), client=client, existing=existing)
        terms = {t.en: t.ru for t in result.glossary.terms}
        self.assertEqual(terms["Selys"], "Селис (старое)")

    def test_bad_terms_skipped(self) -> None:
        client = FakeGlossaryClient({"glossary": [{"en": "X"}, {"en": "", "ru": "Y"}]})
        result = extract(make_book(), client=client)
        self.assertEqual(len(result.glossary), 0)


if __name__ == "__main__":
    unittest.main()
