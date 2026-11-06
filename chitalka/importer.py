"""Фоновое сканирование папок и импорт книг в библиотеку."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .covers import ensure_cover
from .db import LibraryDB
from .formats import detect_format, is_supported, parse_meta

log = logging.getLogger(__name__)

SKIP_DIRS = {".git", "__pycache__", "node_modules", "$recycle.bin", "system volume information"}


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    total: int = 0
    seconds: float = 0.0


def iter_books(paths: Iterable[str | Path], excluded: Iterable[Path] = ()) -> list[Path]:
    """Рекурсивно собирает поддерживаемые файлы, без дублей."""
    excluded_resolved = []
    for folder in excluded:
        try:
            excluded_resolved.append(Path(folder).resolve())
        except OSError:
            pass
    found: dict[str, Path] = {}
    for raw in paths:
        try:
            path = Path(raw).expanduser()
        except (OSError, ValueError):
            continue
        if path.is_file():
            if is_supported(path):
                found[str(path.resolve()).lower()] = path
            continue
        if not path.is_dir():
            continue
        for root, dirs, files in os.walk(path):
            root_path = Path(root)
            dirs[:] = [
                d for d in dirs
                if d.lower() not in SKIP_DIRS and not d.startswith(".")
            ]
            try:
                resolved = root_path.resolve()
            except OSError:
                continue
            if any(resolved == ex or ex in resolved.parents for ex in excluded_resolved):
                dirs[:] = []
                continue
            for name in files:
                if name.startswith(".") or name.startswith("~$"):
                    continue
                file = root_path / name
                if is_supported(file):
                    try:
                        key = str(file.resolve()).lower()
                    except OSError:
                        key = str(file).lower()
                    found.setdefault(key, file)
    return sorted(found.values(), key=lambda p: (p.name.lower(), str(p).lower()))


class Importer(threading.Thread):
    """Поток импорта. Общается с интерфейсом через queue."""

    def __init__(
        self,
        db: LibraryDB,
        paths: Iterable[str | Path],
        events: "queue.Queue[tuple]",
        *,
        force: bool = False,
    ) -> None:
        super().__init__(daemon=True, name="chitalka-importer")
        self.db = db
        self.paths = [str(p) for p in paths]
        self.events = events
        self.force = force
        self.stop_event = threading.Event()
        self.result = ImportResult()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        started = time.time()
        self.events.put(("scan", "Поиск книг…"))
        files = iter_books(self.paths, excluded=())
        self.result.total = len(files)
        self.events.put(("total", len(files)))
        known = self.db.paths()

        for index, file in enumerate(files, 1):
            if self.stop_event.is_set():
                break
            try:
                stat = file.stat()
            except OSError:
                continue
            previous = known.get(str(file))
            if (
                previous
                and not self.force
                and abs(previous[1] - stat.st_mtime) < 1.0
                and self._has_cover(previous[0])
            ):
                self.result.skipped += 1
                self.events.put(("tick", index, len(files), file.name, "skip"))
                continue

            try:
                meta = parse_meta(file)
                meta["cover"] = ensure_cover(
                    file,
                    title=meta.get("title") or file.stem,
                    author=meta.get("author", ""),
                    genre=meta.get("genre", ""),
                    stored=meta.get("cover", ""),
                )
                book_id, is_new = self.db.upsert(meta)
                if is_new:
                    self.result.added += 1
                else:
                    self.result.updated += 1
                self.events.put(("tick", index, len(files), meta.get("title") or file.name, "new" if is_new else "update"))
            except Exception as exc:  # noqa: BLE001 - одна книга не должна ронять импорт
                log.warning("Ошибка импорта %s: %s", file, exc)
                self.result.errors.append((str(file), str(exc)))
                self.events.put(("tick", index, len(files), file.name, "error"))

        self.result.seconds = time.time() - started
        self.events.put(("done", self.result))

    def _has_cover(self, book_id: int) -> bool:
        row = self.db.get(book_id)
        if not row:
            return False
        cover = Path(row["cover"]) if row["cover"] else None
        return bool(cover and cover.exists() and cover.stat().st_size > 0)
