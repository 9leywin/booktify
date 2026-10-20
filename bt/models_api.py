"""Список моделей у провайдера: GET /models с ключом.

Нужен, чтобы в настройках не вписывать имя модели вручную: вставил ключ —
приложение проверило его и показало, что доступно.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

#: Служебные модели, которые не умеют переводить текст.
SKIP_PARTS = (
    "embedding", "embed", "whisper", "tts", "dall-e", "moderation",
    "audio", "transcribe", "image", "davinci", "babbage", "clip",
    "rerank", "guard", "omni-moderation", "codex-mini",
)


def _http_get(url: str, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if exc.code in (401, 403):
            raise PermissionError(f"ключ не принят (HTTP {exc.code})") from exc
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"нет связи: {exc.reason}") from exc


def filter_models(ids: list[str]) -> list[str]:
    result = []
    for model in ids:
        low = model.lower()
        if any(part in low for part in SKIP_PARTS):
            continue
        result.append(model)
    # Стабильный порядок: сначала привычные имена, потом остальные.
    return sorted(dict.fromkeys(result), key=lambda name: (name.count("/"), name.lower()))


def fetch_models(
    base_url: str,
    api_key: str,
    timeout: float = 20.0,
    transport=None,
) -> list[str]:
    """Возвращает доступные модели. Бросает PermissionError на неверный ключ."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = (transport or _http_get)(url, headers, timeout)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("сервис вернул неожиданный ответ")
    ids = [item.get("id") for item in items if isinstance(item, dict) and item.get("id")]
    models = filter_models(ids)
    if not models:
        raise RuntimeError("сервис не вернул ни одной модели")
    return models
