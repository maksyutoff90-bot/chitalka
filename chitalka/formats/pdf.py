"""PDF: метаданные, обложка, постраничный рендер и поиск (PyMuPDF)."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from ..covers import save_cover_bytes
from .model import Chapter, Document, clean_text

try:  # PyMuPDF 1.24+ умеет и `fitz`, и `pymupdf`
    import pymupdf as fitz  # type: ignore
except Exception:  # pragma: no cover
    import fitz  # type: ignore


def _year(value: str) -> str:
    match = re.search(r"(19|20)\d{2}", value or "")
    return match.group(0) if match else ""


def open_pdf(path: Path):
    doc = fitz.open(str(path))
    if doc.needs_pass:
        raise ValueError("PDF защищён паролем")
    return doc


def render_cover(path: Path) -> str:
    doc = open_pdf(path)
    try:
        if doc.page_count == 0:
            return ""
        page = doc[0]
        height = max(1.0, page.rect.height)
        zoom = min(3.0, 1000.0 / height)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return save_cover_bytes(path, pix.tobytes("png"))
    finally:
        doc.close()


def parse_meta(path: Path) -> dict:
    doc = open_pdf(path)
    try:
        meta = doc.metadata or {}
        title = clean_text(meta.get("title", "")) or path.stem
        author = clean_text(meta.get("author", ""))
        description = clean_text(meta.get("subject", ""), 1000)
        year = _year(meta.get("creationDate", ""))
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
    """Ленивая обёртка для чтения PDF."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.doc = open_pdf(path)
        self.page_count = int(self.doc.page_count)
        self._text_cache: dict[int, str] = {}
        self._image_cache: dict[tuple[int, int], Image.Image] = {}

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    def title(self) -> str:
        meta = self.doc.metadata or {}
        return clean_text(meta.get("title", "")) or self.path.stem

    def chapters(self) -> list[Chapter]:
        chapters: list[Chapter] = []
        try:
            toc = self.doc.get_toc(simple=True)
        except Exception:
            toc = []
        for level, title, page in toc:
            title = clean_text(title, 300)
            if not title:
                continue
            chapters.append(
                Chapter(title, max(1, int(page)) - 1, max(1, min(int(level), 4)), "")
            )
        if not chapters:
            chapters.append(Chapter("Страница 1", 0, 1, ""))
        return chapters

    def page_text(self, index: int) -> str:
        if index in self._text_cache:
            return self._text_cache[index]
        try:
            text = self.doc[index].get_text("text")
        except Exception:
            text = ""
        text = text.replace("\u00ad", "")
        self._text_cache[index] = text
        return text

    def render(self, index: int, zoom: float = 1.5) -> Image.Image:
        index = max(0, min(self.page_count - 1, int(index)))
        key = (index, max(1, int(zoom * 100)))
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached
        page = self.doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
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
