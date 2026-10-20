"""Иконка приложения: рисуется кодом, без бинарных исходников в репозитории."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

SIZE = 256
TOP = (63, 120, 235)
BOTTOM = (24, 43, 94)
GOLD = (226, 191, 112)
WHITE = (250, 251, 255)


def rounded_gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), BOTTOM)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return image


def draw_icon(size: int = SIZE) -> Image.Image:
    image = rounded_gradient(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    image.putalpha(mask)

    draw = ImageDraw.Draw(image)
    k = size / 256.0

    # Раскрытая книга: две страницы с общим корешком.
    left = [int(46 * k), int(72 * k), int(124 * k), int(190 * k)]
    right = [int(132 * k), int(72 * k), int(210 * k), int(190 * k)]
    draw.rounded_rectangle(left, radius=int(10 * k), fill=WHITE)
    draw.rounded_rectangle(right, radius=int(10 * k), fill=WHITE)

    # Линии текста на страницах.
    for i in range(4):
        y = int((96 + i * 20) * k)
        draw.line([(int(62 * k), y), (int(110 * k), y)], fill=(150, 166, 196), width=max(2, int(4 * k)))
        draw.line([(int(146 * k), y), (int(194 * k), y)], fill=(150, 166, 196), width=max(2, int(4 * k)))

    # Корешок и закладка.
    draw.line([(int(128 * k), int(80 * k)), (int(128 * k), int(186 * k))], fill=(120, 136, 168), width=max(2, int(4 * k)))
    draw.polygon(
        [
            (int(168 * k), int(72 * k)),
            (int(190 * k), int(72 * k)),
            (int(190 * k), int(116 * k)),
            (int(179 * k), int(104 * k)),
            (int(168 * k), int(116 * k)),
        ],
        fill=GOLD,
    )
    return image


def draw_gear(size: int = 64) -> Image.Image:
    """Шестерёнка для кнопки «Настройки»: серый цвет читается на обеих темах."""
    import math

    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = (138, 150, 171, 255)
    center = big / 2
    outer = big * 0.30
    inner = big * 0.205
    tooth_w = big * 0.085
    tooth_h = big * 0.10

    for index in range(8):
        angle = math.radians(index * 45)
        points = []
        for dx, dy in ((-tooth_w / 2, -outer - tooth_h / 2),
                       (tooth_w / 2, -outer - tooth_h / 2),
                       (tooth_w / 2, -inner + tooth_h / 2),
                       (-tooth_w / 2, -inner + tooth_h / 2)):
            x = center + dx * math.cos(angle) - dy * math.sin(angle)
            y = center + dx * math.sin(angle) + dy * math.cos(angle)
            points.append((x, y))
        draw.polygon(points, fill=color)

    draw.ellipse(
        [center - outer, center - outer, center + outer, center + outer],
        outline=color,
        width=int(big * 0.055),
    )
    draw.ellipse(
        [center - outer * 0.35, center - outer * 0.35,
         center + outer * 0.35, center + outer * 0.35],
        fill=color,
    )
    return image.resize((size, size), Image.LANCZOS)


def draw_chevron(color: tuple[int, int, int], size: int = 28) -> Image.Image:
    """Аккуратная стрелка для выпадающих списков (вместо системной)."""
    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = int(big * 0.095)
    left, right, top, bottom = big * 0.28, big * 0.72, big * 0.40, big * 0.62
    draw.line([(left, top), (big / 2, bottom)], fill=color + (255,), width=width, joint="curve")
    draw.line([(big / 2, bottom), (right, top)], fill=color + (255,), width=width, joint="curve")
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)
    icon = draw_icon()
    png = os.path.join(ASSETS, "icon.png")
    ico = os.path.join(ASSETS, "icon.ico")
    icon.save(png)
    icon.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    gear = os.path.join(ASSETS, "gear.png")
    draw_gear().save(gear)
    draw_chevron((107, 114, 128)).save(os.path.join(ASSETS, "chevron_light.png"))
    draw_chevron((152, 163, 184)).save(os.path.join(ASSETS, "chevron_dark.png"))
    print("иконки:", png, ico, gear, "chevrons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
