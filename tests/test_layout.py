from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chitalka.formats import load_document


def _layout():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tk недоступен в этой среде")
    from chitalka.layout import LayoutStyle, layout_document

    return root, layout_document, LayoutStyle


def test_fb2_layout_has_pages_and_text():
    root, layout_document, LayoutStyle = _layout()
    try:
        document = load_document(
            Path(__file__).resolve().parents[1] / "data" / "books" / "Пиковая дама.fb2"
        )
        result = layout_document(document, LayoutStyle(), root)
        assert result.pages
        assert any(line.text.strip() for page in result.pages for line in page.lines)
        assert sum(len(page.lines) for page in result.pages) > 0
        assert all(line.height > 0 for page in result.pages for line in page.lines)
    finally:
        root.destroy()
