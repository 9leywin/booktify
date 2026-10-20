"""Настройки приложения: провайдер, модель, качество, папки.

Хранятся в `%APPDATA%/BookTranslator/settings.json`. Ключ доступа — отдельно,
в зашифрованном виде (см. `secrets.py`).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field

from . import secrets

PROVIDERS = {
    "DeepSeek": "https://api.deepseek.com",
    "OpenAI": "https://api.openai.com/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "LM Studio (локально)": "http://localhost:1234/v1",
    "Другой адрес": "",
}

MODELS = {
    "DeepSeek": ["deepseek-flash", "deepseek-v4-pro"],
    "OpenAI": ["gpt-4o-mini", "gpt-4o"],
    "OpenRouter": ["deepseek/deepseek-chat", "openai/gpt-4o-mini"],
    "LM Studio (локально)": ["local-model"],
    "Другой адрес": ["model"],
}

QUALITY = {
    "fast": {"title": "Быстро", "hint": "один проход", "review": False, "model": "deepseek-flash"},
    "standard": {"title": "Обычное", "hint": "перевод + редактура", "review": True, "model": "deepseek-flash"},
    "max": {"title": "Максимум", "hint": "модель + редактура", "review": True, "model": "deepseek-v4-pro"},
}


def _writable(path: str) -> bool:
    """Проверяет каталог делом: создать и записать пробный файл.

    Удаление пробного файла не считаем обязательным: антивирус может подержать
    его пару секунд, и из-за этого нельзя объявлять рабочий каталог недоступным.
    """
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return False

    probe = os.path.join(path, ".write-test")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
    except OSError:
        return False
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


APP_NAME = "Booktify"
OLD_NAME = "BookTranslator"


def _candidates() -> list[str]:
    paths: list[str] = []
    override = os.environ.get("BT_CONFIG_DIR")
    if override:
        paths.append(override)

    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, APP_NAME))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(os.path.join(local, APP_NAME))

    # Профиль пользователя: сюда писать обычно можно, даже когда AppData
    # закрыт политикой. И это место не удаляется при пересборке приложения.
    profile = os.environ.get("USERPROFILE")
    if profile:
        paths.append(os.path.join(profile, APP_NAME))

    # Портативный режим: рядом с папкой программы, но НЕ внутри неё —
    # PyInstaller при сборке стирает dist\Booktify вместе с содержимым.
    exe_dir = _exe_dir()
    paths.append(os.path.join(os.path.dirname(exe_dir), f"{APP_NAME}-data"))
    paths.append(os.path.join(exe_dir, "userdata"))
    paths.append(os.path.join(tempfile.gettempdir(), APP_NAME))
    return paths


def _exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _legacy_dirs() -> list[str]:
    """Где могли остаться настройки прежних версий (включая старое имя)."""
    exe_dir = _exe_dir()
    paths = [os.path.join(exe_dir, "userdata"),
             os.path.join(os.path.dirname(exe_dir), f"{OLD_NAME}-data")]
    for env in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
        base = os.environ.get(env)
        if base:
            paths.append(os.path.join(base, OLD_NAME))
    paths.append(os.path.join(tempfile.gettempdir(), OLD_NAME))
    return paths


def migrate_legacy(source: str, dest: str) -> bool:
    """Переносит настройки и кэш из старого места, если оно ещё существует."""
    if os.path.abspath(source) == os.path.abspath(dest) or not os.path.isdir(source):
        return False

    import shutil

    moved = False
    for name in ("settings.json", "app.log"):
        src = os.path.join(source, name)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dest, name))
                moved = True
            except OSError:
                pass

    src_cache = os.path.join(source, "cache")
    if os.path.isdir(src_cache):
        try:
            shutil.copytree(src_cache, os.path.join(dest, "cache"), dirs_exist_ok=True)
            moved = True
        except OSError:
            pass

    src_books = os.path.join(source, "books")
    if os.path.isdir(src_books):
        try:
            shutil.copytree(src_books, os.path.join(dest, "books"), dirs_exist_ok=True)
            moved = True
        except OSError:
            pass

    return moved


_cached_dir: str | None = None


def reset_cache() -> None:
    global _cached_dir
    _cached_dir = None


def config_dir() -> str:
    """Первое место, куда реально можно писать.

    `%APPDATA%` на некоторых машинах закрыт политикой или антивирусом — тогда
    уходим в `%LOCALAPPDATA%`, профиль пользователя, папку рядом с программой
    или временный каталог.
    """
    global _cached_dir
    if _cached_dir:
        return _cached_dir

    candidates = _candidates()

    # Если настройки уже лежат в одном из мест — остаёмся там, даже если выше
    # появилась записываемая папка. Иначе ключ «пропадал» бы при смене прав.
    for path in candidates:
        if os.path.exists(os.path.join(path, "settings.json")) and _writable(path):
            _cached_dir = path
            return path

    for path in candidates:
        if _writable(path):
            _cached_dir = path
            moved_from = None
            for legacy in _legacy_dirs():
                if migrate_legacy(legacy, path):
                    moved_from = legacy
            if moved_from:
                try:
                    from . import applog

                    applog.log(f"данные перенесены из {moved_from} в {path}")
                except Exception:
                    pass
            return path

    # Совсем крайний случай: пусть будет временный каталог, даже если проверка
    # не прошла — приложение сможет работать без сохранения настроек.
    _cached_dir = os.path.join(tempfile.gettempdir(), APP_NAME)
    return _cached_dir


@dataclass
class Settings:
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    quality: str = "standard"
    theme_mode: str = "system"
    jobs: int = 3
    output_dir: str = ""
    api_key_enc: str = ""
    last_folder: str = ""
    demo_mode: bool = False
    recent: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- доступ

    @property
    def api_key(self) -> str:
        return secrets.unprotect(self.api_key_enc)

    def set_api_key(self, value: str) -> None:
        self.api_key_enc = secrets.protect(value.strip())

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def needs_review(self) -> bool:
        return bool(QUALITY.get(self.quality, {}).get("review"))

    def effective_model(self) -> str:
        if self.provider == "DeepSeek":
            return "deepseek-v4-pro" if self.quality == "max" else "deepseek-flash"
        if self.provider == "LM Studio (локально)":
            return self.model or "local-model"
        return self.model or "deepseek-flash"

    # ---------------------------------------------------------------- файлы

    @classmethod
    def path(cls) -> str:
        return os.path.join(config_dir(), "settings.json")

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(cls.path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        tmp = self.path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path())
