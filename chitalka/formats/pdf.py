"""PDF: метаданные, обложка, постраничный рендер и поиск (PDFium)."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from ..covers import save_cover_bytes
from .model import Chapter, Document, clean_text

import pypdfium2 as pdfium
from pypdfium2 import PdfiumError


def _year(value: str) -> str:
    match = re.search(r"(19|20)\d{2}", value or "")
    return match.group(0) if match else ""


def open_pdf(path: Path):
    try:
        return pdfium.PdfDocument(str(path))
    except PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message or "pass" in message:
            raise ValueError("PDF защищён паролем") from exc
        raise
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "password" in message or "pass" in message:
            raise ValueError("PDF защищён паролем") from exc
        raise


def _page_count(doc) -> int:
    return int(len(doc))


def render_cover(path: Path) -> str:
    doc = open_pdf(path)
    try:
        if _page_count(doc) == 0:
            return ""
        page = doc.get_page(0)
        width, height = page.get_size()
        scale = min(3.0, 1000.0 / max(1.0, float(height)))
        image = page.render(scale=scale).to_pil()
        return save_cover_bytes(path, _png_bytes(image))
    finally:
        doc.close()


def _png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def parse_meta(path: Path) -> dict:
    doc = open_pdf(path)
    try:
        meta = doc.get_metadata_dict() or {}
        title = clean_text(meta.get("Title", "")) or path.stem
        author = clean_text(meta.get("Author", ""))
        description = clean_text(meta.get("Subject", ""), 1000)
        year = _year(meta.get("CreationDate", ""))
        stat = path.stat()
        return {
            "path": str(path),
            "format": "pdf",
            "title": title,
            "author": author,
            "series": "",
            "genre": "",
            "year": year,
            "language": "",
            "description": description,
            "cover": render_cover(path),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    finally:
        doc.close()


class PdfBook:
    """Ленивая обёртка для чтения PDF через PDFium."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.doc = open_pdf(path)
        self.page_count = _page_count(self.doc)
        self._text_cache: dict[int, str] = {}
        self._words_cache: dict[int, list[tuple[float, float, float, float, str, int, int, int]]] = {}
        self._image_cache: dict[tuple[int, int], Image.Image] = {}
        self._size_cache: dict[int, tuple[float, float]] = {}

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    def title(self) -> str:
        meta = self.doc.get_metadata_dict() or {}
        return clean_text(meta.get("Title", "")) or self.path.stem

    def page_size(self, index: int) -> tuple[float, float]:
        index = max(0, min(self.page_count - 1, int(index)))
        cached = self._size_cache.get(index)
        if cached is not None:
            return cached
        try:
            size = self.doc.get_page_size(index)
            result = (float(size[0]), float(size[1]))
        except Exception:
            result = (595.0, 842.0)
        self._size_cache[index] = result
        return result

    def _textpage(self, index: int):
        index = max(0, min(self.page_count - 1, int(index)))
        page = self.doc.get_page(index)
        return page, page.get_textpage()

    def chapters(self) -> list[Chapter]:
        chapters: list[Chapter] = []
        try:
            bookmarks = list(self.doc.get_toc())
        except Exception:
            bookmarks = []
        for bookmark in bookmarks:
            try:
                title = clean_text(bookmark.get_title(), 300)
            except Exception:
                continue
            if not title:
                continue
            try:
                page = int(bookmark.get_dest().get_index())
            except Exception:
                page = 0
            level = max(1, min(int(getattr(bookmark, "level", 0)) + 1, 4))
            chapters.append(Chapter(title, max(0, page), level, ""))
        if not chapters:
            chapters.append(Chapter("Страница 1", 0, 1, ""))
        return chapters

    def page_text(self, index: int) -> str:
        index = max(0, min(self.page_count - 1, int(index)))
        if index in self._text_cache:
            return self._text_cache[index]
        page = textpage = None
        try:
            page, textpage = self._textpage(index)
            text = textpage.get_text_range()
        except Exception:
            text = ""
        finally:
            for item in (textpage, page):
                if item is not None:
                    try:
                        item.close()
                    except Exception:
                        pass
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00ad", "").replace("\xa0", " ")
        self._text_cache[index] = text
        return text

    def words(self, index: int) -> list[tuple[float, float, float, float, str, int, int, int]]:
        """Слова в координатах PDF-точки: (x0, y0, x1, y1, text, block, line, word).

        PDFium отдаёт координаты с началом в левом нижнем углу; читалка
        работает с экранными координатами, поэтому Y переворачивается.
        """
        index = max(0, min(self.page_count - 1, int(index)))
        cached = self._words_cache.get(index)
        if cached is not None:
            return cached
        page = textpage = None
        words: list[tuple[float, float, float, float, str, int, int, int]] = []
        try:
            page, textpage = self._textpage(index)
            count = int(textpage.count_chars())
            text = textpage.get_text_range()
            height = self.page_size(index)[1]
            line = 0
            last_top: float | None = None
            in_word = False
            x0 = y0 = x1 = y1 = 0.0
            buffer: list[str] = []
            word_index = 0
            for char_index in range(min(count, len(text))):
                char = text[char_index]
                if char in "\r\n":
                    char = " "
                try:
                    box = textpage.get_charbox(char_index)
                except Exception:
                    box = None
                if box is None:
                    continue
                left, bottom, right, top = (float(v) for v in box)
                if not char.isspace():
                    if last_top is None or abs(top - last_top) > 2.0:
                        line += 1
                        last_top = top
                        word_index = 0
                    if not in_word:
                        in_word = True
                        word_index += 1
                        x0, y0, x1, y1 = left, height - top, right, height - bottom
                        buffer = []
                    else:
                        x0 = min(x0, left)
                        y0 = min(y0, height - top)
                        x1 = max(x1, right)
                        y1 = max(y1, height - bottom)
                    buffer.append(char)
                elif in_word:
                    value = "".join(buffer).replace("\u00ad", "").strip()
                    if value:
                        words.append((x0, y0, x1, y1, value, 0, line, word_index))
                    in_word = False
                    buffer = []
            if in_word:
                value = "".join(buffer).replace("\u00ad", "").strip()
                if value:
                    words.append((x0, y0, x1, y1, value, 0, line, word_index))
        except Exception:
            words = []
        finally:
            for item in (textpage, page):
                if item is not None:
                    try:
                        item.close()
                    except Exception:
                        pass
        words.sort(key=lambda word: (word[6], word[7]))
        self._words_cache[index] = words
        return words

    def render(self, index: int, zoom: float = 1.5) -> Image.Image:
        index = max(0, min(self.page_count - 1, int(index)))
        key = (index, max(1, int(zoom * 100)))
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached
        page = self.doc.get_page(index)
        try:
            image = page.render(scale=max(0.1, float(zoom))).to_pil()
        finally:
            try:
                page.close()
            except Exception:
                pass
        if len(self._image_cache) > 12:
            self._image_cache.pop(next(iter(self._image_cache)))
        self._image_cache[key] = image
        return image

    def search(self, query: str, limit: int = 80) -> list[tuple[int, str]]:
        query = (query or "").strip()
        if len(query) < 2:
            return []
        needle = query.lower()
        results: list[tuple[int, str]] = []
        for index in range(self.page_count):
            text = self.page_text(index)
            low = text.lower()
            start = low.find(needle)
            if start < 0:
                continue
            fragment = " ".join(text[max(0, start - 60) : start + len(query) + 90].split())
            results.append((index, fragment))
            if len(results) >= limit:
                break
        return results


def load_document(path: Path) -> Document:
    book = PdfBook(path)
    try:
        meta = parse_meta(path)
        doc = Document(
            title=meta["title"],
            author=meta["author"],
            format="pdf",
            path=path,
            chapters=book.chapters(),
            description=meta["description"],
            year=meta["year"],
            page_count=book.page_count,
            pdf_path=path,
        )
        return doc
    finally:
        book.close()
