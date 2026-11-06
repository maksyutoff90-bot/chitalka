"""Иконка приложения: тёмный квадрат с медной раскрытой книгой."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "app.ico"
PNG = ROOT / "data" / "app.png"

BG = (25, 22, 19, 255)
BG_EDGE = (48, 42, 36, 255)
COPPER = (200, 121, 65, 255)
COPPER_LIGHT = (226, 158, 105, 255)
PAPER = (244, 236, 222, 255)


def draw(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(8, int(54 * scale))
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=BG, outline=BG_EDGE,
        width=max(1, int(2 * scale)),
    )

    def s(value: float) -> float:
        return value * scale

    # Раскрытая книга.
    left = [
        (s(48), s(78)), (s(122), s(92)), (s(122), s(196)), (s(48), s(182)),
    ]
    right = [
        (s(208), s(78)), (s(134), s(92)), (s(134), s(196)), (s(208), s(182)),
    ]
    draw.polygon(left, fill=PAPER, outline=COPPER_LIGHT)
    draw.polygon(right, fill=PAPER, outline=COPPER_LIGHT)
    draw.line((s(128), s(94), s(128), s(198)), fill=COPPER, width=max(2, int(3 * scale)))
    draw.line((s(122), s(92), s(128), s(98), s(134), s(92)),
              fill=COPPER, width=max(2, int(3 * scale)), joint="curve")

    # Строки текста.
    for offset, y in enumerate((116, 136, 156, 176)):
        width = 46 if offset != 3 else 30
        draw.line((s(64), s(y), s(64 + width), s(y + 2)),
                  fill=(122, 104, 86, 255), width=max(2, int(3 * scale)))
        draw.line((s(148), s(y), s(148 + width), s(y + 2)),
                  fill=(122, 104, 86, 255), width=max(2, int(3 * scale)))

    # Медная закладка сверху.
    draw.polygon(
        [(s(178), s(42)), (s(198), s(42)), (s(198), s(78)), (s(188), s(68)),
         (s(178), s(78))],
        fill=COPPER,
    )
    draw.line((s(76), s(206), s(180), s(206)), fill=(90, 70, 54, 255),
              width=max(2, int(2 * scale)))
    return image


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(size) for size in sizes]
    images[-1].save(OUT, format="ICO", sizes=[(size, size) for size in sizes])
    images[-1].save(PNG)
    print("saved", OUT, PNG)


if __name__ == "__main__":
    main()
