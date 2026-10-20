import os
import shutil
import unittest

from bt.glossary import Glossary, Term
from tests.test_importers import work_dir

MD = """# Глоссарий

## Имена
| Оригинал | Русский | Примечание |
|---|---|---|
| Corin Cadence | Корин Кейденс | рассказчик |
| Selys | Селис | богиня |

## Термины
| Оригинал | Русский | Примечание |
|---|---|---|
| attunement | созвучие | ключевой термин |
"""


class GlossaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"gloss_{self.id().rsplit('.', 1)[-1]}")
        self.path = os.path.join(self.dir, "glossary.md")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(MD)
        self.glossary = Glossary.from_markdown(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_markdown_parsing(self) -> None:
        self.assertEqual(len(self.glossary), 3)
        corin = next(t for t in self.glossary.terms if t.en == "Corin Cadence")
        self.assertEqual(corin.ru, "Корин Кейденс")
        self.assertIn("рассказчик", corin.note)

    def test_match_is_case_insensitive_and_word_bound(self) -> None:
        found = self.glossary.match("CORIN CADENCE entered. attunements were new.")
        names = [t.en for t in found]
        self.assertIn("Corin Cadence", names)
        # «attunements» — другая словоформа, точного вхождения нет
        self.assertNotIn("attunement", names)

    def test_render(self) -> None:
        text = self.glossary.render(self.glossary.terms)
        self.assertIn("Corin Cadence → Корин Кейденс", text)
        self.assertIn("attunement → созвучие", text)

    def test_violations(self) -> None:
        problems = self.glossary.violations(
            "Corin Cadence looked at the attunement.",
            "Корин взглянул на созвучие.",
        )
        self.assertEqual(problems, [])

        problems = self.glossary.violations(
            "Corin Cadence looked at the attunement.",
            "Корин взглянул на энчантмент.",
        )
        self.assertTrue(any("созвучие" in p for p in problems))

    def test_forbidden_variant(self) -> None:
        glossary = Glossary([Term(en="Mender", ru="Целитель", forbidden=["Менди"])])
        problems = glossary.violations("The Mender arrived.", "Менди пришёл.")
        self.assertTrue(any("запрещённый" in p for p in problems))

    def test_fingerprint_changes(self) -> None:
        before = self.glossary.fingerprint()
        self.glossary.add(Term(en="new", ru="новый"))
        self.assertNotEqual(before, self.glossary.fingerprint())

    def test_json_roundtrip(self) -> None:
        out = os.path.join(self.dir, "glossary.json")
        self.glossary.save_json(out)
        restored = Glossary.from_json(out)
        self.assertEqual(len(restored), len(self.glossary))
        self.assertEqual(restored.terms[0].ru, self.glossary.terms[0].ru)


if __name__ == "__main__":
    unittest.main()
