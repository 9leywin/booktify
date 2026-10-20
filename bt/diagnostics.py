"""Диагностика окружения: почему Windows отказывает в записи.

ACL может разрешать запись, но Windows проверяет ещё и уровень целостности
процесса. Процесс с низким уровнем (Low IL) не может писать в `%APPDATA%`,
`Downloads`, `Documents` — получает «Отказано в доступе», хотя права вроде есть.
Так бывает, когда приложение запущено из песочницы, из другого ограниченного
процесса или с пониженными правами.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os

LEVELS = {
    0x0000: "untrusted",
    0x1000: "low",
    0x2000: "medium",
    0x3000: "high",
    0x4000: "system",
}


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenMandatoryLabel(ctypes.Structure):
    _fields_ = [("Label", _SidAndAttributes)]


def integrity_level() -> str:
    """Возвращает low / medium / high / unknown."""
    if os.name != "nt":
        return "unknown"
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        k32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)  # TOKEN_QUERY
        ):
            return "unknown"

        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))  # TokenIntegrityLevel
        if size.value <= 0:
            ctypes.windll.kernel32.CloseHandle(token)
            return "unknown"

        buffer = ctypes.create_string_buffer(size.value)
        ok = advapi32.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size))
        ctypes.windll.kernel32.CloseHandle(token)
        if not ok:
            return "unknown"

        label = ctypes.cast(buffer, ctypes.POINTER(_TokenMandatoryLabel)).contents
        sid = label.Label.Sid
        if not sid:
            return "unknown"

        # Разбираем SID как байты: revision (1), count (1), authority (6),
        # дальше идут subauthorities по 4 байта.
        count = ctypes.cast(sid, ctypes.POINTER(ctypes.c_ubyte))[1]
        if count < 1:
            return "unknown"
        raw = ctypes.string_at(sid, 8 + 4 * count)
        offset = 8 + 4 * (count - 1)
        rid = int.from_bytes(raw[offset:offset + 4], "little")
        return LEVELS.get(rid & 0xF000, f"0x{rid:04x}")
    except Exception:
        return "unknown"


def whoami_integrity() -> str:
    """Независимая проверка через whoami: сравниваем со своим разбором токена."""
    if os.name != "nt":
        return "unknown"
    try:
        import re
        import subprocess

        output = subprocess.run(
            ["whoami", "/groups"], capture_output=True, text=True, timeout=5,
            encoding="mbcs", errors="replace",
        ).stdout
        match = re.search(r"S-1-16-(\d+)", output)
        if not match:
            return "unknown"
        return {
            "4096": "low",
            "8192": "medium",
            "12288": "high",
            "16384": "system",
        }.get(match.group(1), "unknown")
    except Exception:
        return "unknown"


def describe_write_problem() -> str:
    """Короткое объяснение для журнала и настроек."""
    level = integrity_level()
    if level == "low":
        return (
            "приложение запущено с низким уровнем целостности: Windows не разрешает "
            "ему писать в AppData, Downloads и Документы, даже если права есть. "
            "Запусти ярлык обычным двойным щелчком из проводника"
        )
    return f"уровень целостности: {level}"


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def parent_process() -> tuple[int, str]:
    """PID и имя родителя: понять, из проводника запущено приложение или нет."""
    if os.name != "nt":
        return 0, ""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        k32.Process32First.restype = wintypes.BOOL
        k32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        k32.Process32Next.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        snapshot = k32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        invalid = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid:
            return 0, ""
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        me = os.getpid()
        parent = 0
        ok = k32.Process32First(snapshot, ctypes.byref(entry))
        for _ in range(8192):
            if not ok:
                break
            if entry.th32ProcessID == me:
                parent = entry.th32ParentProcessID
                break
            ok = k32.Process32Next(snapshot, ctypes.byref(entry))
        k32.CloseHandle(snapshot)

        if not parent:
            return 0, ""
        snapshot = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snapshot or snapshot == invalid:
            return parent, ""
        name = ""
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = k32.Process32First(snapshot, ctypes.byref(entry))
        for _ in range(8192):
            if not ok:
                break
            if entry.th32ProcessID == parent:
                name = entry.szExeFile.decode("mbcs", "replace")
                break
            ok = k32.Process32Next(snapshot, ctypes.byref(entry))
        k32.CloseHandle(snapshot)
        return parent, name
    except Exception:
        return 0, ""


def process_integrity(pid: int) -> str:
    """Уровень целостности чужого процесса (если получится открыть его токен)."""
    if os.name != "nt" or not pid:
        return "unknown"
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL

        handle = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return "no-access"
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            k32.CloseHandle(handle)
            return "no-access"
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(max(size.value, 64))
        ok = advapi32.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size))
        k32.CloseHandle(token)
        k32.CloseHandle(handle)
        if not ok:
            return "unknown"
        label = ctypes.cast(buffer, ctypes.POINTER(_TokenMandatoryLabel)).contents
        sid = label.Label.Sid
        count = ctypes.cast(sid, ctypes.POINTER(ctypes.c_ubyte))[1]
        raw = ctypes.string_at(sid, 8 + 4 * count)
        offset = 8 + 4 * (count - 1)
        rid = int.from_bytes(raw[offset:offset + 4], "little")
        return LEVELS.get(rid & 0xF000, f"0x{rid:04x}")
    except Exception:
        return "unknown"
