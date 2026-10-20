"""Куда сохранять готовую книгу.

Windows (а точнее «Защита от программ-вымогателей» и корпоративные политики)
часто запрещает неподписанной программе писать в `Downloads`, `Documents`
и `Desktop`. Перевод при этом уже оплачен и готов, поэтому терять его нельзя:
если рядом с исходником писать нельзя, уходим в папку настроек.
"""

from __future__ import annotations

import os


def is_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".bt-write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def safe_output_path(target: str, fallback_dir: str) -> tuple[str, bool]:
    """Возвращает (путь, пришлось_ли_перенести).

    Если папка назначения недоступна на запись, файл кладётся в `fallback_dir`
    с тем же именем.
    """
    target = os.path.abspath(target)
    parent = os.path.dirname(target) or "."

    if is_writable_dir(parent):
        return target, False

    try:
        os.makedirs(fallback_dir, exist_ok=True)
    except OSError:
        # Совсем крайний случай: пусть будет текущий каталог.
        fallback_dir = os.getcwd()

    return os.path.join(fallback_dir, os.path.basename(target)), True
