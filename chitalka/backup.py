"""Резервная копия библиотеки, настроек и обложек."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .config import APP_VERSION, COVERS_DIR, DB_PATH, SETTINGS_PATH


class BackupError(Exception):
    pass


def _snapshot_database(target: Path) -> None:
    """Копирует SQLite через backup API, не ломая WAL."""
    if not DB_PATH.exists():
        raise BackupError("База библиотеки ещё не создана")
    source = sqlite3.connect(str(DB_PATH))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def create_backup(target: Path | str) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    with tempfile.TemporaryDirectory(prefix="chitalka-backup-") as tmp:
        db_copy = Path(tmp) / "library.db"
        _snapshot_database(db_copy)
        manifest = {
            "application": "chitalka",
            "format": 1,
            "version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False,
                                                         indent=2))
            archive.write(db_copy, "library.db")
            if SETTINGS_PATH.exists():
                archive.write(SETTINGS_PATH, "settings.json")
            if COVERS_DIR.exists():
                for cover in COVERS_DIR.glob("*"):
                    if cover.is_file():
                        archive.write(cover, f"covers/{cover.name}")
    return target


def _safe_member(name: str) -> bool:
    return not (name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts)


def restore_backup(archive_path: Path | str) -> None:
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise BackupError("Файл резервной копии не найден")
    with tempfile.TemporaryDirectory(prefix="chitalka-restore-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(archive_path) as archive:
            if any(not _safe_member(name) for name in archive.namelist()):
                raise BackupError("В архиве есть недопустимые пути")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise BackupError("Это не резервная копия «Читалки»") from exc
            if manifest.get("application") != "chitalka":
                raise BackupError("Это не резервная копия «Читалки»")
            archive.extract("library.db", tmp_path)
            if "settings.json" in archive.namelist():
                archive.extract("settings.json", tmp_path)
            for name in archive.namelist():
                if name.startswith("covers/") and not name.endswith("/"):
                    archive.extract(name, tmp_path)

        restored_db = tmp_path / "library.db"
        if not restored_db.exists():
            raise BackupError("В архиве нет library.db")
        check = sqlite3.connect(str(restored_db))
        try:
            check.execute("SELECT COUNT(*) FROM books").fetchone()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"Повреждённая база в архиве: {exc}") from exc
        finally:
            check.close()

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if DB_PATH.exists():
            shutil.copy2(DB_PATH, DB_PATH.with_name(f"library.db.before-restore-{stamp}"))
        for suffix in ("-wal", "-shm"):
            Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
        shutil.copy2(restored_db, DB_PATH)
        if (tmp_path / "settings.json").exists():
            shutil.copy2(tmp_path / "settings.json", SETTINGS_PATH)
        covers = tmp_path / "covers"
        if covers.exists():
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            for cover in covers.glob("*"):
                if cover.is_file():
                    shutil.copy2(cover, COVERS_DIR / cover.name)
