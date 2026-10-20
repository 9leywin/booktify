"""Клиент LLM: OpenAI-совместимый `/chat/completions` без SDK.

Своя реализация на `urllib` — чтобы не тащить в приложение зависимости и чтобы
любой провайдер с тем же форматом (DeepSeek, OpenRouter, LM Studio, Ollama)
подключался одной строкой адреса.

Транспорт подменяется: в тестах и в режиме «без сети» работает мок, а не HTTP.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]

#: Тарифы за 1M токенов (вход, выход), USD. Пик/непик DeepSeek отличается вдвое.
PRICES: dict[str, tuple[float, float]] = {
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


class LLMError(Exception):
    """Общая ошибка вызова модели."""


class LLMRetryable(LLMError):
    """Временная ошибка: лимит, перегрузка, обрыв сети."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMPermanent(LLMError):
    """Повторять бессмысленно: неверный ключ, нет модели, некорректный запрос."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens

    def cost(self, model: str) -> float:
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        return (self.prompt_tokens * price_in + self.completion_tokens * price_out) / 1_000_000


@dataclass
class LLMResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str = ""


@dataclass
class LLMConfig:
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-flash"
    temperature: float = 0.4
    top_p: float = 0.95
    max_tokens: int = 8192
    timeout: float = 180.0
    retries: int = 4
    json_mode: bool = True
    #: DeepSeek по умолчанию думает перед ответом: reasoning-токены оплачиваются
    #: как выходные и утраивают счёт. Для перевода размышления не нужны.
    thinking: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)


class LLMClient:
    """Боевой клиент. `transport` можно подменить для тестов."""

    def __init__(self, config: LLMConfig, transport: Transport | None = None):
        self.config = config
        self._transport = transport or _http_transport

    def chat(self, system: str, user: str, *, temperature: float | None = None,
             max_tokens: int | None = None) -> LLMResponse:
        if not self.config.api_key:
            raise LLMPermanent("не задан ключ доступа к модели")

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature if temperature is None else temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if self.config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if "deepseek.com" in self.config.base_url and not self.config.thinking:
            # Явно выключаем chain-of-thought: иначе модель «думает» на каждом
            # фрагменте, платим за это как за выходные токены и ждём втрое дольше.
            payload["thinking"] = {"type": "disabled"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        headers.update(self.config.extra_headers)

        last: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                data = self._transport(url, headers, payload, self.config.timeout)
                return _parse_response(data)
            except LLMRetryable as exc:
                last = exc
                if attempt >= self.config.retries:
                    break
                delay = exc.retry_after if exc.retry_after else min(30.0, 2.0 ** (attempt + 1))
                time.sleep(delay)
            except LLMPermanent:
                raise

        raise LLMError(f"модель не ответила после {self.config.retries + 1} попыток: {last}")


def _http_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        message = f"HTTP {exc.code}: {detail or exc.reason}"
        if exc.code in (408, 409, 425, 429) or 500 <= exc.code < 600:
            retry_after = None
            try:
                retry_after = float(exc.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                pass
            raise LLMRetryable(message, retry_after) from exc
        raise LLMPermanent(message) from exc
    except urllib.error.URLError as exc:
        raise LLMRetryable(f"сеть: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMRetryable("таймаут запроса") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMRetryable(f"ответ не JSON: {raw[:300]}") from exc


def _parse_response(data: dict[str, Any]) -> LLMResponse:
    choices = data.get("choices") or []
    if not choices:
        error = data.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        if message:
            raise LLMPermanent(f"модель вернула ошибку: {message}")
        raise LLMRetryable(f"пустой ответ модели: {str(data)[:300]}")

    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    finish = choices[0].get("finish_reason") or ""
    if not text.strip():
        raise LLMRetryable(f"модель вернула пустой текст (finish_reason={finish})")

    usage = data.get("usage") or {}
    return LLMResponse(
        text=text,
        usage=Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        ),
        raw=data,
        finish_reason=finish,
    )


# --------------------------------------------------------------------- мок-модель

BLOCK_RE = re.compile(r'<block id="([^"]+)">(.*?)</block>', re.S)


class MockClient:
    """Детерминированная «модель» для тестов и демонстрации конвейера без сети.

    Ничего не переводит: помечает текст внутри каждого блока. Этого достаточно,
    чтобы проверить разбор ответа, валидацию, кэш, сборку EPUB и прогресс.
    """

    def __init__(self, marker: str = "ПЕРЕВОД: ", fail_first: int = 0):
        self.marker = marker
        self.fail_first = fail_first
        self.calls = 0

    def chat(self, system: str, user: str, **_: Any) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise LLMRetryable("мок: временная ошибка")

        blocks = BLOCK_RE.findall(user)
        out = {}
        for block_id, html in blocks:
            out[block_id] = _mark(html, self.marker)

        text = json.dumps(
            {"blocks": [{"id": k, "ru": v} for k, v in out.items()], "new_terms": [], "uncertain": []},
            ensure_ascii=False,
        )
        return LLMResponse(
            text=text,
            usage=Usage(prompt_tokens=len(user) // 4, completion_tokens=len(text) // 4),
        )


VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source"}


def _mark(html: str, marker: str) -> str:
    stripped = html.strip()
    match = re.match(r"\s*<([a-zA-Z0-9]+)([^>]*)>", stripped)
    if not match:
        return marker + stripped
    tag, attrs = match.group(1), match.group(2)
    if tag.lower() in VOID_TAGS or attrs.rstrip().endswith("/"):
        return stripped
    rest = stripped[match.end():]
    close = f"</{tag}>"
    body = rest[: -len(close)] if rest.endswith(close) else rest
    return f"<{tag}{attrs}>{marker}{body}{close}"


class MockReviewer:
    """Мок редактора: меняет маркер перевода на «ГОТОВО:» в первом блоке фрагмента."""

    def __init__(self, find: str = "ПЕРЕВОД:", replace: str = "ГОТОВО:"):
        self.find = find
        self.replace = replace
        self.calls = 0

    def chat(self, system: str, user: str, **_: Any) -> LLMResponse:
        self.calls += 1
        ids = re.findall(r"### Блок (\S+)", user)
        edits = []
        if ids:
            edits.append(
                {
                    "id": ids[0],
                    "priority": "minor",
                    "find": self.find,
                    "replace": self.replace,
                    "problem": "мок: проверка применения правок",
                }
            )
        text = json.dumps({"edits": edits}, ensure_ascii=False)
        return LLMResponse(text=text, usage=Usage(prompt_tokens=len(user) // 4,
                                                  completion_tokens=len(text) // 4))
