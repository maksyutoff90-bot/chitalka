"""Постраничная вёрстка книги: строки, переносы, иллюстрации, главы."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

import tkinter.font as tkfont

from .formats.model import LINE_BREAK, Block, Chapter, Document


@dataclass
class LayoutStyle:
    family: str = "Georgia"
    size: int = 19              # пикселей
    line_spacing: float = 1.55
    justify: bool = True
    paragraph_indent: float = 1.3
    width: int = 640            # ширина текстовой области
    height: int = 760           # высота текстовой области
    chapter_page_break: bool = True
    header: bool = True
    footer: bool = True


@dataclass
class Segment:
    x: float
    text: str
    key: tuple
    link: str = ""
    underline: bool = False
    strike: bool = False
    dy: float = 0.0
    width: float = 0.0
    block_index: int = -1
    start: int = 0
    end: int = 0


@dataclass
class Line:
    y: float
    height: float
    segments: list[Segment] = field(default_factory=list)
    text: str = ""


@dataclass
class PlacedImage:
    path: str
    x: float
    y: float
    width: int
    height: int


@dataclass
class Rule:
    y: float
    width: float
    thickness: int = 1


@dataclass
class Page:
    index: int = 0
    lines: list[Line] = field(default_factory=list)
    images: list[PlacedImage] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    first_block: int = 0
    chapter: str = ""
    chapter_level: int = 0


@dataclass
class LayoutResult:
    pages: list[Page]
    block_pages: dict[int, int]
    chapters: list[Chapter]
    page_first_blocks: list[int]
    fonts: "FontSet"

    def page_for_block(self, block_index: int) -> int:
        if not self.pages:
            return 0
        index = bisect_right(self.page_first_blocks, max(0, block_index)) - 1
        return max(0, min(index, len(self.pages) - 1))

    def chapter_for_block(self, block_index: int) -> str:
        current = ""
        for chapter in self.chapters:
            if chapter.position <= block_index:
                current = chapter.title
            else:
                break
        return current


class FontSet:
    def __init__(self, root, style: LayoutStyle) -> None:
        self.root = root
        self.style = style
        self._fonts: dict[tuple, tkfont.Font] = {}
        self._metrics: dict[tuple, tuple[int, int]] = {}
        self._widths: dict[tuple[str, str], int] = {}
        self._chars: dict[tuple, dict[str, int]] = {}
        self.base_height = max(8, style.size)

    def key(
        self,
        *,
        bold: bool = False,
        italic: bool = False,
        sup: bool = False,
        sub: bool = False,
        code: bool = False,
        heading: int = 0,
        small: bool = False,
    ) -> tuple:
        return (
            bool(bold), bool(italic), bool(sup), bool(sub), bool(code),
            int(heading), bool(small),
        )

    def font(self, key: tuple) -> tkfont.Font:
        font = self._fonts.get(key)
        if font is not None:
            return font
        bold, italic, sup, sub, code, heading, small = key
        size = self.style.size
        if heading:
            size = int(size * {1: 1.9, 2: 1.45, 3: 1.2, 4: 1.05}.get(heading, 1.05))
        if small:
            size = int(size * 0.84)
        if sup or sub:
            size = int(size * 0.62)
        family = self.style.family
        if code:
            family = "Consolas"
            size = int(self.style.size * 0.86)
        font = tkfont.Font(
            root=self.root,
            family=family,
            size=-max(7, size),
            weight="bold" if (bold or heading) else "normal",
            slant="italic" if italic else "roman",
        )
        self._fonts[key] = font
        return font

    def metrics(self, key: tuple) -> tuple[int, int]:
        value = self._metrics.get(key)
        if value is None:
            font = self.font(key)
            value = (int(font.metrics("linespace")), int(font.metrics("ascent")))
            self._metrics[key] = value
        return value

    def width(self, key: tuple, text: str) -> int:
        cache_key = (key, text)
        value = self._widths.get(cache_key)
        if value is None:
            # Сумма ширин символов вместо measure() на каждое слово: это в
            # десятки раз быстрее и для книжного текста достаточно точно.
            table = self._chars.get(key)
            if table is None:
                table = {}
                self._chars[key] = table
            total = 0
            for char in text:
                char_width = table.get(char)
                if char_width is None:
                    char_width = int(self.font(key).measure(char))
                    table[char] = char_width
                total += char_width
            value = total
            if len(self._widths) < 160_000:
                self._widths[cache_key] = value
        return value

    def space(self, key: tuple) -> int:
        return self.width(key, " ")


@dataclass
class _Word:
    text: str
    key: tuple
    width: int
    link: str = ""
    underline: bool = False
    strike: bool = False
    sup: bool = False
    sub: bool = False
    space_before: int = 0
    block_index: int = -1
    start: int = 0
    end: int = 0


@dataclass
class _Break:
    pass


_BREAK = _Break()


def _run_key(block: Block, run) -> tuple:
    heading = int(block.kind[1]) if block.kind in ("h1", "h2", "h3", "h4") else 0
    return (
        run.bold, run.italic, run.sup, run.sub, run.code, heading, block.small,
    )


def _tokenize(block: Block, fonts: FontSet, block_index: int) -> list:
    tokens: list = []
    position = 0
    for run in block.runs:
        text = run.text
        if not text:
            continue
        key = _run_key(block, run)
        parts = re.split(r"([\s\u2028\n]+)", text)
        for part in parts:
            if not part:
                continue
            start = position
            position += len(part)
            if "\u2028" in part or "\n" in part:
                tokens.append(_BREAK)
                continue
            if part.isspace():
                tokens.append(("space", key))
                continue
            tokens.append(
                _Word(
                    text=part,
                    key=key,
                    width=fonts.width(key, part),
                    link=run.link,
                    underline=run.underline,
                    strike=run.strike,
                    sup=run.sup,
                    sub=run.sub,
                    block_index=block_index,
                    start=start,
                    end=position,
                )
            )
    return tokens


def _split_long_word(word: _Word, fonts: FontSet, max_width: int) -> list[_Word]:
    """Делит слишком длинное слово по символам."""
    pieces: list[_Word] = []
    current = ""
    for char in word.text:
        probe = current + char
        if current and fonts.width(word.key, probe) > max_width:
            pieces.append(_Word(current, word.key, fonts.width(word.key, current),
                               word.link, word.underline, word.strike, word.sup, word.sub,
                               block_index=word.block_index,
                               start=word.start + len(current),
                               end=word.start + len(current)))
            current = char
        else:
            current = probe
    if current:
        pieces.append(_Word(current, word.key, fonts.width(word.key, current),
                           word.link, word.underline, word.strike, word.sup, word.sub,
                           block_index=word.block_index,
                           start=word.start + len(word.text) - len(current),
                           end=word.end))
    # Пересчитываем границы кусков последовательно.
    cursor = word.start
    for piece in pieces:
        piece.start = cursor
        cursor += len(piece.text)
        piece.end = cursor
    return pieces


def _block_geometry(block: Block, style: LayoutStyle) -> tuple[float, float, str, float]:
    """(отступ слева, абзацный отступ, выравнивание, межстрочный множитель)."""
    base = style.size
    indent = block.indent * base
    first = block.first_indent
    if first is None:
        first = style.paragraph_indent if block.kind == "p" else 0.0
    first_px = max(0.0, float(first) * base)
    align = block.align or "left"
    if block.kind == "h1":
        align = "center"
    elif block.kind in ("h2", "h3", "h4"):
        align = block.align or "left"
    if block.kind == "epigraph":
        align = "right"
    return indent, first_px, align, 1.0


def _line_height(words: Iterable[_Word], fonts: FontSet, style: LayoutStyle) -> int:
    base_key = fonts.key()
    height = max(
        fonts.metrics(base_key)[0],
        int(round(style.size * style.line_spacing)),
    )
    for word in words:
        height = max(height, fonts.metrics(word.key)[0])
    return max(8, int(round(height)))


def _make_line(words: list[_Word], align: str, avail: float, indent: float,
               fonts: FontSet, style: LayoutStyle, *, justify: bool,
               first: bool) -> Line:
    natural = sum(word.width for word in words) + sum(word.space_before for word in words)
    x = indent
    extra = 0.0
    if justify and align == "justify" and len(words) > 1 and natural < avail:
        extra = (avail - natural) / (len(words) - 1)
    elif align == "center":
        x += max(0.0, (avail - natural) / 2)
    elif align == "right":
        x += max(0.0, avail - natural)

    segments: list[Segment] = []
    text_parts: list[str] = []
    for index, word in enumerate(words):
        x += word.space_before
        dy = 0.0
        if word.sup:
            dy = -style.size * 0.38
        elif word.sub:
            dy = style.size * 0.16
        segments.append(
            Segment(
                x=round(x, 2),
                text=word.text,
                key=word.key,
                link=word.link,
                underline=word.underline,
                strike=word.strike,
                dy=round(dy, 2),
                width=word.width,
                block_index=word.block_index,
                start=word.start,
                end=word.end,
            )
        )
        text_parts.append(word.text)
        x += word.width
        if index < len(words) - 1:
            x += extra
            text_parts.append(" ")
    height = _line_height(words, fonts, style)
    return Line(y=0.0, height=height, segments=segments, text="".join(text_parts))


def layout_document(document: Document, style: LayoutStyle, root) -> LayoutResult:
    fonts = FontSet(root, style)
    base = float(style.size)
    pages: list[Page] = []
    page = Page(index=0)
    page.first_block = 0
    pages.append(page)
    y = 0.0
    block_pages: dict[int, int] = {}

    def new_page(block_index: int) -> None:
        nonlocal page, y
        page = Page(index=len(pages), first_block=block_index)
        pages.append(page)
        y = 0.0

    def ensure_space(amount: float, block_index: int) -> None:
        nonlocal y
        if y > 0 and y + amount > style.height:
            new_page(block_index)

    for block_index, block in enumerate(document.blocks):
        if block.page_break and style.chapter_page_break and y > 0:
            new_page(block_index)
        margin_before = block.margin_before * base
        margin_after = block.margin_after * base
        if y > 0:
            y += margin_before

        if block.kind == "spacer":
            y += base * 0.9
            continue

        if block.kind == "separator":
            ensure_space(base * 2, block_index)
            page.rules.append(Rule(y=max(0.0, y + base * 0.4), width=style.width * 0.18))
            y += base * 1.3
            continue

        if block.kind == "image" and block.image:
            max_w = max(40.0, style.width - block.indent * base)
            max_h = style.height * 0.72
            width = block.image_w or 600
            height = block.image_h or 900
            scale = min(max_w / max(1, width), max_h / max(1, height), 1.8)
            target_w = max(1, int(width * scale))
            target_h = max(1, int(height * scale))
            if y > 0 and y + target_h > style.height:
                new_page(block_index)
            x = block.indent * base
            if block.align == "center":
                x += max(0.0, (style.width - x - target_w) / 2)
            page.images.append(PlacedImage(block.image, round(x, 1), round(y, 1), target_w, target_h))
            block_pages.setdefault(block_index, page.index)
            y += target_h + margin_after
            continue

        if not block.runs:
            y += margin_after
            continue

        indent, first_indent, align, _ = _block_geometry(block, style)
        justify = (align == "justify") and style.justify
        tokens = _tokenize(block, fonts, block_index)
        if not tokens:
            y += margin_after
            continue

        heading = int(block.kind[1]) if block.kind in ("h1", "h2", "h3", "h4") else 0
        base_key = fonts.key(heading=heading, bold=block.kind in ("subtitle",), small=block.small)
        # Оценка высоты для keep-with-next.
        estimate = _line_height([_Word("", base_key, 0)], fonts, style)

        if block.keep_with_next and y > 0 and y + estimate * 2.6 > style.height:
            new_page(block_index)

        lines: list[Line] = []
        words: list[_Word] = []
        pending_space = 0
        natural = 0.0
        first_line = True
        avail = max(40.0, style.width - indent - first_indent)
        line_avail = avail

        def flush(justify_line: bool) -> None:
            nonlocal words, pending_space, natural, first_line, avail, line_avail
            if not words:
                return
            line = _make_line(
                words, align, line_avail, indent + (first_indent if first_line else 0),
                fonts, style, justify=justify_line, first=first_line,
            )
            lines.append(line)
            words = []
            pending_space = 0
            natural = 0.0
            first_line = False
            avail = max(40.0, style.width - indent)
            line_avail = avail

        for token in tokens:
            if token is _BREAK:
                flush(False)
                continue
            if isinstance(token, tuple) and token and token[0] == "space":
                if words:
                    pending_space = fonts.space(token[1])
                continue
            word: _Word = token
            if word.width > line_avail and not words:
                pieces = _split_long_word(word, fonts, int(line_avail))
                for piece in pieces[:-1]:
                    words = [piece]
                    flush(False)
                word = pieces[-1]
                if not word.text:
                    continue
            needed = pending_space + word.width if words else word.width
            if words and natural + needed > line_avail:
                flush(justify)
            word.space_before = pending_space if words else 0
            words.append(word)
            natural += word.space_before + word.width
            pending_space = 0

        flush(False)

        if not lines:
            y += margin_after
            continue

        # Первая строка блока: фиксируем страницу.
        for line in lines:
            if y + line.height > style.height and y > 0:
                new_page(block_index)
            block_pages.setdefault(block_index, page.index)
            line.y = round(y, 1)
            page.lines.append(line)
            y += line.height
        y += margin_after

    # Подписываем страницы главами.
    chapter_positions = [chapter.position for chapter in document.chapters]
    for page in pages:
        index = bisect_right(chapter_positions, page.first_block) - 1
        if index >= 0:
            page.chapter = document.chapters[index].title
            page.chapter_level = document.chapters[index].level

    for chapter in document.chapters:
        chapter.page = block_pages.get(chapter.position, 0)

    page_first_blocks = [page.first_block for page in pages]
    return LayoutResult(
        pages=pages,
        block_pages=block_pages,
        chapters=document.chapters,
        page_first_blocks=page_first_blocks,
        fonts=fonts,
    )
