"""Оформление: две палитры, таблица стилей и определение системной темы."""

from __future__ import annotations

import os
import sys


def _asset(name: str) -> str:
    """Путь к картинке для QSS: в сборке — из _MEIPASS, иначе из проекта."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        path = os.path.join(base, "assets", name)
    else:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "assets", name)
    return path.replace("\\", "/")

LIGHT = {
    "BG": "#F5F7FB",
    "CARD": "#FFFFFF",
    "CARD_HOVER": "#FAFBFE",
    "SUBTLE": "#F0F3F9",
    "TEXT": "#1B2233",
    "MUTED": "#6B7280",
    "BORDER": "#E1E6F0",
    "BORDER_STRONG": "#B9C4DA",
    "PRIMARY": "#2F6FED",
    "PRIMARY_HOVER": "#255FD0",
    "PRIMARY_SOFT": "#E8F0FF",
    "SUCCESS": "#16A34A",
    "DANGER": "#DC2626",
    "WARN": "#D97706",
    "RING_BG": "#E3E8F2",
    "SCROLL": "#CBD3E3",
    "TOOLTIP_BG": "#232A3B",
}

DARK = {
    "BG": "#12161F",
    "CARD": "#1A202C",
    "CARD_HOVER": "#202736",
    "SUBTLE": "#1F2634",
    "TEXT": "#E6EAF2",
    "MUTED": "#98A3B8",
    "BORDER": "#2A3242",
    "BORDER_STRONG": "#3A4557",
    "PRIMARY": "#5B8DEF",
    "PRIMARY_HOVER": "#6F9BF2",
    "PRIMARY_SOFT": "#1D2A44",
    "SUCCESS": "#34D399",
    "DANGER": "#F87171",
    "WARN": "#FBBF24",
    "RING_BG": "#262E3D",
    "SCROLL": "#3A4456",
    "TOOLTIP_BG": "#2B3444",
}

_dark = False
_current = LIGHT
globals().update(LIGHT)


def set_mode(dark: bool) -> None:
    global _dark, _current
    _dark = bool(dark)
    _current = DARK if _dark else LIGHT
    globals().update(_current)


def is_dark() -> bool:
    return _dark


def system_is_dark() -> bool:
    """Системная тема Windows: AppsUseLightTheme = 0 означает тёмную."""
    if os.name != "nt":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except OSError:
        return False


def qss() -> str:
    """Таблица стилей под текущую палитру."""
    return f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 15px;
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background: {BG};
}}

QWidget#Page {{
    background: {BG};
}}

QLabel#Title {{
    font-size: 26px;
    font-weight: 600;
}}

QLabel#Subtitle {{
    font-size: 15px;
    color: {MUTED};
}}

QLabel#H1 {{
    font-size: 30px;
    font-weight: 600;
}}

QLabel#Muted {{
    color: {MUTED};
}}

QLabel#Stat {{
    font-size: 14px;
    color: {MUTED};
}}

QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}

QFrame#DropZone {{
    background: {CARD};
    border: 2px dashed {BORDER_STRONG};
    border-radius: 20px;
}}

QFrame#DropZone[dragging="true"] {{
    background: {PRIMARY_SOFT};
    border-color: {PRIMARY};
}}

QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 18px;
}}

QPushButton:hover {{
    border-color: {BORDER_STRONG};
    background: {CARD_HOVER};
}}

QPushButton#Pill {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 18px;
    padding: 8px 18px 8px 14px;
    color: {TEXT};
}}

QPushButton#Pill:hover {{
    border-color: {PRIMARY};
    color: {PRIMARY};
}}

QPushButton#Primary {{
    background: {PRIMARY};
    color: white;
    border: none;
    border-radius: 12px;
    padding: 15px 28px;
    font-size: 17px;
    font-weight: 600;
}}

QPushButton#Primary:hover {{
    background: {PRIMARY_HOVER};
}}

QPushButton#Primary:disabled {{
    background: {BORDER_STRONG};
}}

QPushButton#Quiet {{
    background: transparent;
    border: none;
    color: {MUTED};
    padding: 8px 10px;
}}

QPushButton#Quiet:hover {{
    color: {TEXT};
}}

QPushButton#Link {{
    background: transparent;
    border: none;
    color: {PRIMARY};
    padding: 4px 6px;
    text-align: left;
}}

QPushButton#Segment {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 16px;
    text-align: left;
}}

QPushButton#Segment:checked {{
    background: {PRIMARY_SOFT};
    border-color: {PRIMARY};
    color: {PRIMARY};
    font-weight: 600;
}}

QToolButton#RecentsHeader {{
    background: transparent;
    border: none;
    color: {MUTED};
    padding: 4px 2px;
    font-size: 14px;
}}

QToolButton#RecentsHeader:hover {{
    color: {TEXT};
}}

QProgressBar {{
    background: {RING_BG};
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 6px;
}}

QLineEdit, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 9px 12px;
}}

QLineEdit:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}

QComboBox QAbstractItemView {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {TEXT};
}}

QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 4px 8px;
}}

QComboBox::drop-down {{
    border: none;
    width: 32px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}

QComboBox::down-arrow {{
    image: url("{_asset("chevron_dark.png" if _dark else "chevron_light.png")}");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}}

QCheckBox {{
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 2px solid {BORDER_STRONG};
    background: {CARD};
}}

QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}

QTableWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    gridline-color: {BORDER};
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {TEXT};
}}

QHeaderView::section {{
    background: {SUBTLE};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px;
    color: {MUTED};
}}

QListWidget {{
    background: transparent;
    border: none;
}}

QListWidget::item {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 12px;
    margin: 4px 0;
}}

QListWidget::item:selected {{
    border-color: {PRIMARY};
    background: {PRIMARY_SOFT};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}

QScrollBar::handle:vertical {{
    background: {SCROLL};
    border-radius: 5px;
    min-height: 30px;
}}

QToolTip {{
    background: {TOOLTIP_BG};
    color: white;
    border: none;
    padding: 6px;
}}
"""
