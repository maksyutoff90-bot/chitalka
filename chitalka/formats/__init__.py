"""Определение формата и единая точка входа для метаданных и текста."""

from __future__ import annotations

import zipfile
from pathlib import Path

from .model import Document, clean_text

NATIVE = {"fb2", "epub", "pdf", "txt"}
SUPPORTED = NATIVE

FORMAT_TITLES = {
    "fb2": "FB2",
    "epub": "EPUB",
    "pdf": "PDF",
    "txt": "TXT",
}

EXTENSIONS = {
    ".fb2": "fb2",
    ".epub": "epub",
    ".pdf": "pdf",
    ".txt": "txt",
    ".text": "txt",
}


class UnsupportedFormat(Exception):
    pass


class BookError(Exception):
    pass


def detect_format(path: str | Path) -> str:
    path = Path(path)
    name = path.name.lower()
    if name.endswith(".fb2.zip"):
        return "fb2"
    suffix = path.suffix.lower()
    if suffix in EXTENSIONS:
        return EXTENSIONS[suffix]
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                if any(n.lower().endswith(".fb2") for n in archive.namelist()):
                    return "fb2"
        except (OSError, zipfile.BadZipFile):
            return ""
    return ""


def is_supported(path: str | Path) -> bool:
    return detect_format(path) in SUPPORTED


def format_title(fmt: str) -> str:
    return FORMAT_TITLES.get(fmt, (fmt or "").upper())


def _fallback_meta(path: Path, fmt: str, error: str = "") -> dict:
    stem = clean_text(path.stem)
    title = stem
    author = ""
    for dash in (" - ", " – ", " — "):
        if dash in stem:
            left, right = stem.split(dash, 1)
            if 2 < len(left) < 70 and len(right) > 2:
                author, title = clean_text(left), clean_text(right)
                break
    stat = path.stat()
    return {
        "path": str(path),
        "format": fmt,
        "title": title or path.name,
        "author": author,
        "series": "",
        "genre": "",
        "year": "",
        "language": "",
        "description": "",
        "cover": "",
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "error": error,
    }


def parse_meta(path: str | Path) -> dict:
    path = Path(path)
    fmt = detect_format(path)
    if fmt not in SUPPORTED:
        raise UnsupportedFormat(fmt or path.suffix)
    try:
        if fmt == "fb2":
            from .fb2 import parse_meta as parser
        elif fmt == "epub":
            from .epub import parse_meta as parser
        elif fmt == "pdf":
            from .pdf import parse_meta as parser
        else:
            from .txt import parse_meta as parser
        meta = parser(path)
        meta["format"] = fmt
        return meta
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Не удалось прочитать %s: %s", path, exc)
        return _fallback_meta(path, fmt, str(exc))


def load_document(path: str | Path) -> Document:
    path = Path(path)
    fmt = detect_format(path)
    if fmt not in SUPPORTED:
        raise UnsupportedFormat(
            f"Формат «{path.suffix.lstrip('.').upper()}» пока не поддерживается. "
            "Откройте файл во внешней программе."
        )
    try:
        if fmt == "fb2":
            from .fb2 import load_document as loader
        elif fmt == "epub":
            from .epub import load_document as loader
        elif fmt == "pdf":
            from .pdf import load_document as loader
        else:
            from .txt import load_document as loader
        document = loader(path)
        if not document.title:
            document.title = path.stem
        return document
    except UnsupportedFormat:
        raise
    except Exception as exc:
        raise BookError(f"Не удалось открыть книгу: {exc}") from exc
