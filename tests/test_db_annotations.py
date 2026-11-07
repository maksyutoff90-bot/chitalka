from __future__ import annotations

from pathlib import Path

from chitalka.db import LibraryDB


def _book(db: LibraryDB, path: Path) -> int:
    book_id, _ = db.upsert({
        "path": str(path),
        "format": "fb2",
        "title": "Тестовая книга",
        "author": "Автор",
        "size": 10,
        "mtime": 1.0,
    })
    return book_id


def test_text_annotation_crud(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    book_id = _book(db, tmp_path / "book.fb2")
    annotation_id = db.add_annotation(
        book_id, "#ffd166", 1, 4, 1, 12, "выделенный текст", "комментарий",
    )
    rows = db.annotations(book_id)
    assert len(rows) == 1
    assert rows[0]["quote"] == "выделенный текст"
    assert rows[0]["comment"] == "комментарий"
    assert rows[0]["kind"] == "text"

    db.update_annotation(annotation_id, "#8ecae6", "новый комментарий")
    row = db.annotations(book_id)[0]
    assert row["color"] == "#8ecae6"
    assert row["comment"] == "новый комментарий"

    db.delete_annotation(annotation_id)
    assert db.annotations(book_id) == []
    db.close()


def test_pdf_annotation_geometry(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    book_id = _book(db, tmp_path / "book.pdf")
    annotation_id = db.add_annotation(
        book_id, "#ffd166", -1, 0, -1, 0, "PDF цитата", "",
        page=2, rects="10,20,30,40;50,60,70,80", kind="pdf",
    )
    row = db.annotations(book_id)[0]
    assert row["page"] == 2
    assert row["kind"] == "pdf"
    assert row["rects"].count(";") == 1
    assert row["id"] == annotation_id
    db.close()


def test_lookup_cache_lifecycle(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    assert db.cache_get("missing") is None
    db.cache_set("word:ru:en", "lady")
    assert db.cache_get("word:ru:en") == "lady"
    assert db.cache_count() == 1
    db.cache_delete("word:ru:en")
    assert db.cache_get("word:ru:en") is None
    db.cache_set("a", "1")
    db.cache_set("b", "2")
    assert db.cache_count() == 2
    db.cache_clear()
    assert db.cache_count() == 0
    db.close()
