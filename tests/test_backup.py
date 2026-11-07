from __future__ import annotations

import sqlite3

from chitalka import backup
from chitalka.db import LibraryDB


def test_backup_and_restore(tmp_path, monkeypatch):
    db_path = tmp_path / "library.db"
    settings_path = tmp_path / "settings.json"
    covers = tmp_path / "covers"
    covers.mkdir()
    settings_path.write_text('{"ui_theme": "dark"}', encoding="utf-8")
    (covers / "one.jpg").write_bytes(b"cover")

    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(backup, "COVERS_DIR", covers)

    db = LibraryDB(db_path)
    db.upsert({"path": str(tmp_path / "a.fb2"), "format": "fb2", "title": "Книга"})
    db.close()

    archive = backup.create_backup(tmp_path / "backup.zip")
    assert archive.exists()

    db = LibraryDB(db_path)
    db.upsert({"path": str(tmp_path / "b.fb2"), "format": "fb2", "title": "Другая"})
    db.close()

    backup.restore_backup(archive)
    check = sqlite3.connect(db_path)
    try:
        titles = {row[0] for row in check.execute("SELECT title FROM books")}
    finally:
        check.close()
    assert "Книга" in titles
    assert "Другая" not in titles
    assert settings_path.read_text(encoding="utf-8") == '{"ui_theme": "dark"}'
    assert (covers / "one.jpg").read_bytes() == b"cover"
