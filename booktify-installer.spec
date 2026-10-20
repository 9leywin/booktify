# -*- mode: python ; coding: utf-8 -*-
"""Сборка установщика Booktify в один BooktifySetup.exe.

Перед сборкой должен существовать каталог с приложением (dist-next/Booktify
или dist/Booktify).
Запуск: python -m PyInstaller --noconfirm --clean booktify-installer.spec
"""

import os

payload = next(
    (path for path in ("dist-next/Booktify", "dist/Booktify") if os.path.isdir(path)),
    "dist-next/Booktify",
)

a = Analysis(
    ["installer_main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        (payload, "payload"),
        ("assets", "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "pandas", "matplotlib", "pytest", "lxml", "PIL", "pypdf"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BooktifySetup",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
