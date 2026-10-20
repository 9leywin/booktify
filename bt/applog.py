"""Простой журнал приложения.

Пишется в `%APPDATA%/Booktify/app.log`. Нужен, чтобы разбирать проблемы
на чужой машине: без консоли у оконного приложения нет другого способа рассказать,
что произошло.
"""

from __future__ import annotations

import os
import tempfile
import time
import traceback


def _base_dir() -> str:
    try:
        from .config import config_dir

        return config_dir()
    except Exception:
        fallback = os.path.join(tempfile.gettempdir(), "Booktify")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback


def log(message: str) -> None:
    path = os.path.join(_base_dir(), "app.log")
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n"
    try:
        # Держим журнал коротким: последние ~200 запусков, не больше 256 КБ.
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-500:]
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(tail)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def log_exception(prefix: str = "ошибка") -> None:
    log(prefix + ":\n" + traceback.format_exc())


def log_path() -> str:
    return os.path.join(_base_dir(), "app.log")
