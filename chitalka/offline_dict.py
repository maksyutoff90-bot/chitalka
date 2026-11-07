"""Офлайн-словарь FreeDict/WikDict (SQLite) с ленивой распаковкой."""

from __future__ import annotations

import lzma
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

from .config import BUNDLED_DICT_ARCHIVE, OFFLINE_DICT_ARCHIVE, OFFLINE_DICT_PATH

_LOCK = threading.Lock()


class OfflineDictionary:
    def __init__(self, path: Path = OFFLINE_DICT_PATH,
                 archive: Path = OFFLINE_DICT_ARCHIVE,
                 fallback_archive: Path = BUNDLED_DICT_ARCHIVE) -> None:
        self.path = Path(path)
        self.archive = Path(archive)
        self.fallback_archive = Path(fallback_archive)
        self._checked = False
        self.last_error = ""

    def _archive_path(self) -> Path | None:
        if self.archive.exists():
            return self.archive
        if self.fallback_archive.exists() and self.fallback_archive != self.archive:
            return self.fallback_archive
        return None

    def _prepare(self) -> bool:
        archive = self._archive_path()
        if self.path.exists():
            if archive is None or self.path.stat().st_mtime >= archive.stat().st_mtime:
                return True
        if archive is None:
            self.last_error = (
                f"no archive: path={self.path} exists={self.path.exists()} "
                f"archive={self.archive} fallback={self.fallback_archive}"
            )
            return False
        with _LOCK:
            if self.path.exists() and self.path.stat().st_mtime >= archive.stat().st_mtime:
                return True
            try:
                data = lzma.decompress(archive.read_bytes())
                temp = self.path.with_suffix(".sqlite.tmp")
                temp.write_bytes(data)
                temp.replace(self.path)
                return True
            except Exception as exc:
                self.last_error = f"extract: {exc}"
                return False

    def available(self) -> bool:
        return self._prepare()

    def _connect(self) -> sqlite3.Connection | None:
        if not self._prepare():
            return None
        last_exc = None
        for attempt in range(3):
            try:
                conn = sqlite3.connect(str(self.path.resolve()), timeout=5)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                conn.execute("PRAGMA temp_store=MEMORY")
                return conn
            except Exception as exc:
                last_exc = exc
                time.sleep(0.15)
        self.last_error = (
            f"connect: {last_exc}; path={self.path}; resolved={self.path.resolve()} "
            f"exists={self.path.exists()} "
            f"size={self.path.stat().st_size if self.path.exists() else 0}"
        )
        return None

    def lookup(self, word: str, language: str, limit: int = 8) -> dict | None:
        word = (word or "").strip()
        if not word:
            return None
        conn = self._connect()
        if conn is None:
            return None
        try:
            rows = conn.execute(
                "SELECT word, definition FROM entries "
                "WHERE word_lower=? AND lang=? LIMIT ?",
                (word.lower(), language, int(limit)),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        if not rows:
            return None
        definitions: list[str] = []
        seen: set[str] = set()
        for row in rows:
            definition = str(row["definition"] or "").strip()
            if definition and definition not in seen:
                definitions.append(definition)
                seen.add(definition)
        if not definitions:
            return None
        host = "ru.wiktionary.org" if language == "ru" else "en.wiktionary.org"
        return {
            "word": str(rows[0]["word"] or word),
            "language": language,
            "phonetic": "",
            "definitions": definitions,
            "url": f"https://{host}/wiki/" + urllib.parse.quote(word),
            "source": "FreeDict · офлайн",
            "offline": True,
        }

    def stats(self) -> dict:
        conn = self._connect()
        if conn is None:
            return {}
        try:
            rows = []
            for lang in ("ru", "en"):
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM entries WHERE lang=?", (lang,)
                ).fetchone()
                if count and int(count["count"]):
                    rows.append((lang, int(count["count"])))
            if not rows:
                self.last_error = (
                    f"empty: path={self.path} exists={self.path.exists()} "
                    f"size={self.path.stat().st_size if self.path.exists() else 0}"
                )
                return {}
            return {lang: count for lang, count in rows}
        except Exception as exc:
            self.last_error = (
                (self.last_error + " | " if self.last_error else "")
                + f"stats: {exc}; path={self.path}; exists={self.path.exists()}"
            )
            return {}
        finally:
            conn.close()


_OFFLINE = OfflineDictionary()


def offline_lookup(word: str, language: str) -> dict | None:
    return _OFFLINE.lookup(word, language)


def offline_stats() -> dict:
    return _OFFLINE.stats()


def offline_last_error() -> str:
    return _OFFLINE.last_error
