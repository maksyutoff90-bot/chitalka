from __future__ import annotations

from pathlib import Path

from chitalka.formats.pdf import PdfBook

BOOKS = Path(__file__).resolve().parents[1] / "data" / "books"


def test_pdf_words_and_size():
    book = PdfBook(BOOKS / "Ионыч.pdf")
    try:
        width, height = book.page_size(0)
        assert width > 0 and height > 0
        assert book.page_count > 1
        words = book.words(0)
        assert words
        for x0, y0, x1, y1, text, _block, _line, _word in words:
            assert x1 >= x0
            assert y1 >= y0
            assert text
        assert any("Ионыч" in word[4] for word in words)
    finally:
        book.close()
