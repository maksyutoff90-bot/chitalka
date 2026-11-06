"""TXT: определение кодировки, разбиение на главы и абзацы."""

from __future__ import annotations

import re
from pathlib import Path

from ..genres import genre_label  # noqa: F401  (единый импорт для метаданных)
from .model import Block, Chapter, Document, Run, clean_text, normalize_runs

CHAPTER_RE = re.compile(
    r"^\s*(?:(?:глава|часть|книга|том|пролог|эпилог|эпиграф|вступление|предисловие|"
    r"послесловие|chapter|part|book|prologue|epilogue)\b.{0,110}"
    r"|(?:[IVXLCDM]{1,7}|\d{1,3})[.)]?"
    r"|(?:Глава|Часть)\s+[A-Za-zА-Яа-я0-9-]+.{0,80})\s*$",
    re.IGNORECASE,
)

AUTHOR_LINE = re.compile(r"^\s*(?:автор|author)\s*[:\-—]\s*(.{2,80})$", re.IGNORECASE)
TITLE_LINE = re.compile(r"^\s*(?:название|title)\s*[:\-—]\s*(.{2,140})$", re.IGNORECASE)


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    sample = data[:200_000]
    candidates = ["utf-8", "cp1251", "koi8-r", "cp866", "iso-8859-5"]
    best, best_score = "utf-8", -1
    for encoding in candidates:
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError as exc:
            score = exc.start / max(1, len(sample)) * 100
            # Даже частично декодировавшийся cp1251 обычно лучше utf-8.
            if encoding != "utf-8":
                score = max(score, 0)
            if score > best_score:
                best, best_score = encoding, score
            continue
        score = 100 - text.count("\ufffd") * 10
        cyrillic = sum(1 for char in text if "а" <= char.lower() <= "я" or char == "ё")
        score += min(30, cyrillic / max(1, len(text)) * 100)
        if score > best_score:
            best, best_score = encoding, score
    if best_score < 20:
        try:
            import chardet

            guess = chardet.detect(sample)
            if guess and guess.get("encoding"):
                return str(guess["encoding"])
        except Exception:
            pass
    return best


def read_text(path: Path) -> str:
    data = path.read_bytes()
    encoding = detect_encoding(data)
    try:
        text = data.decode(encoding, errors="replace")
    except LookupError:
        text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
    return text


def _name_parts(path: Path) -> tuple[str, str]:
    stem = clean_text(path.stem)
    match = re.match(r"^(.{2,70}?)\s*[-–—]\s*(.{2,160})$", stem)
    if match:
        return clean_text(match.group(2)), clean_text(match.group(1))
    return stem, ""


def parse_meta(path: Path) -> dict:
    title, author = _name_parts(path)
    text = ""
    try:
        data = path.read_bytes()[:120_000]
        text = data.decode(detect_encoding(data), errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        pass
    head = [line.strip() for line in text.split("\n")[:40] if line.strip()]
    for line in head[:10]:
        match = AUTHOR_LINE.match(line)
        if match and not author:
            author = clean_text(match.group(1))
            break
    for line in head[:10]:
        match = TITLE_LINE.match(line)
        if match:
            title = clean_text(match.group(1))
            break
    if not author:
        for line in head[:5]:
            match = AUTHOR_LINE.match(line)
            if match:
                author = clean_text(match.group(1))
                break
    description = ""
    # Первый содержательный абзац — как аннотация, если он короткий.
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paragraphs:
        first = paragraphs[0]
        if 80 <= len(first) <= 600 and not CHAPTER_RE.match(first) and not AUTHOR_LINE.match(first):
            description = clean_text(first, 600)
    stat = path.stat()
    return {
        "path": str(path),
        "format": "txt",
        "title": title,
        "author": author,
        "series": "",
        "genre": "",
        "year": "",
        "language": "ru",
        "description": description,
        "cover": "",
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def _looks_like_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 90:
        return False
    if CHAPTER_RE.match(text):
        return True
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 3:
        return False
    upper = sum(1 for char in letters if char.isupper())
    if upper / len(letters) > 0.85 and not text.endswith((".", "!", "?", ",", ";", ":")):
        if text.startswith(("—", "–", "-")):
            return False
        return True
    return False


def load_document(path: Path) -> Document:
    text = read_text(path)
    title, author = _name_parts(path)
    lines = text.split("\n")

    blocks: list[Block] = []
    chapters: list[Chapter] = []
    first_heading_seen = False

    # Выкидываем служебные строки "Автор:"/"Название:" из начала.
    start = 0
    for index, line in enumerate(lines[:12]):
        stripped = line.strip()
        if not stripped:
            continue
        if AUTHOR_LINE.match(stripped) or TITLE_LINE.match(stripped):
            if AUTHOR_LINE.match(stripped) and not author:
                match = AUTHOR_LINE.match(stripped)
                if match:
                    author = clean_text(match.group(1))
            if TITLE_LINE.match(stripped):
                match = TITLE_LINE.match(stripped)
                if match:
                    title = clean_text(match.group(1))
            start = index + 1
        elif index == 0 and stripped.lower() == title.lower():
            start = index + 1
        elif author and stripped.lower() == author.lower():
            # Строка с автором сразу после заголовка.
            start = index + 1
        else:
            break

    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        joined = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph.clear()
        joined = " ".join(joined.split())
        if not joined:
            return
        runs = normalize_runs([Run(joined)])
        if runs:
            blocks.append(Block(kind="p", runs=runs))

    def add_heading(line: str) -> None:
        clean = " ".join(line.split())
        if not clean:
            return
        flush_paragraph()
        level = 1
        if CHAPTER_RE.match(clean) and re.match(r"^\s*часть|^\s*part|^\s*книга|^\s*book", clean, re.I):
            level = 1
        blocks.append(
            Block(
                kind=f"h{min(level, 2)}",
                runs=[Run(clean)],
                margin_before=1.4,
                margin_after=0.8,
                page_break=True,
                keep_with_next=True,
                anchor=f"ch{len(chapters)}",
            )
        )
        chapters.append(Chapter(clean, len(blocks) - 1, level, f"ch{len(chapters)}"))

    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if _looks_like_heading(stripped) and (not paragraph or len(paragraph) <= 2):
            add_heading(stripped)
            first_heading_seen = True
            continue
        # Строка-заголовок внутри текста (после пустой строки) — тоже глава.
        if _looks_like_heading(stripped) and not paragraph:
            add_heading(stripped)
            first_heading_seen = True
            continue
        paragraph.append(stripped)
        # Очень длинные абзацы без пустых строк режем, чтобы не зависнуть.
        if sum(len(part) for part in paragraph) > 12_000:
            flush_paragraph()

    flush_paragraph()

    if not blocks:
        blocks.append(Block(kind="p", runs=[Run("Файл пуст.")], align="center"))

    if not chapters:
        chapters.append(Chapter(title, 0, 1, ""))
    elif not first_heading_seen:
        chapters.insert(0, Chapter(title, 0, 1, ""))

    return Document(
        title=title,
        author=author,
        format="txt",
        path=path,
        blocks=blocks,
        chapters=chapters,
        description=parse_meta(path)["description"],
        language="ru",
    )
