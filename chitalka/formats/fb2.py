"""Разбор FB2 (в том числе fb2.zip): метаданные, текст, иллюстрации, сноски."""

from __future__ import annotations

import base64
import logging
import re
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image

from ..config import IMAGES_DIR
from ..covers import book_key, save_cover_bytes
from ..genres import genre_label
from .model import Block, Chapter, Document, Run, clean_text, join_text, normalize_runs

log = logging.getLogger(__name__)

XLINK = "{http://www.w3.org/1999/xlink}href"
IMAGE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _children(el, name: str):
    return [child for child in el if _local(child.tag) == name]


def _first(el, name: str):
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _attr(el, name: str) -> str:
    if el is None:
        return ""
    value = el.get(name)
    if value:
        return value
    for key, item in el.attrib.items():
        if _local(key) == name:
            return item
    return ""


def _href(el) -> str:
    return el.get(XLINK) or el.get("href") or _attr(el, "href") or ""


def read_fb2_bytes(path: Path) -> bytes:
    """Достаёт XML из .fb2 или .fb2.zip."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith(".fb2") and not name.startswith("__MACOSX")
            ]
            if not names:
                raise ValueError("В архиве нет файла .fb2")
            names.sort(key=lambda name: (len(name), name))
            return archive.read(names[0])
    return path.read_bytes()


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        recover=True,
        huge_tree=True,
        resolve_entities=False,
        no_network=True,
        remove_comments=True,
        remove_pis=True,
    )


def _parse_xml(data: bytes):
    root = etree.fromstring(data, parser=_parser())
    if root is None:
        raise ValueError("Не удалось прочитать XML книги")
    return root


def _author_name(author) -> str:
    if author is None:
        return ""
    parts: list[str] = []
    for tag in ("first-name", "middle-name", "last-name"):
        node = _first(author, tag)
        if node is not None and node.text:
            parts.append(node.text.strip())
    if not parts:
        nick = _first(author, "nickname")
        if nick is not None and nick.text:
            parts.append(nick.text.strip())
    return " ".join(part for part in parts if part)


def _authors(title_info) -> str:
    names: list[str] = []
    for author in _children(title_info, "author"):
        name = _author_name(author)
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _annotation_text(title_info) -> str:
    annotation = _first(title_info, "annotation")
    if annotation is None:
        return ""
    paragraphs: list[str] = []
    for element in annotation.iter():
        if _local(element.tag) in ("p", "subtitle") and element.text:
            text = "".join(element.itertext()).strip()
            if text:
                paragraphs.append(text)
    if not paragraphs:
        paragraphs = ["".join(annotation.itertext()).strip()]
    return clean_text("\n".join(paragraphs), 4000)


def _cover_bytes(root, binaries: dict[str, tuple[bytes, str]]) -> bytes | None:
    description = _first(root, "description")
    if description is None:
        return None
    title_info = _first(description, "title-info")
    coverpage = _first(title_info, "coverpage") if title_info is not None else None
    if coverpage is None:
        return None
    image = _first(coverpage, "image")
    if image is None:
        return None
    ref = _href(image).lstrip("#")
    entry = binaries.get(ref)
    if entry:
        return entry[0]
    return None


def binaries_map(root) -> dict[str, tuple[bytes, str]]:
    result: dict[str, tuple[bytes, str]] = {}
    for binary in root.iter():
        if _local(binary.tag) != "binary":
            continue
        ident = binary.get("id") or ""
        if not ident:
            continue
        content_type = (binary.get("content-type") or "").lower()
        try:
            data = base64.b64decode(re.sub(r"\s+", "", binary.text or ""), validate=False)
        except Exception:
            continue
        if len(data) < 32:
            continue
        result[ident] = (data, content_type)
    return result


def parse_meta(path: Path) -> dict:
    data = read_fb2_bytes(path)
    root = _parse_xml(data)
    description = _first(root, "description")
    title_info = _first(description, "title-info") if description is not None else None
    if title_info is None:
        raise ValueError("В FB2 нет описания книги")

    title_node = _first(title_info, "book-title")
    title = clean_text(title_node.text if title_node is not None else "") or path.stem
    genres = []
    for genre in _children(title_info, "genre"):
        if genre.text and genre.text.strip():
            genres.append(genre.text.strip())
    date_node = _first(title_info, "date")
    year = ""
    if date_node is not None:
        year = clean_text(date_node.get("value") or date_node.text or "")[:40]
    sequence = _first(title_info, "sequence")
    series = clean_text(sequence.get("name")) if sequence is not None else ""
    lang_node = _first(title_info, "lang")
    language = clean_text(lang_node.text if lang_node is not None else "")

    binaries = binaries_map(root)
    cover = ""
    cover_data = _cover_bytes(root, binaries)
    if cover_data:
        cover = save_cover_bytes(path, cover_data)

    stat = path.stat()
    return {
        "path": str(path),
        "format": "fb2",
        "title": title,
        "author": _authors(title_info),
        "series": series,
        "genre": genre_label(genres),
        "year": year,
        "language": language,
        "description": _annotation_text(title_info),
        "cover": cover,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


# ------------------------------------------------------------------ документ
class _Images:
    def __init__(self, path: Path, binaries: dict[str, tuple[bytes, str]]) -> None:
        self.path = path
        self.binaries = binaries
        self.folder = IMAGES_DIR / book_key(path)
        self.cache: dict[str, tuple[str, int, int]] = {}

    def get(self, ident: str) -> tuple[str, int, int] | None:
        ident = (ident or "").lstrip("#")
        if not ident:
            return None
        if ident in self.cache:
            return self.cache[ident]
        entry = self.binaries.get(ident)
        if not entry:
            return None
        data, content_type = entry
        if "svg" in content_type:
            return None
        ext = IMAGE_EXT.get(content_type)
        if not ext:
            for candidate in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                if ident.lower().endswith(candidate):
                    ext = ".jpg" if candidate == ".jpeg" else candidate
                    break
            else:
                ext = ".jpg"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ident)[:80] or "image"
        stem = safe.rsplit(".", 1)[0] if "." in safe else safe
        target = self.folder / f"{stem}{ext}"
        try:
            if not target.exists() or target.stat().st_size < 32:
                self.folder.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            with Image.open(target) as image:
                width, height = image.size
                image.verify()
        except Exception:
            return None
        if width < 2 or height < 2:
            return None
        result = (str(target), int(width), int(height))
        self.cache[ident] = result
        return result


class _Style:
    __slots__ = ("bold", "italic", "underline", "strike", "sup", "sub", "code", "link")

    def __init__(self, **kwargs) -> None:
        self.bold = kwargs.get("bold", False)
        self.italic = kwargs.get("italic", False)
        self.underline = kwargs.get("underline", False)
        self.strike = kwargs.get("strike", False)
        self.sup = kwargs.get("sup", False)
        self.sub = kwargs.get("sub", False)
        self.code = kwargs.get("code", False)
        self.link = kwargs.get("link", "")

    def clone(self, **kwargs) -> "_Style":
        values = {slot: getattr(self, slot) for slot in self.__slots__}
        values.update(kwargs)
        return _Style(**values)


def _collect_inline(el, style: _Style, runs: list[Run]) -> None:
    if el.text:
        runs.append(Run(el.text, **_style_fields(style)))
    for child in el:
        tag = _local(child.tag)
        if tag == "image":
            if child.tail:
                runs.append(Run(child.tail, **_style_fields(style)))
            continue
        if tag == "a":
            href = _href(child)
            link = ""
            if href.startswith("#"):
                link = "anchor:" + href[1:]
            elif href:
                link = "url:" + href
            _collect_inline(child, style.clone(link=link), runs)
        elif tag in ("strong", "b"):
            _collect_inline(child, style.clone(bold=True), runs)
        elif tag in ("emphasis", "em", "i"):
            _collect_inline(child, style.clone(italic=True), runs)
        elif tag in ("strikethrough", "strike", "del", "s"):
            _collect_inline(child, style.clone(strike=True), runs)
        elif tag in ("underline", "u"):
            _collect_inline(child, style.clone(underline=True), runs)
        elif tag == "sup":
            _collect_inline(child, style.clone(sup=True), runs)
        elif tag == "sub":
            _collect_inline(child, style.clone(sub=True), runs)
        elif tag == "code":
            _collect_inline(child, style.clone(code=True), runs)
        elif tag == "style":
            _collect_inline(child, style, runs)
        else:
            _collect_inline(child, style, runs)
        if child.tail:
            runs.append(Run(child.tail, **_style_fields(style)))


def _style_fields(style: _Style) -> dict:
    return {
        "bold": style.bold,
        "italic": style.italic,
        "underline": style.underline,
        "strike": style.strike,
        "sup": style.sup,
        "sub": style.sub,
        "code": style.code,
        "link": style.link,
    }


def _text_of(el) -> str:
    if el is None:
        return ""
    parts: list[str] = []
    for paragraph in el.iter():
        tag = _local(paragraph.tag)
        if tag in ("p", "v", "subtitle", "text-author"):
            text = " ".join("".join(paragraph.itertext()).split())
            if text:
                parts.append(text)
    if not parts:
        text = " ".join("".join(el.itertext()).split())
        if text:
            parts.append(text)
    return " ".join(parts)


def _paragraph(el, *, kind: str = "p", align: str = "left", style: _Style | None = None,
               indent: float = 0.0, first_indent: float | None = None,
               margin_before: float = 0.0, margin_after: float = 0.0) -> Block:
    runs: list[Run] = []
    _collect_inline(el, style or _Style(), runs)
    return Block(
        kind=kind,
        runs=normalize_runs(runs),
        align=align,
        indent=indent,
        first_indent=first_indent,
        margin_before=margin_before,
        margin_after=margin_after,
    )


def _heading(el, level: int, anchor: str) -> Block | None:
    text = _text_of(el)
    if not text:
        return None
    return Block(
        kind=f"h{min(level, 4)}",
        runs=[Run(text)],
        align="left",
        margin_before=1.4 if level <= 1 else 1.0,
        margin_after=0.8,
        level=level,
        anchor=anchor,
        page_break=level <= 1,
        keep_with_next=True,
    )


def _epigraph(el, notes_images) -> list[Block]:
    blocks: list[Block] = []
    for child in el:
        tag = _local(child.tag)
        if tag == "p":
            block = _paragraph(
                child, kind="epigraph", align="right", style=_Style(italic=True),
                indent=2.0, margin_before=0.2, margin_after=0.2,
            )
            if block.runs:
                blocks.append(block)
        elif tag == "text-author":
            block = _paragraph(child, kind="epigraph_author", align="right", indent=2.0)
            if block.runs:
                blocks.append(block)
        elif tag == "poem":
            blocks.extend(_poem(child, notes_images))
    if blocks:
        blocks[0].margin_before = max(blocks[0].margin_before, 0.6)
        blocks[-1].margin_after = max(blocks[-1].margin_after, 0.9)
    return blocks


def _poem(el, notes_images) -> list[Block]:
    blocks: list[Block] = []

    def stanza_runs(stanza) -> list[Run]:
        runs: list[Run] = []
        for verse in _children(stanza, "v"):
            line_runs: list[Run] = []
            _collect_inline(verse, _Style(), line_runs)
            cleaned = normalize_runs(line_runs)
            if not cleaned:
                continue
            if runs:
                runs.append(Run("\n"))
            runs.extend(cleaned)
        return runs

    def add_stanza(stanza) -> None:
        runs = stanza_runs(stanza)
        if not runs:
            return
        blocks.append(
            Block(
                kind="verse",
                runs=runs,
                indent=2.0,
                margin_before=0.45 if not blocks else 0.25,
                margin_after=0.55,
            )
        )

    for child in el:
        tag = _local(child.tag)
        if tag == "stanza":
            add_stanza(child)
        elif tag == "v":
            runs: list[Run] = []
            _collect_inline(child, _Style(), runs)
            cleaned = normalize_runs(runs)
            if cleaned:
                if blocks and blocks[-1].kind == "verse":
                    blocks[-1].runs.append(Run("\n"))
                    blocks[-1].runs.extend(cleaned)
                else:
                    blocks.append(Block(kind="verse", runs=cleaned, indent=2.0,
                                        margin_before=0.45, margin_after=0.55))
    author = _first(el, "text-author")
    if author is not None:
        block = _paragraph(author, kind="verse_author", align="right", indent=2.0,
                           margin_after=0.8)
        if block.runs:
            blocks.append(block)
    return blocks


def _cite(el, notes_images) -> list[Block]:
    blocks: list[Block] = []
    for child in el:
        tag = _local(child.tag)
        if tag == "p":
            block = _paragraph(child, kind="cite", style=_Style(italic=True), indent=1.6)
            if block.runs:
                blocks.append(block)
        elif tag == "poem":
            blocks.extend(_poem(child, notes_images))
        elif tag == "text-author":
            block = _paragraph(child, kind="cite_author", align="right", indent=1.6)
            if block.runs:
                blocks.append(block)
    if blocks:
        blocks[0].margin_before = max(blocks[0].margin_before, 0.6)
        blocks[-1].margin_after = max(blocks[-1].margin_after, 0.8)
    return blocks


def _table(el) -> list[Block]:
    blocks: list[Block] = []
    rows = list(el.iter())
    for row in rows:
        if _local(row.tag) != "tr":
            continue
        cells: list[str] = []
        for cell in row:
            if _local(cell.tag) in ("td", "th"):
                text = " ".join("".join(cell.itertext()).split())
                cells.append(text)
        if not cells:
            continue
        text = "   ".join(cells)
        blocks.append(
            Block(
                kind="table",
                runs=[Run(text, bold=(_local(row.tag) == "th"))],
                small=True,
                margin_before=0.2,
                margin_after=0.2,
            )
        )
    if blocks:
        blocks[0].margin_before = 0.8
        blocks[-1].margin_after = 0.8
    return blocks


def _image_block(el, images: _Images) -> Block | None:
    target = images.get(_href(el))
    if not target:
        return None
    path, width, height = target
    return Block(
        kind="image",
        image=path,
        image_w=width,
        image_h=height,
        align="center",
        margin_before=0.8,
        margin_after=0.8,
    )


def _spacer() -> Block:
    return Block(kind="spacer", margin_before=0.3, margin_after=0.3)


def parse_blocks(container, images: _Images, *, level: int = 1) -> tuple[list[Block], list[Chapter], dict[str, int]]:
    blocks: list[Block] = []
    chapters: list[Chapter] = []
    anchors: dict[str, int] = {}

    def register_anchor(el) -> str:
        ident = el.get("id") or ""
        if ident:
            anchors[ident] = len(blocks)
        return ident

    def walk_section(section, depth: int) -> None:
        anchor = register_anchor(section)
        title = None
        for child in section:
            if _local(child.tag) == "title":
                title = child
                break
        if title is not None:
            block = _heading(title, depth, anchor)
            if block is not None:
                block.page_break = depth <= 2
                chapters.append(Chapter(block.text(), len(blocks), depth, anchor))
                anchors[anchor or f"__chapter{len(blocks)}"] = len(blocks)
                blocks.append(block)

        for child in section:
            tag = _local(child.tag)
            if tag == "title":
                continue
            if tag == "section":
                walk_section(child, depth + 1)
            elif tag == "p":
                register_anchor(child)
                block = _paragraph(child)
                if block.runs:
                    blocks.append(block)
            elif tag == "subtitle":
                register_anchor(child)
                block = _paragraph(
                    child, kind="subtitle", style=_Style(bold=True, italic=True),
                    margin_before=0.7, margin_after=0.5,
                )
                if block.runs:
                    blocks.append(block)
            elif tag == "epigraph":
                blocks.extend(_epigraph(child, images))
            elif tag == "cite":
                blocks.extend(_cite(child, images))
            elif tag == "poem":
                blocks.extend(_poem(child, images))
            elif tag == "image":
                block = _image_block(child, images)
                if block:
                    blocks.append(block)
            elif tag == "table":
                blocks.extend(_table(child))
            elif tag == "empty-line":
                blocks.append(_spacer())
            elif tag in ("annotation", "text-author"):
                block = _paragraph(child, kind="annotation" if tag == "annotation" else "p",
                                  style=_Style(italic=(tag == "annotation")))
                if block.runs:
                    blocks.append(block)

    for child in container:
        tag = _local(child.tag)
        if tag == "section":
            walk_section(child, level)
        elif tag == "title":
            continue
        elif tag == "epigraph":
            blocks.extend(_epigraph(child, images))
        elif tag == "image":
            block = _image_block(child, images)
            if block:
                blocks.append(block)
        elif tag in ("p", "subtitle"):
            block = _paragraph(child, kind="subtitle" if tag == "subtitle" else "p")
            if block.runs:
                blocks.append(block)
        elif tag in ("cite", "poem", "table", "empty-line"):
            if tag == "cite":
                blocks.extend(_cite(child, images))
            elif tag == "poem":
                blocks.extend(_poem(child, images))
            elif tag == "table":
                blocks.extend(_table(child))
            else:
                blocks.append(_spacer())

    return blocks, chapters, anchors


def load_document(path: Path) -> Document:
    data = read_fb2_bytes(path)
    root = _parse_xml(data)
    description = _first(root, "description")
    title_info = _first(description, "title-info") if description is not None else None
    if title_info is None:
        raise ValueError("В FB2 нет описания книги")

    title_node = _first(title_info, "book-title")
    title = clean_text(title_node.text if title_node is not None else "") or path.stem
    genres = [
        genre.text.strip()
        for genre in _children(title_info, "genre")
        if genre.text and genre.text.strip()
    ]
    date_node = _first(title_info, "date")
    year = ""
    if date_node is not None:
        year = clean_text(date_node.get("value") or date_node.text or "")[:40]
    sequence = _first(title_info, "sequence")
    series = clean_text(sequence.get("name")) if sequence is not None else ""
    lang_node = _first(title_info, "lang")
    language = clean_text(lang_node.text if lang_node is not None else "")

    binaries = binaries_map(root)
    images = _Images(path, binaries)

    blocks: list[Block] = []
    chapters: list[Chapter] = []
    anchors: dict[str, int] = {}
    notes: dict[str, list[Block]] = {}

    for body in _children(root, "body"):
        name = (body.get("name") or "").lower()
        if name == "notes":
            for section in _children(body, "section"):
                ident = section.get("id") or ""
                note_blocks, _, _ = parse_blocks(section, images, level=4)
                # В сноске не нужен заголовок-раздел, только текст.
                note_blocks = [
                    block for block in note_blocks
                    if block.kind not in ("h1", "h2", "h3", "h4")
                ]
                if ident:
                    notes[ident] = note_blocks
            continue
        body_blocks, body_chapters, body_anchors = parse_blocks(body, images, level=1)
        offset = len(blocks)
        for chapter in body_chapters:
            chapter.position += offset
            chapters.append(chapter)
        for key, value in body_anchors.items():
            anchors[key] = value + offset
        blocks.extend(body_blocks)

    # Если глав нет — сделаем одну, чтобы был хоть какой-то ориентир.
    if not chapters and blocks:
        chapters.append(Chapter(title, 0, 1, ""))

    # Нумеруем главы, если заголовков нет вовсе.
    for index, chapter in enumerate(chapters):
        chapter.position = max(0, min(chapter.position, len(blocks) - 1))

    return Document(
        title=title,
        author=_authors(title_info),
        format="fb2",
        path=path,
        blocks=blocks,
        chapters=chapters,
        notes=notes,
        anchors=anchors,
        description=_annotation_text(title_info),
        language=language,
        year=year,
        genre=genre_label(genres),
        series=series,
    )
