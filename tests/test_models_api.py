import unittest

from bt.models_api import fetch_models, filter_models


class FilterModelsTest(unittest.TestCase):
    def test_drops_service_models(self) -> None:
        models = filter_models([
            "deepseek-flash",
            "text-embedding-3-small",
            "whisper-1",
            "dall-e-3",
            "gpt-4o",
            "gpt-4o-audio-preview",
        ])
        self.assertEqual(models, ["deepseek-flash", "gpt-4o"])

    def test_deduplicates_and_sorts(self) -> None:
        models = filter_models(["b-model", "a-model", "b-model"])
        self.assertEqual(models, ["a-model", "b-model"])

    def test_provider_prefixed_goes_after_plain(self) -> None:
        models = filter_models(["openai/gpt-4o", "gpt-4o-mini"])
        self.assertEqual(models[0], "gpt-4o-mini")


class FetchModelsTest(unittest.TestCase):
    def test_parses_openai_response(self) -> None:
        def transport(url, headers, timeout):
            self.assertTrue(url.endswith("/models"))
            self.assertEqual(headers["Authorization"], "Bearer sk-test")
            return {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}

        models = fetch_models("https://api.openai.com/v1", "sk-test", transport=transport)
        self.assertEqual(models, ["gpt-4o", "gpt-4o-mini"])

    def test_raises_on_bad_key(self) -> None:
        def transport(url, headers, timeout):
            raise PermissionError("ключ не принят")

        with self.assertRaises(PermissionError):
            fetch_models("https://api.deepseek.com", "bad", transport=transport)

    def test_raises_on_empty_list(self) -> None:
        with self.assertRaises(RuntimeError):
            fetch_models("https://x", "k", transport=lambda *a: {"data": []})


if __name__ == "__main__":
    unittest.main()
