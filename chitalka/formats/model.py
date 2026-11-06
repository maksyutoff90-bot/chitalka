"""Модель содержимого книги: блоки, стили, главы."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

LINE_BREAK = "\u2028"  # принудительный перенос строки внутри абзаца


@dataclass
class Run:
    """Фрагмент текста с одинаковым оформлением."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    sup: bool = False
    sub: bool = False
    code: bool = False
    link: str = ""          # note:<id> | anchor:<id> | url:<адрес>
    color: str = ""         # необязательный цвет (например, для ссылок)

    def styled(self) -> bool:
        return bool(
            self.bold or self.italic or self.underline or self.strike
            or self.sup or self.sub or self.code or self.link
        )


@dataclass
class Block:
    """Абзац, заголовок, стихотворение, картинка или разделитель."""

    kind: str = "p"
    runs: list[Run] = field(default_factory=list)
    align: str = "left"                 # left | center | right | justify
    indent: float = 0.0                 # отступ слева, в em
    first_indent: float | None = None   # абзацный отступ, в em
    margin_before: float = 0.0          # в em
    margin_after: float = 0.0           # в em
    level: int = 0
    anchor: str = ""
    image: str = ""                     # путь к файлу изображения
    image_w: int = 0
    image_h: int = 0
    page_break: bool = False
    marker: str = ""                    # маркер списка
    keep_with_next: bool = False
    small: bool = False

    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    def is_text(self) -> bool:
        return bool(self.runs) and bool(self.text().strip())


@dataclass
class Chapter:
    title: str
    position: int          # индекс блока
    level: int = 1
    anchor: str = ""
    page: int = 0          # заполняется вёрсткой


@dataclass
class Document:
    """Разобранная книга, готовая к вёрстке."""

    title: str
    author: str = ""
    format: str = ""
    path: Path | None = None
    blocks: list[Block] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    notes: dict[str, list[Block]] = field(default_factory=dict)
    anchors: dict[str, int] = field(default_factory=dict)
    description: str = ""
    language: str = ""
    year: str = ""
    genre: str = ""
    series: str = ""
    page_count: int = 0        # для PDF
    pdf_path: Path | None = None

    def plain_text(self) -> str:
        return "\n".join(block.text() for block in self.blocks if block.is_text())

    def block_texts(self) -> list[str]:
        return [block.text() for block in self.blocks]


def normalize_runs(runs: Iterable[Run]) -> list[Run]:
    """Схлопывает пробелы HTML/XML и склеивает одинаковые фрагменты."""
    cleaned: list[Run] = []
    for run in runs:
        text = run.text.replace("\u00ad", "").replace("\ufeff", "")
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        while "  " in text:
            text = text.replace("  ", " ")
        if not text:
            continue
        if cleaned and _same_style(cleaned[-1], run):
            cleaned[-1].text += text
        else:
            clone = Run(
                text=text,
                bold=run.bold,
                italic=run.italic,
                underline=run.underline,
                strike=run.strike,
                sup=run.sup,
                sub=run.sub,
                code=run.code,
                link=run.link,
                color=run.color,
            )
            cleaned.append(clone)
    if cleaned:
        cleaned[0].text = cleaned[0].text.lstrip()
        cleaned[-1].text = cleaned[-1].text.rstrip()
    return [run for run in cleaned if run.text]


def _same_style(left: Run, right: Run) -> bool:
    return (
        left.bold == right.bold
        and left.italic == right.italic
        and left.underline == right.underline
        and left.strike == right.strike
        and left.sup == right.sup
        and left.sub == right.sub
        and left.code == right.code
        and left.link == right.link
        and left.color == right.color
    )


def join_text(blocks: Iterable[Block]) -> str:
    parts: list[str] = []
    for block in blocks:
        text = " ".join(block.text().split())
        if text:
            parts.append(text)
    return "\n".join(parts)


def clean_text(value: str, limit: int = 0) -> str:
    text = " ".join((value or "").split())
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip(" ,.;:—-") + "…"
    return text
