import re
import unittest

from bt.prompts import PromptError, list_versions, load_prompt

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

#: Ровно то, что подставляет bt.translate.Translator._call.
TRANSLATE_KEYS = {
    "title", "author", "genre", "pov", "tense", "tone", "address", "notes",
    "recap", "prev_en", "prev_ru", "glossary", "forbidden", "chunk_no",
    "chunk_total", "chapter_title", "blocks_html",
}


class PromptTest(unittest.TestCase):
    def test_translate_prompt_loads(self) -> None:
        prompt = load_prompt("translate")
        self.assertEqual(prompt.version, "v1")
        self.assertIn("переводчик", prompt.system.lower())
        self.assertIn("blocks", prompt.system)

    def test_all_placeholders_are_filled(self) -> None:
        prompt = load_prompt("translate")
        used = set(PLACEHOLDER_RE.findall(prompt.user_template))
        self.assertEqual(used, TRANSLATE_KEYS)

        values = {key: "значение" for key in TRANSLATE_KEYS}
        values["blocks_html"] = '<block id="s01.b001"><p>Hello</p></block>'
        system, user = prompt.render(**values)
        self.assertNotIn("{{", user)
        self.assertIn('<block id="s01.b001">', user)
        self.assertTrue(system)

    def test_missing_value_raises(self) -> None:
        prompt = load_prompt("translate")
        with self.assertRaises(PromptError):
            prompt.render(title="x")

    def test_versions(self) -> None:
        self.assertIn("1", list_versions("translate"))
        self.assertIn("1", list_versions("review"))
        self.assertIn("1", list_versions("glossary"))

    def test_review_prompt_placeholders(self) -> None:
        prompt = load_prompt("review")
        used = set(PLACEHOLDER_RE.findall(prompt.user_template))
        expected = {"title", "author", "genre", "pov", "tense", "tone", "chapter", "glossary", "pairs"}
        self.assertEqual(used, expected)
        _, user = prompt.render(**{key: "x" for key in expected})
        self.assertIn("x", user)

    def test_user_section_has_no_code_fence(self) -> None:
        prompt = load_prompt("translate")
        self.assertFalse(prompt.user_template.strip().startswith("```"))
        self.assertNotIn("```", prompt.user_template)


if __name__ == "__main__":
    unittest.main()
