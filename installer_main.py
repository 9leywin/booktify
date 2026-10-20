"""Установщик Booktify.

Собран PyInstaller'ом в один `BooktifySetup.exe`: внутри лежит папка с готовым
приложением. Умеет ставить в выбранную папку, делать ярлыки, регистрировать
удаление и запускать приложение. Есть тихий режим для проверки:

    BooktifySetup.exe --silent --target C:\\path\\to\\install
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import winreg

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Booktify"
APP_EXE = "Booktify.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Booktify"


def resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, *parts)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def default_target() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def payload_dir() -> str:
    """Папка с приложением: внутри установщика или рядом при запуске из исходников."""
    override = os.environ.get("BT_PAYLOAD")
    if override and os.path.isdir(override):
        return override
    internal = resource("payload")
    if os.path.isdir(internal):
        return internal
    for candidate in ("dist-next/Booktify", "dist/Booktify"):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), candidate)
        if os.path.isdir(path):
            return path
    return internal


def _powershell(script: str) -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def make_shortcut(link_path: str, target_exe: str) -> bool:
    os.makedirs(os.path.dirname(link_path), exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{link_path}'); "
        f"$s.TargetPath = '{target_exe}'; "
        f"$s.WorkingDirectory = '{os.path.dirname(target_exe)}'; "
        f"$s.IconLocation = '{target_exe},0'; "
        "$s.Save()"
    )
    return _powershell(script)


def write_uninstaller(target: str) -> str:
    path = os.path.join(target, "uninstall.ps1")
    content = f"""$ErrorActionPreference = 'SilentlyContinue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Remove-Item "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}.lnk" -Force
Remove-Item "$env:USERPROFILE\\Desktop\\{APP_NAME}.lnk" -Force
Remove-Item 'HKCU:\\{UNINSTALL_KEY}' -Recurse -Force
Start-Process powershell -ArgumentList '-NoProfile','-Command',"Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$dir' -Recurse -Force"
"""
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(content)
    return path


def register_uninstall(target: str, uninstaller: str, version: str = "1.0.0") -> None:
    exe = os.path.join(target, APP_EXE)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Booktify")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, target)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, exe)
        winreg.SetValueEx(
            key, "UninstallString", 0, winreg.REG_SZ,
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{uninstaller}"',
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def install(target: str, desktop_shortcut: bool, progress=None) -> None:
    source = payload_dir()
    if not os.path.isdir(source):
        raise RuntimeError("в установщике нет файлов приложения")

    os.makedirs(target, exist_ok=True)

    files: list[tuple[str, str]] = []
    for root, _dirs, names in os.walk(source):
        for name in names:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, source)
            files.append((src, os.path.join(target, rel)))

    total = max(1, len(files))
    for index, (src, dst) in enumerate(files, start=1):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if progress:
            progress(index, total)

    exe = os.path.join(target, APP_EXE)
    if not os.path.exists(exe):
        raise RuntimeError("после установки не найден Booktify.exe")

    uninstaller = write_uninstaller(target)

    start_menu = os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"
    )
    make_shortcut(os.path.join(start_menu, f"{APP_NAME}.lnk"), exe)
    if desktop_shortcut:
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        make_shortcut(os.path.join(desktop, f"{APP_NAME}.lnk"), exe)

    try:
        register_uninstall(target, uninstaller)
    except OSError:
        # Нет прав на HKCU — установка всё равно рабочая.
        pass


class InstallThread(QThread):
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, target: str, desktop: bool):
        super().__init__()
        self.target = target
        self.desktop = desktop

    def run(self) -> None:
        try:
            install(self.target, self.desktop, self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class SetupWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Установка {APP_NAME}")
        self.setWindowIcon(QIcon(resource("assets", "icon.png")))
        self.setMinimumWidth(560)
        self._thread: InstallThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setObjectName("H1")
        layout.addWidget(title)

        subtitle = QLabel("Переводчик книг с английского на русский")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(subtitle)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Куда установить"))
        row = QHBoxLayout()
        self.path = QLineEdit(default_target())
        row.addWidget(self.path, stretch=1)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        self.desktop = QCheckBox("Создать ярлык на рабочем столе")
        self.desktop.setChecked(True)
        layout.addWidget(self.desktop)

        self.status = QLabel("")
        self.status.setObjectName("Stat")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = QPushButton("Отмена")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("Primary")
        self.install_button.clicked.connect(self._install)
        buttons.addWidget(self.install_button)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Куда установить", self.path.text())
        if path:
            self.path.setText(os.path.join(path, APP_NAME))

    def _install(self) -> None:
        target = self.path.text().strip()
        if not target:
            QMessageBox.warning(self, "Нужна папка", "Выбери папку для установки.")
            return
        self.install_button.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText("Копируем файлы…")

        self._thread = InstallThread(target, self.desktop.isChecked())
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._done)
        self._thread.failed.connect(self._failed)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setMaximum(total)
        self.bar.setValue(done)

    def _done(self) -> None:
        self.status.setText("Готово. Booktify установлен.")
        self.bar.setValue(self.bar.maximum())
        self.install_button.setText("Запустить Booktify")
        self.install_button.setEnabled(True)
        try:
            self.install_button.clicked.disconnect()
        except RuntimeError:
            pass
        exe = os.path.join(self.path.text().strip(), APP_EXE)
        self.install_button.clicked.connect(lambda: subprocess.Popen([exe]))
        self.close_button.setText("Закрыть")

    def _failed(self, message: str) -> None:
        self.install_button.setEnabled(True)
        self.bar.setVisible(False)
        self.status.setText("")
        QMessageBox.critical(self, "Установка не удалась", message)


def silent_install(target: str, desktop: bool) -> int:
    try:
        install(target, desktop)
    except Exception as exc:  # noqa: BLE001
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed: {target}")
    return 0


SETUP_QSS = """
* { font-family: "Segoe UI", sans-serif; font-size: 15px; color: #1B2233; }
QWidget { background: #F5F7FB; }
QLabel#H1 { font-size: 30px; font-weight: 600; }
QLabel#Subtitle { color: #6B7280; }
QLabel#Stat { color: #6B7280; }
QLineEdit { background: #FFFFFF; border: 1px solid #E1E6F0; border-radius: 10px; padding: 9px 12px; }
QPushButton { background: #FFFFFF; border: 1px solid #E1E6F0; border-radius: 10px; padding: 10px 18px; }
QPushButton:hover { border-color: #B9C4DA; }
QPushButton#Primary { background: #2F6FED; color: white; border: none; border-radius: 12px; padding: 14px 26px; font-weight: 600; }
QPushButton#Primary:hover { background: #255FD0; }
QProgressBar { background: #E3E8F2; border: none; border-radius: 6px; height: 10px; }
QProgressBar::chunk { background: #2F6FED; border-radius: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 2px solid #B9C4DA; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #2F6FED; border-color: #2F6FED; }
"""


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--target", default=default_target())
    parser.add_argument("--no-desktop", action="store_true")
    args, _ = parser.parse_known_args()

    if args.silent:
        return silent_install(args.target, not args.no_desktop)

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} Setup")
    app.setStyleSheet(SETUP_QSS)
    window = SetupWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
