"""Хранение ключа доступа.

На Windows ключ шифруется через DPAPI (`CryptProtectData`): расшифровать может
только тот же пользователь на той же машине. Если DPAPI недоступен, ключ
сохраняется как есть — приложение об этом предупреждает, а не делает вид,
что всё в порядке.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import os


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return os.name == "nt" and hasattr(ctypes, "windll")


def protect(text: str) -> str:
    if not text:
        return ""
    if not available():
        return "plain:" + base64.b64encode(text.encode("utf-8")).decode("ascii")
    data = text.encode("utf-8")
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), "book-translator", None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise OSError("DPAPI: не удалось зашифровать ключ")
    try:
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")


def unprotect(value: str) -> str:
    if not value:
        return ""
    if value.startswith("plain:"):
        return base64.b64decode(value[6:]).decode("utf-8")
    if not value.startswith("dpapi:"):
        return value
    if not available():
        return ""
    encrypted = base64.b64decode(value[6:])
    buffer = ctypes.create_string_buffer(encrypted, len(encrypted))
    blob_in = _Blob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        return ""
    try:
        data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return data.decode("utf-8", "replace")
