"""Разбор EPUB 2/3: метаданные, главы, текст, картинки."""

from __future__ import annotations

import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from lxml import etree, html as lxml_html

from ..config import IMAGES_DIR
from ..covers import book_key, save_cover_bytes
from ..genres import genre_label
from .model import (
    LINE_BREAK,
    Block,
    Chapter,
    Document,
    Run,
    clean_text,
    normalize_runs,
)

log = logging.getLogger(__name__)

DC = "{http://purl.org/dc/elements/1.1/}"
OPF = "{http://www.idpf.org/2007/opf}"
OPS = "{http://www.idpf.org/2007/ops}"

SKIP_TAGS = {"script", "style", "head", "meta", "link", "title", "svg", "noscript"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "aside", "main", "figure",
    "figcaption", "blockquote", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3",
    "h4", "h5", "h6", "pre", "table", "tr", "td", "th", "hr", "img", "body", "br",
}
INLINE_TAGS = {
    "a", "span", "em", "i", "strong", "b", "u", "s", "strike", "del", "sup", "sub",
    "small", "big", "code", "kbd", "mark", "cite", "q", "abbr", "font", "ruby", "rt",
    "rp", "bdi", "bdo", "wbr", "time", "dfn", "var", "samp", "ins",
}


def _tag(node) -> str:
    tag = getattr(node, "tag", "")
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    return tag.lower()


def _resolve(base_file: str, href: str) -> str:
    href = unquote((href or "").split("#")[0].strip())
    if not href:
        return ""
    if href.startswith("/"):
        href = href.lstrip("/")
    else:
        href = posixpath.join(posixpath.dirname(base_file), href)
    return posixpath.normpath(href)


def _fragment(href: str) -> str:
    return unquote(href.split("#", 1)[1]) if "#" in href else ""


class _EPUB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.zf = zipfile.ZipFile(path)
        self.names = {name.lower(): name for name in self.zf.namelist()}
        self.opf_path = self._find_opf()
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.opf = self._read_xml(self.opf_path)
        self.manifest: dict[str, dict] = {}
        self.spine: list[str] = []
        self.meta: dict[str, str] = {}
        self.cover_href = ""
        self._parse_opf()

    def close(self) -> None:
        try:
            self.zf.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ zip
    def has(self, name: str) -> bool:
        return name.lower() in self.names

    def read(self, name: str) -> bytes:
        actual = self.names.get(name.lower())
        if actual is None:
            raise KeyError(name)
        return self.zf.read(actual)

    def _read_xml(self, name: str):
        data = self.read(name)
        parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(data, parser=parser)
        if root is None:
            raise ValueError(f"Не удалось прочитать {name}")
        return root

    def _find_opf(self) -> str:
        if not self.has("META-INF/container.xml"):
            raise ValueError("В EPUB нет META-INF/container.xml")
        root = self._read_xml("META-INF/container.xml")
        for element in root.iter():
            if _tag(element) == "rootfile":
                full = element.get("full-path")
                if full:
                    return posixpath.normpath(unquote(full))
        raise ValueError("В EPUB не найден OPF-файл")

    def _parse_opf(self) -> None:
        metadata = None
        manifest = None
        spine = None
        for child in self.opf:
            tag = _tag(child)
            if tag == "metadata":
                metadata = child
            elif tag == "manifest":
                manifest = child
            elif tag == "spine":
                spine = child

        if metadata is not None:
            for element in metadata:
                tag = _tag(element)
                if tag in ("title", "creator", "language", "description", "subject", "date", "publisher"):
                    text = " ".join((element.text or "").split())
                    if not text:
                        continue
                    key = "author" if tag == "creator" else tag
                    if key in self.meta and key in ("author", "subject"):
                        self.meta[key] += ", " + text
                    else:
                        self.meta.setdefault(key, text)
                elif tag == "meta":
                    name = (element.get("name") or element.get("property") or "").lower()
                    content = element.get("content") or (element.text or "")
                    if name in ("calibre:series", "belongs-to-collection"):
                        self.meta.setdefault("series", " ".join(content.split()))

        if manifest is not None:
            for item in manifest:
                if _tag(item) != "item":
                    continue
                ident = item.get("id") or ""
                href = item.get("href") or ""
                if not ident or not href:
                    continue
                self.manifest[ident] = {
                    "id": ident,
                    "href": posixpath.normpath(posixpath.join(self.opf_dir, unquote(href))),
                    "media_type": item.get("media-type") or "",
                    "properties": (item.get("properties") or "").lower(),
                }
                if "cover-image" in (item.get("properties") or "").lower():
                    self.cover_href = self.manifest[ident]["href"]

        if spine is not None:
            for itemref in spine:
                if _tag(itemref) == "itemref":
                    ident = itemref.get("idref") or ""
                    if ident in self.manifest:
                        self.spine.append(ident)

        if not self.cover_href:
            meta = None
            if metadata is not None:
                for element in metadata:
                    if _tag(element) == "meta" and (element.get("name") or "").lower() == "cover":
                        meta = element.get("content") or ""
                        break
            if meta and meta in self.manifest:
                self.cover_href = self.manifest[meta]["href"]
        if not self.cover_href:
            for item in self.manifest.values():
                if item["media_type"].startswith("image/") and "cover" in item["href"].lower():
                    self.cover_href = item["href"]
                    break

    # ------------------------------------------------------------------ toc
    def toc_entries(self) -> list[tuple[str, str, str, int]]:
        """[(файл, фрагмент, заголовок, уровень)]"""
        # EPUB3 nav
        for item in self.manifest.values():
            if "nav" in item["properties"]:
                try:
                    return self._nav_entries(item["href"])
                except Exception:
                    log.debug("Не удалось разобрать nav", exc_info=True)
        # EPUB2 NCX
        for item in self.manifest.values():
            if item["media_type"] in ("application/x-dtbncx+xml", "application/ncx+xml") or item["href"].lower().endswith(".ncx"):
                try:
                    return self._ncx_entries(item["href"])
                except Exception:
                    log.debug("Не удалось разобрать NCX", exc_info=True)
        return []

    def _nav_entries(self, nav_path: str) -> list[tuple[str, str, str, int]]:
        root = lxml_html.fromstring(self.read(nav_path))
        nav = None
        for element in root.iter():
            if _tag(element) != "nav":
                continue
            etype = element.get(OPS + "type") or element.get("type") or ""
            if "toc" in etype.split():
                nav = element
                break
        if nav is None:
            nav = root.find(".//nav")
        if nav is None:
            nav = root
        entries: list[tuple[str, str, str, int]] = []

        def walk_list(container, level: int) -> None:
            for child in container:
                tag = _tag(child)
                if tag == "li":
                    label = None
                    for sub in child:
                        if _tag(sub) == "a":
                            label = " ".join("".join(sub.itertext()).split())
                            href = sub.get("href") or ""
                            if href and label:
                                entries.append(
                                    (_resolve(nav_path, href), _fragment(href), label, level)
                                )
                            break
                        if _tag(sub) == "span":
                            label = " ".join("".join(sub.itertext()).split())
                    for sub in child:
                        if _tag(sub) in ("ol", "ul"):
                            walk_list(sub, level + 1)
                elif tag in ("ol", "ul"):
                    walk_list(child, level)
                elif tag == "a":
                    label = " ".join("".join(child.itertext()).split())
                    href = child.get("href") or ""
                    if href and label:
                        entries.append((_resolve(nav_path, href), _fragment(href), label, level))

        walk_list(nav, 1)
        return entries

    def _ncx_entries(self, ncx_path: str) -> list[tuple[str, str, str, int]]:
        root = self._read_xml(ncx_path)
        entries: list[tuple[str, str, str, int]] = []

        def walk(point, level: int) -> None:
            for child in point:
                tag = _tag(child)
                if tag == "navpoint":
                    label = ""
                    for sub in child:
                        if _tag(sub) == "navlabel":
                            label = " ".join("".join(sub.itertext()).split())
                        elif _tag(sub) == "content":
                            src = sub.get("src") or ""
                            if src and label:
                                entries.append(
                                    (_resolve(ncx_path, src), _fragment(src), label, level)
                                )
                    walk(child, level + 1)

        for element in root.iter():
            if _tag(element) == "navmap":
                walk(element, 1)
                break
        return entries


# ------------------------------------------------------------------- метаданные
def _description_html(value: str) -> str:
    if not value:
        return ""
    try:
        fragment = lxml_html.fragment_fromstring(value, create_parent="div")
        text = fragment.text_content()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    return clean_text(text, 4000)


def parse_meta(path: Path) -> dict:
    book = _EPUB(path)
    try:
        meta = book.meta
        cover = ""
        if book.cover_href and book.has(book.cover_href):
            cover = save_cover_bytes(path, book.read(book.cover_href))
        subjects = meta.get("subject", "")
        year = meta.get("date", "")[:40]
        stat = path.stat()
        return {
            "path": str(path),
            "format": "epub",
            "title": clean_text(meta.get("title", "")) or path.stem,
            "author": meta.get("author", ""),
            "series": meta.get("series", ""),
            "genre": genre_label(subjects) if subjects else "",
            "year": year,
            "language": meta.get("language", ""),
            "description": _description_html(meta.get("description", "")),
            "cover": cover,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    finally:
        book.close()


# ------------------------------------------------------------------- документ
class _Images:
    def __init__(self, book: _EPUB, path: Path) -> None:
        self.book = book
        self.folder = IMAGES_DIR / book_key(path)
        self.cache: dict[str, tuple[str, int, int] | None] = {}

    def get(self, base_file: str, src: str) -> tuple[str, int, int] | None:
        src = (src or "").strip()
        if not src or src.startswith("data:"):
            return None
        target_name = _resolve(base_file, src)
        if not target_name or target_name in self.cache:
            return self.cache.get(target_name)
        if not self.book.has(target_name):
            self.cache[target_name] = None
            return None
        data = self.book.read(target_name)
        suffix = posixpath.splitext(target_name)[1].lower()
        if suffix not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            self.cache[target_name] = None
            return None
        safe = hashlib_name(target_name)
        target = self.folder / f"{safe}{suffix}"
        try:
            from PIL import Image

            if not target.exists() or target.stat().st_size < 32:
                self.folder.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            with Image.open(target) as image:
                width, height = image.size
                image.verify()
        except Exception:
            self.cache[target_name] = None
            return None
        if width < 2 or height < 2:
            self.cache[target_name] = None
            return None
        result = (str(target), int(width), int(height))
        self.cache[target_name] = result
        return result


def hashlib_name(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


@dataclass
class _Style:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    sup: bool = False
    sub: bool = False
    code: bool = False
    link: str = ""

    def clone(self, **kwargs) -> "_Style":
        values = {
            "bold": self.bold, "italic": self.italic, "underline": self.underline,
            "strike": self.strike, "sup": self.sup, "sub": self.sub,
            "code": self.code, "link": self.link,
        }
        values.update(kwargs)
        return _Style(**values)

    def fields(self) -> dict:
        return {
            "bold": self.bold, "italic": self.italic, "underline": self.underline,
            "strike": self.strike, "sup": self.sup, "sub": self.sub,
            "code": self.code, "link": self.link,
        }


class _Builder:
    def __init__(self, images: _Images, base_file: str) -> None:
        self.images = images
        self.base_file = base_file
        self.blocks: list[Block] = []
        self.runs: list[Run] = []
        self.anchors: dict[str, int] = {}

    def anchor(self, element) -> str:
        ident = element.get("id") or ""
        if ident:
            self.anchors[ident] = len(self.blocks)
        return ident

    def add_text(self, text: str, style: _Style) -> None:
        if text:
            self.runs.append(Run(text, **style.fields()))

    def add_break(self) -> None:
        self.runs.append(Run(LINE_BREAK))

    def flush(self, *, kind: str = "p", align: str = "left", indent: float = 0.0,
              first_indent: float | None = None, margin_before: float = 0.0,
              margin_after: float = 0.0, small: bool = False, marker: str = "") -> Block | None:
        runs = normalize_runs(self.runs)
        self.runs = []
        if not runs:
            return None
        block = Block(
            kind=kind, runs=runs, align=align, indent=indent, first_indent=first_indent,
            margin_before=margin_before, margin_after=margin_after, small=small,
            marker=marker,
        )
        self.blocks.append(block)
        return block

    def add_image(self, src: str) -> None:
        target = self.images.get(self.base_file, src)
        if not target:
            return
        self.flush()
        path, width, height = target
        self.blocks.append(
            Block(kind="image", image=path, image_w=width, image_h=height,
                  align="center", margin_before=0.7, margin_after=0.7)
        )


def _css(element) -> dict[str, str]:
    raw = element.get("style") or ""
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            result[key.strip().lower()] = value.strip().lower()
    return result


def _style_for(element, style: _Style) -> _Style:
    tag = _tag(element)
    css = _css(element)
    updates: dict = {}
    if tag in ("strong", "b"):
        updates["bold"] = True
    if tag in ("em", "i", "cite"):
        updates["italic"] = True
    if tag in ("u", "ins"):
        updates["underline"] = True
    if tag in ("s", "strike", "del"):
        updates["strike"] = True
    if tag == "sup":
        updates["sup"] = True
    if tag == "sub":
        updates["sub"] = True
    if tag in ("code", "kbd", "samp", "pre"):
        updates["code"] = True
    weight = css.get("font-weight", "")
    if weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600):
        updates["bold"] = True
    if css.get("font-style") in ("italic", "oblique"):
        updates["italic"] = True
    decoration = css.get("text-decoration", "")
    if "underline" in decoration:
        updates["underline"] = True
    if "line-through" in decoration:
        updates["strike"] = True
    valign = css.get("vertical-align", "")
    if valign == "super":
        updates["sup"] = True
    elif valign == "sub":
        updates["sub"] = True
    return style.clone(**updates) if updates else style


def _has_block_children(element) -> bool:
    for child in element:
        if _tag(child) in BLOCK_TAGS and _tag(child) not in ("br", "img"):
            return True
    return False


def _collect_inline(node, style: _Style, builder: _Builder) -> None:
    """Собирает строчное содержимое узла в текущий абзац."""
    if node.text:
        builder.add_text(node.text, style)
    for child in node:
        tag = _tag(child)
        if not tag:
            continue
        if tag in SKIP_TAGS:
            continue
        if tag == "br":
            builder.add_break()
        elif tag == "img":
            builder.add_image(child.get("src") or "")
            continue
        elif tag == "a":
            href = (child.get("href") or "").strip()
            link = ""
            if href.startswith("#"):
                link = "anchor:" + _fragment(href)
            elif href:
                if href.lower().startswith(("http://", "https://", "mailto:")):
                    link = "url:" + href
                else:
                    frag = _fragment(href)
                    link = "anchor:" + frag if frag else "ref:" + href
            _collect_inline(child, _style_for(child, style).clone(link=link), builder)
        elif tag in INLINE_TAGS:
            _collect_inline(child, _style_for(child, style), builder)
        elif tag in ("p", "div"):
            # Блочный элемент внутри строчного — маловероятно, но бывает.
            _collect_inline(child, style, builder)
            builder.add_break()
        else:
            _collect_inline(child, style, builder)
        if child.tail:
            builder.add_text(child.tail, style)


def _align_for(element, default: str = "left") -> str:
    css = _css(element)
    align = css.get("text-align", "")
    if align in ("center", "right", "justify"):
        return align
    name = (element.get("align") or "").lower()
    if name in ("center", "right", "justify"):
        return name
    return default


def _indent_for(element) -> float:
    css = _css(element)
    value = css.get("text-indent", "")
    match = re.match(r"(-?[\d.]+)\s*(em|rem|px)?", value)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2) or "em"
    if unit == "px":
        return number / 16.0
    return max(0.0, min(6.0, number))


class _Walker:
    def __init__(self, builder: _Builder) -> None:
        self.b = builder

    def walk(self, node, style: _Style, align: str = "left", indent: float = 0.0,
             list_marker: str = "") -> None:
        for child in node:
            tag = _tag(child)
            if not tag or tag in SKIP_TAGS:
                continue
            self.block(child, style, align, indent, list_marker)
        # Текст, оставшийся на уровне контейнера.
        if node.text and node.text.strip() and not list(node):
            self.b.add_text(node.text, style)
            self.b.flush(align=align, indent=indent)

    def block(self, el, parent_style: _Style, parent_align: str, indent: float,
              list_marker: str = "") -> None:
        tag = _tag(el)
        style = _style_for(el, parent_style)
        align = _align_for(el, parent_align)
        ident = self.b.anchor(el)

        if tag in ("p", "dt", "dd", "figcaption", "address"):
            _collect_inline(el, style, self.b)
            block = self.b.flush(
                kind="p", align=align, indent=indent,
                first_indent=_indent_for(el) or None,
                margin_before=0.15 if indent else 0.0,
                margin_after=0.15 if indent else 0.0,
            )
            if block and list_marker:
                block.runs.insert(0, Run(list_marker + "  "))
                block.indent = max(block.indent, 1.2)
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            _collect_inline(el, style.clone(bold=True), self.b)
            block = self.b.flush(
                kind=f"h{min(level, 4)}", align=align, indent=indent,
                margin_before=1.3 if level <= 2 else 1.0,
                margin_after=0.7,
            )
            if block:
                block.level = level
                block.page_break = level <= 1
                block.keep_with_next = True
            return

        if tag in ("div", "section", "article", "header", "footer", "aside", "main", "body", "figure"):
            if _has_block_children(el):
                if el.text and el.text.strip():
                    self.b.add_text(el.text, style)
                    self.b.flush(align=align, indent=indent)
                self.walk(el, style, align, indent)
                if tag == "figcaption" and self.b.runs:
                    self.b.flush(align="center", indent=indent)
            else:
                _collect_inline(el, style, self.b)
                block = self.b.flush(kind="p", align=align, indent=indent)
                if block and list_marker:
                    block.runs.insert(0, Run(list_marker + "  "))
            return

        if tag == "blockquote":
            if el.text and el.text.strip():
                self.b.add_text(el.text, style)
            self.walk(el, style.clone(italic=style.italic or False), align, indent + 1.5)
            if self.b.runs:
                self.b.flush(kind="cite", align="left", indent=indent + 1.5)
            for i, block in enumerate(self.b.blocks):
                if block.kind == "p" and block.indent >= indent + 1.5:
                    block.kind = "cite"
            return

        if tag in ("ul", "ol"):
            ordered = tag == "ol"
            number = 1
            for item in el:
                if _tag(item) != "li":
                    continue
                marker = f"{number}." if ordered else "•"
                number += 1
                self._list_item(item, style, align, indent, marker)
            return

        if tag == "li":
            self._list_item(el, style, align, indent, list_marker or "•")
            return

        if tag == "pre":
            text = el.text_content().replace("\r\n", "\n")
            lines = [line.rstrip() for line in text.split("\n")]
            runs: list[Run] = []
            for index, line in enumerate(lines):
                if index:
                    runs.append(Run(LINE_BREAK))
                runs.append(Run(line, code=True))
            runs = normalize_runs(runs)
            if runs:
                self.b.blocks.append(
                    Block(kind="code", runs=runs, indent=indent, small=True,
                          margin_before=0.6, margin_after=0.6, anchor=ident)
                )
            return

        if tag == "table":
            rows = []
            for row in el.iter():
                if _tag(row) != "tr":
                    continue
                cells = []
                header = False
                for cell in row:
                    if _tag(cell) in ("td", "th"):
                        header = header or _tag(cell) == "th"
                        cells.append(" ".join("".join(cell.itertext()).split()))
                if cells:
                    rows.append((header, cells))
            for header, cells in rows:
                self.b.blocks.append(
                    Block(kind="table", runs=[Run("   ".join(cells), bold=header)],
                          small=True, margin_before=0.1, margin_after=0.1,
                          anchor=ident if not self.b.blocks else "")
                )
            if rows:
                self.b.blocks[-1].margin_after = 0.7
            return

        if tag == "hr":
            self.b.blocks.append(Block(kind="separator", align="center",
                                       margin_before=1.0, margin_after=1.0))
            return

        if tag == "img":
            self.b.add_image(el.get("src") or "")
            return

        if tag == "br":
            self.b.add_break()
            return

        if tag in ("dl",):
            self.walk(el, style, align, indent)
            return

        # Неизвестный тег: если внутри блоки — обходим, иначе считаем абзацем.
        if _has_block_children(el):
            self.walk(el, style, align, indent)
        else:
            _collect_inline(el, style, self.b)
            self.b.flush(kind="p", align=align, indent=indent)

    def _list_item(self, el, style: _Style, align: str, indent: float, marker: str) -> None:
        start = len(self.b.blocks)
        if _has_block_children(el):
            if el.text and el.text.strip():
                self.b.add_text(el.text, style)
                block = self.b.flush(align=align, indent=indent + 1.6)
                if block:
                    block.runs.insert(0, Run(marker + "  "))
            for child in el:
                tag = _tag(child)
                if tag in ("ul", "ol"):
                    self.block(child, style, align, indent + 1.6)
                else:
                    self.block(child, style, align, indent + 1.6)
        else:
            _collect_inline(el, style, self.b)
            block = self.b.flush(align=align, indent=indent + 1.6)
            if block:
                block.runs.insert(0, Run(marker + "  "))
        if len(self.b.blocks) == start:
            return


def _chapter_title_from_html(root) -> str:
    for element in root.iter():
        tag = _tag(element)
        if tag in ("h1", "h2", "h3"):
            text = " ".join("".join(element.itertext()).split())
            if text:
                return text[:200]
    return ""


# ------------------------------------------------------------------ документ
def load_document(path: Path) -> Document:
    book = _EPUB(path)
    try:
        images = _Images(book, path)
        toc = book.toc_entries()
        toc_by_file: dict[str, list[tuple[str, str, str, int]]] = {}
        for file, frag, title, level in toc:
            toc_by_file.setdefault(file, []).append((frag, title, file, level))

        blocks: list[Block] = []
        chapters: list[Chapter] = []
        anchors: dict[str, int] = {}
        seen_chapters: set[tuple[int, str]] = set()

        spine_hrefs: list[str] = []
        for ident in book.spine:
            item = book.manifest.get(ident)
            if item and item["media_type"] in ("application/xhtml+xml", "text/html", "application/html"):
                spine_hrefs.append(item["href"])
        if not spine_hrefs:
            for item in book.manifest.values():
                if item["media_type"] in ("application/xhtml+xml", "text/html"):
                    spine_hrefs.append(item["href"])
        # Порядок манифеста может не совпадать со spine — сохраняем spine.
        spine_hrefs = list(dict.fromkeys(spine_hrefs))

        for index, href in enumerate(spine_hrefs):
            try:
                data = book.read(href)
            except KeyError:
                continue
            try:
                root = lxml_html.fromstring(data)
            except Exception:
                log.debug("Не удалось разобрать %s", href, exc_info=True)
                continue
            builder = _Builder(images, href)
            body = None
            for element in root.iter():
                if _tag(element) == "body":
                    body = element
                    break
            if body is None:
                body = root
            walker = _Walker(builder)
            # Текст на уровне body.
            if body.text and body.text.strip():
                builder.add_text(body.text, _Style())
                builder.flush()
            walker.walk(body, _Style())
            if builder.runs:
                builder.flush()
            # Обложка и чисто иллюстративные страницы не участвуют в чтении.
            if index == 0 and not any(block.is_text() for block in builder.blocks):
                continue
            if not builder.blocks and not toc_by_file.get(href):
                continue
            offset = len(blocks)
            for key, value in builder.anchors.items():
                anchors[key] = value + offset
            blocks.extend(builder.blocks)

            # Главы из оглавления.
            entries = toc_by_file.get(href, [])
            for frag, title, _, level in entries:
                position = offset + (builder.anchors.get(frag, 0) if frag else 0)
                key = (position, title)
                if key in seen_chapters:
                    continue
                seen_chapters.add(key)
                chapters.append(Chapter(title, position, max(1, min(level, 4)), frag))

            # Если оглавления нет — берём заголовки самого документа.
            if not entries:
                for block_index, block in enumerate(builder.blocks):
                    if block.kind in ("h1", "h2") and block.text().strip():
                        chapters.append(
                            Chapter(block.text().strip(), offset + block_index, 1, block.anchor)
                        )
                if not any(block.kind.startswith("h") for block in builder.blocks):
                    title = _chapter_title_from_html(root) or f"Глава {index + 1}"
                    chapters.append(Chapter(title, offset, 1, ""))

        # Упорядочить и убрать главы-дубли по позиции.
        clean: list[Chapter] = []
        for chapter in sorted(chapters, key=lambda c: (c.position, c.level)):
            if clean and chapter.position == clean[-1].position:
                if chapter.title == clean[-1].title:
                    continue
            clean.append(chapter)
        chapters = clean
        if not chapters and blocks:
            chapters.append(Chapter(clean_text(book.meta.get("title", "")) or path.stem, 0, 1, ""))
        for chapter in chapters:
            chapter.position = max(0, min(chapter.position, len(blocks) - 1))

        meta = book.meta
        return Document(
            title=clean_text(meta.get("title", "")) or path.stem,
            author=meta.get("author", ""),
            format="epub",
            path=path,
            blocks=blocks,
            chapters=chapters,
            notes={},
            anchors=anchors,
            description=_description_html(meta.get("description", "")),
            language=meta.get("language", ""),
            year=meta.get("date", "")[:40],
            genre=genre_label(meta.get("subject", "")) if meta.get("subject") else "",
            series=meta.get("series", ""),
        )
    finally:
        book.close()
