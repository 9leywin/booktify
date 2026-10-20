# -*- mode: python ; coding: utf-8 -*-
"""Сборка Booktify в каталог с .exe (portable-версия).

Запуск:  python -m PyInstaller --noconfirm --clean booktify.spec
Или:     powershell -File build.ps1 -Zip
"""

from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("prompts", "prompts"),
    ("assets", "assets"),
]
datas += collect_data_files("certifi")

hiddenimports = [
    "lxml",
    "lxml.etree",
    "lxml.html",
    "PIL",
    "PIL.Image",
    "pypdf",
]

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "pandas", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Booktify",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Booktify",
)
