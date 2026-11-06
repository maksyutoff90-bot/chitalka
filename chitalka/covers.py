"""Обложки: извлечение из книги и генерация типографских обложек."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import COVERS_DIR

COVER_W, COVER_H = 600, 900

# Спокойные книжные палитры: (фон сверху, фон снизу, акцент, чернила).
PALETTES = [
    ("#1f3040", "#0e1a24", "#d9b382", "#f4ead8"),
    ("#3c2a2a", "#1d1212", "#e0b07a", "#f6e9d8"),
    ("#24382f", "#101e17", "#c9a86a", "#f0ead8"),
    ("#3a3327", "#1c1810", "#d6b98a", "#f7efdd"),
    ("#2b2a45", "#141326", "#b9a6e0", "#f0ecfa"),
    ("#412f24", "#1e140e", "#dfa06d", "#faeedf"),
    ("#263744", "#101a21", "#9fc4c9", "#eef6f6"),
    ("#3d2436", "#1c0f18", "#dda6b8", "#fbedf2"),
]


def book_key(path: str | Path) -> str:
    normalized = str(Path(path).resolve()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def cover_path_for(path: str | Path) -> Path:
    return COVERS_DIR / f"{book_key(path)}.jpg"


def save_cover_bytes(path: str | Path, data: bytes) -> str:
    """Сохраняет и нормализует обложку; возвращает путь или ''."""
    if not data:
        return ""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return ""
    return save_cover_image(path, image)


def save_cover_image(path: str | Path, image: Image.Image) -> str:
    try:
        image = _cover_crop(image.convert("RGB"))
        target = cover_path_for(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=90, optimize=True, progressive=True)
        return str(target)
    except Exception:
        return ""


def _cover_crop(image: Image.Image) -> Image.Image:
    """Приводит к пропорции 2:3 без искажений."""
    target_ratio = COVER_W / COVER_H
    width, height = image.size
    ratio = width / max(1, height)
    if ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        image = image.crop((left, 0, left + new_width, height))
    elif ratio < target_ratio:
        new_height = int(width / target_ratio)
        top = max(0, (height - new_height) // 3)
        image = image.crop((0, top, width, top + new_height))
    return image.resize((COVER_W, COVER_H), Image.LANCZOS)


# ------------------------------------------------------------------ генерация
def _font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []
    if bold and italic:
        candidates = ["georgiaz.ttf", "timesbi.ttf", "arialbi.ttf"]
    elif bold:
        candidates = ["georgiab.ttf", "timesbd.ttf", "arialbd.ttf"]
    elif italic:
        candidates = ["georgiai.ttf", "timesi.ttf", "ariali.ttf"]
    else:
        candidates = ["georgia.ttf", "times.ttf", "arial.ttf"]
    for name in candidates:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = (current + " " + word).strip()
        if draw.textlength(probe, font=font) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _spaced(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, spacing: int = 3) -> None:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + spacing


def generate_cover(title: str, author: str, genre: str = "") -> str:
    """Рисует обложку в едином книжном стиле; кэшируется по названию."""
    key = hashlib.sha1(f"{title}|{author}".encode("utf-8")).hexdigest()[:16]
    target = COVERS_DIR / f"generated_{key}.jpg"
    if target.exists():
        return str(target)

    palette = PALETTES[int(key[:4], 16) % len(PALETTES)]
    top, bottom, accent, ink = palette
    image = Image.new("RGB", (COVER_W, COVER_H), top)
    draw = ImageDraw.Draw(image)
    top_rgb = tuple(int(top[i : i + 2], 16) for i in (1, 3, 5))
    bottom_rgb = tuple(int(bottom[i : i + 2], 16) for i in (1, 3, 5))
    for y in range(COVER_H):
        t = y / (COVER_H - 1)
        color = tuple(int(top_rgb[i] * (1 - t) + bottom_rgb[i] * t) for i in range(3))
        draw.line([(0, y), (COVER_W, y)], fill=color)

    # Мягкие световые пятна.
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((-180, -220, 420, 360), fill=(255, 255, 255, 12))
    gdraw.ellipse((330, 520, 820, 1040), fill=(255, 255, 255, 8))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Тонкая рамка.
    margin = 34
    draw.rectangle(
        (margin, margin, COVER_W - margin, COVER_H - margin),
        outline=_rgba(accent, 110),
        width=2,
    )
    draw.line((margin + 18, 148, COVER_W - margin - 18, 148), fill=_rgba(accent, 120), width=1)

    title_font_size = 64
    if len(title) > 42:
        title_font_size = 50
    if len(title) > 70:
        title_font_size = 42
    font_title = _font(title_font_size, bold=True)
    lines = _wrap(draw, title, font_title, COVER_W - 120)
    while len(lines) > 5 and title_font_size > 32:
        title_font_size -= 5
        font_title = _font(title_font_size, bold=True)
        lines = _wrap(draw, title, font_title, COVER_W - 120)

    line_height = int(title_font_size * 1.12)
    block_height = line_height * len(lines)
    start_y = 250 if block_height < 360 else 210
    y = start_y
    for line in lines:
        width = draw.textlength(line, font=font_title)
        draw.text(((COVER_W - width) / 2, y), line, font=font_title, fill=ink)
        y += line_height

    # Декоративная линия и жанр.
    rule_y = y + 30
    draw.line((COVER_W / 2 - 46, rule_y, COVER_W / 2 + 46, rule_y), fill=accent, width=2)

    if genre:
        font_genre = _font(19)
        label = genre.upper()[:36]
        width = sum(draw.textlength(c, font=font_genre) + 3 for c in label)
        _spaced(draw, ((COVER_W - width) / 2, rule_y + 24), label, font_genre, _rgba(accent, 220), 3)

    # Автор.
    font_author = _font(28)
    author_text = (author or "Неизвестный автор").strip()
    author_lines = _wrap(draw, author_text, font_author, COVER_W - 140)[:2]
    author_y = COVER_H - 150 - (len(author_lines) - 1) * 32
    for line in author_lines:
        width = draw.textlength(line, font=font_author)
        draw.text(((COVER_W - width) / 2, author_y), line, font=font_author, fill=ink)
        author_y += 32

    font_mark = _font(14)
    mark = "Ч И Т А Л К А"
    width = draw.textlength(mark, font=font_mark)
    draw.text(((COVER_W - width) / 2, COVER_H - 66), mark, font=font_mark, fill=_rgba(accent, 170))

    # Лёгкое зерно.
    noise = Image.effect_noise((COVER_W, COVER_H), 12).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    image = Image.composite(image, image.point(lambda p: min(255, p + 7)), noise.point(lambda p: 40 if p > 128 else 0))
    image.save(target, "JPEG", quality=90, optimize=True, progressive=True)
    return str(target)


def _rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        alpha,
    )


def ensure_cover(
    path: str | Path,
    *,
    title: str,
    author: str = "",
    genre: str = "",
    stored: str = "",
) -> str:
    """Возвращает существующую обложку или генерирует новую."""
    if stored:
        candidate = Path(stored)
        if candidate.exists() and candidate.stat().st_size > 0:
            return str(candidate)
    target = cover_path_for(path)
    if target.exists() and target.stat().st_size > 0:
        return str(target)
    return generate_cover(title, author, genre)


def cleanup_orphans(valid: set[str]) -> int:
    removed = 0
    for file in COVERS_DIR.glob("*.jpg"):
        if str(file) not in valid:
            try:
                file.unlink()
                removed += 1
            except OSError:
                pass
    return removed
