from __future__ import annotations

from pathlib import Path

import pytest

from chitalka.formats import load_document, parse_meta
from chitalka.formats import UnsupportedFormat

BOOKS = Path(__file__).resolve().parents[1] / "data" / "books"


def test_fb2_structure():
    document = load_document(BOOKS / "Пиковая дама.fb2")
    assert "Пиковая дама" in document.title
    assert "Пушкин" in document.author
    assert document.format == "fb2"
    assert len(document.blocks) > 20
    assert document.chapters
    assert "Германн" in document.plain_text()


def test_epub_structure():
    document = load_document(BOOKS / "Дама с собачкой.epub")
    assert document.format == "epub"
    assert document.blocks
    assert "Чехов" in document.author


def test_txt_structure():
    document = load_document(BOOKS / "Лев Толстой - После бала.txt")
    assert document.format == "txt"
    assert document.blocks
    assert "Толстой" in document.author


def test_pdf_structure():
    document = load_document(BOOKS / "Ионыч.pdf")
    assert document.format == "pdf"
    assert document.page_count > 0
    assert document.pdf_path is not None


def test_parse_meta_and_detect():
    meta = parse_meta(BOOKS / "Пиковая дама.fb2")
    assert meta["format"] == "fb2"
    assert meta["title"]
    with pytest.raises(UnsupportedFormat):
        parse_meta(BOOKS / "нет-такого.xyz")
