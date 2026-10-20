"""Загрузка промптов из markdown-файлов и подстановка переменных.

Промпт — это документ для человека и одновременно шаблон для кода: секции
`## SYSTEM` и `## USER` отделены, всё остальное (пояснения, примеры) в запрос
не уходит.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class PromptError(Exception):
    pass


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def render(self, **values: str) -> tuple[str, str]:
        def sub(template: str) -> str:
            def repl(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in values:
                    raise PromptError(f"в промпте {self.name} нет значения для {{{{{key}}}}}")
                return str(values[key])

            return PLACEHOLDER_RE.sub(repl, template)

        return sub(self.system), sub(self.user_template)


def load_prompt(name: str = "translate") -> Prompt:
    """`translate` → файл `prompts/translate_v1.md` (последняя версия)."""
    return _load(name, _latest_version(name))


def list_versions(name: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(name)}_v(\d+)\.md$")
    versions = []
    for filename in os.listdir(PROMPT_DIR):
        m = pattern.match(filename)
        if m:
            versions.append(m.group(1))
    return sorted(versions, key=int)


def _latest_version(name: str) -> str:
    versions = list_versions(name)
    if not versions:
        raise PromptError(f"не найден файл промпта {name}_vN.md в {PROMPT_DIR}")
    return versions[-1]


@lru_cache(maxsize=16)
def _load(name: str, version: str) -> Prompt:
    path = os.path.join(PROMPT_DIR, f"{name}_v{version}.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    system = _section(text, "SYSTEM")
    user = _section(text, "USER")
    if not system or not user:
        raise PromptError(f"{path}: нужны секции ## SYSTEM и ## USER")
    return Prompt(name=name, version=f"v{version}", system=system, user_template=user)


def _section(text: str, title: str) -> str:
    """Берёт тело секции до следующего `## ...` вне ограждения ```.

    Внутри пользовательского шаблона есть свои `## Книга`, `## Глоссарий` —
    это часть промпта, а не граница секции.
    """
    lines = text.splitlines()
    marker = f"## {title}".lower()
    start = None
    for index, line in enumerate(lines):
        if line.strip().lower() == marker:
            start = index + 1
            break
    if start is None:
        return ""

    body: list[str] = []
    fence = False
    for line in lines[start:]:
        if line.strip().startswith("```"):
            fence = not fence
            body.append(line)
            continue
        if not fence and re.match(r"^##\s+\S", line):
            break
        body.append(line)

    return _strip_fences("\n".join(body))


def _strip_fences(body: str) -> str:
    """Убирает ограждение ``` вокруг шаблона, не трогая текст внутри."""
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        for index in range(len(lines) - 1, -1, -1):
            if lines[index].strip().startswith("```"):
                lines = lines[:index]
                break
    return "\n".join(lines).strip()
