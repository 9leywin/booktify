import json
import unittest
from unittest import mock

from bt.llm import (
    LLMClient,
    LLMConfig,
    LLMPermanent,
    LLMRetryable,
    MockClient,
    Usage,
    _parse_response,
)
from bt.translate import _extract_json, _parse_blocks


def _payload(text: str, prompt: int = 10, completion: int = 20) -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class MockClientTest(unittest.TestCase):
    def test_marks_every_block(self) -> None:
        client = MockClient(marker="RU: ")
        user = '<block id="a1"><p>Hello</p></block>\n<block id="a2"><h2>Title</h2></block>'
        response = client.chat("system", user)
        data = json.loads(response.text)
        self.assertEqual([b["id"] for b in data["blocks"]], ["a1", "a2"])
        self.assertIn("RU: Hello", data["blocks"][0]["ru"])
        self.assertTrue(data["blocks"][1]["ru"].startswith("<h2"))

    def test_can_fail_first(self) -> None:
        client = MockClient(fail_first=1)
        with self.assertRaises(LLMRetryable):
            client.chat("s", '<block id="a"><p>x</p></block>')
        self.assertIn("blocks", client.chat("s", '<block id="a"><p>x</p></block>').text)


class RetryTest(unittest.TestCase):
    def test_retries_transient_errors(self) -> None:
        calls = {"n": 0}

        def transport(url, headers, payload, timeout):
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMRetryable("перегрузка")
            return _payload('{"blocks": []}')

        config = LLMConfig(api_key="k", retries=3, timeout=1)
        client = LLMClient(config, transport=transport)
        with mock.patch("bt.llm.time.sleep"):
            response = client.chat("s", "u")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(response.text, '{"blocks": []}')

    def test_permanent_error_not_retried(self) -> None:
        calls = {"n": 0}

        def transport(url, headers, payload, timeout):
            calls["n"] += 1
            raise LLMPermanent("неверный ключ")

        client = LLMClient(LLMConfig(api_key="k", retries=3), transport=transport)
        with self.assertRaises(LLMPermanent):
            client.chat("s", "u")
        self.assertEqual(calls["n"], 1)

    def test_no_key(self) -> None:
        client = LLMClient(LLMConfig(api_key=""))
        with self.assertRaises(LLMPermanent):
            client.chat("s", "u")

    def test_usage_and_cost(self) -> None:
        usage = Usage(prompt_tokens=1_000_000, completion_tokens=0)
        self.assertAlmostEqual(usage.cost("deepseek-flash"), 0.30, places=4)
        usage.add(Usage(prompt_tokens=0, completion_tokens=1_000_000))
        self.assertAlmostEqual(usage.cost("deepseek-flash"), 1.50, places=4)

    def test_parse_response_error(self) -> None:
        with self.assertRaises(LLMPermanent):
            _parse_response({"error": {"message": "bad key"}})


class ThinkingModeTest(unittest.TestCase):
    def _payload_for(self, base_url: str) -> dict:
        captured = {}

        def transport(url, headers, payload, timeout):
            captured.update(payload)
            return _payload('{"blocks": []}')

        client = LLMClient(LLMConfig(api_key="k", base_url=base_url), transport=transport)
        client.chat("s", "u")
        return captured

    def test_thinking_disabled_for_deepseek(self) -> None:
        payload = self._payload_for("https://api.deepseek.com")
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})

    def test_thinking_flag_not_sent_to_other_providers(self) -> None:
        payload = self._payload_for("https://api.openai.com/v1")
        self.assertNotIn("thinking", payload)


class ParsingTest(unittest.TestCase):
    def test_fenced_json(self) -> None:
        text = '```json\n{"blocks": [{"id": "a", "ru": "<p>Привет</p>"}]}\n```'
        blocks = _parse_blocks(text)
        self.assertEqual(blocks, [{"id": "a", "ru": "<p>Привет</p>"}])

    def test_trailing_comma(self) -> None:
        text = '{"blocks": [{"id": "a", "ru": "<p>x</p>"},],}'
        self.assertEqual(_parse_blocks(text)[0]["id"], "a")

    def test_plain_mapping(self) -> None:
        blocks = _parse_blocks('{"a": "<p>x</p>", "b": "<p>y</p>"}')
        self.assertEqual(len(blocks), 2)

    def test_garbage(self) -> None:
        with self.assertRaises(ValueError):
            _parse_blocks("совсем не json")
        with self.assertRaises(ValueError):
            _extract_json("")


if __name__ == "__main__":
    unittest.main()
