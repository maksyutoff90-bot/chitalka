"""SQLite-библиотека: книги, прогресс, закладки, поиск."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    format          TEXT NOT NULL,
    title           TEXT NOT NULL,
    author          TEXT NOT NULL DEFAULT '',
    series          TEXT NOT NULL DEFAULT '',
    genre           TEXT NOT NULL DEFAULT '',
    year            TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    cover           TEXT NOT NULL DEFAULT '',
    size            INTEGER NOT NULL DEFAULT 0,
    mtime           REAL NOT NULL DEFAULT 0,
    added_at        TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'new',
    favorite        INTEGER NOT NULL DEFAULT 0,
    rating          INTEGER NOT NULL DEFAULT 0,
    progress        REAL NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL DEFAULT 0,
    position_offset INTEGER NOT NULL DEFAULT 0,
    chapter         TEXT NOT NULL DEFAULT '',
    last_read_at    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_books_author ON books(author COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_books_recent ON books(last_read_at DESC);
CREATE TABLE IF NOT EXISTS bookmarks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    offset      INTEGER NOT NULL DEFAULT 0,
    chapter     TEXT NOT NULL DEFAULT '',
    page        INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_book ON bookmarks(book_id);
CREATE TABLE IF NOT EXISTS annotations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id      INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    color        TEXT NOT NULL DEFAULT 'yellow',
    start_block  INTEGER NOT NULL DEFAULT 0,
    start_offset INTEGER NOT NULL DEFAULT 0,
    end_block    INTEGER NOT NULL DEFAULT 0,
    end_offset   INTEGER NOT NULL DEFAULT 0,
    quote        TEXT NOT NULL DEFAULT '',
    comment      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_annotations_book ON annotations(book_id);
CREATE TABLE IF NOT EXISTS folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    added_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reading_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT NOT NULL DEFAULT '',
    ended_at    TEXT NOT NULL DEFAULT '',
    seconds     INTEGER NOT NULL DEFAULT 0,
    pages       INTEGER NOT NULL DEFAULT 0,
    date        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON reading_sessions(date);
CREATE INDEX IF NOT EXISTS idx_sessions_book ON reading_sessions(book_id);
CREATE TABLE IF NOT EXISTS catalogs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    added_at    TEXT NOT NULL DEFAULT ''
);
"""

BOOK_FIELDS = (
    "path", "format", "title", "author", "series", "genre", "year", "language",
    "description", "cover", "size", "mtime",
)

SORTS = {
    "recent": "COALESCE(NULLIF(last_read_at,''), added_at) DESC, title COLLATE NOCASE",
    "added": "added_at DESC, title COLLATE NOCASE",
    "title": "title COLLATE NOCASE ASC",
    "author": "author COLLATE NOCASE ASC, title COLLATE NOCASE",
    "year": "year DESC, title COLLATE NOCASE",
    "progress": "progress DESC, title COLLATE NOCASE",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LibraryDB:
    """Потокобезопасная обёртка: отдельное соединение на поток."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = str(path)
        self._local = threading.local()
        self._lock = threading.RLock()
        self.init()

    # ------------------------------------------------------------- соединение
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def init(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.commit()
                conn.close()
            finally:
                self._local.conn = None

    # ----------------------------------------------------------------- книги
    def upsert(self, meta: dict[str, Any]) -> tuple[int, bool]:
        """Добавляет книгу или обновляет метаданные, сохраняя прогресс.

        Возвращает (id, is_new).
        """
        path = str(meta["path"])
        row = self.conn.execute("SELECT id FROM books WHERE path=?", (path,)).fetchone()
        now = _now()
        values = {
            "path": path,
            "format": meta.get("format", ""),
            "title": meta.get("title") or Path(path).stem,
            "author": meta.get("author", ""),
            "series": meta.get("series", ""),
            "genre": meta.get("genre", ""),
            "year": str(meta.get("year", "") or ""),
            "language": meta.get("language", ""),
            "description": meta.get("description", ""),
            "cover": str(meta.get("cover", "") or ""),
            "size": int(meta.get("size", 0) or 0),
            "mtime": float(meta.get("mtime", 0) or 0),
        }
        if row:
            assignments = ", ".join(f"{key}=?" for key in values if key != "path")
            params = [values[key] for key in values if key != "path"]
            params.append(now)
            params.append(row["id"])
            self.conn.execute(
                f"UPDATE books SET {assignments}, updated_at=? WHERE id=?", params
            )
            self.conn.commit()
            return int(row["id"]), False

        columns = list(values) + ["added_at", "updated_at"]
        params = list(values.values()) + [now, now]
        placeholders = ", ".join("?" for _ in columns)
        cur = self.conn.execute(
            f"INSERT INTO books ({', '.join(columns)}) VALUES ({placeholders})", params
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def get(self, book_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()

    def by_path(self, path: str | Path) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM books WHERE path=?", (str(path),)
        ).fetchone()

    def paths(self) -> dict[str, tuple[int, float]]:
        rows = self.conn.execute("SELECT id, path, mtime FROM books").fetchall()
        return {r["path"]: (int(r["id"]), float(r["mtime"])) for r in rows}

    def search(
        self,
        query: str = "",
        *,
        fmt: str = "all",
        status: str = "all",
        favorite: bool = False,
        sort: str = "recent",
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        where: list[str] = []
        params: list[Any] = []
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            where.append(
                "(title LIKE ? COLLATE NOCASE OR author LIKE ? COLLATE NOCASE "
                "OR series LIKE ? COLLATE NOCASE OR genre LIKE ? COLLATE NOCASE)"
            )
            params.extend([like, like, like, like])
        if fmt and fmt != "all":
            where.append("format=?")
            params.append(fmt.lower())
        if status == "favorite":
            where.append("favorite=1")
        elif status == "reading":
            where.append("status='reading'")
        elif status == "done":
            where.append("status='done'")
        elif status == "new":
            where.append("status='new'")
        if favorite:
            where.append("favorite=1")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = SORTS.get(sort, SORTS["recent"])
        sql = f"SELECT * FROM books{clause} ORDER BY {order} LIMIT ?"
        params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def counts(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(favorite=1) AS favorite, "
            "SUM(status='reading') AS reading, "
            "SUM(status='done') AS done, "
            "COUNT(DISTINCT CASE WHEN author<>'' THEN author END) AS authors "
            "FROM books"
        ).fetchone()
        formats = {
            r["format"]: int(r["n"])
            for r in self.conn.execute(
                "SELECT format, COUNT(*) AS n FROM books GROUP BY format"
            )
        }
        return {
            "total": int(row["total"] or 0),
            "favorite": int(row["favorite"] or 0),
            "reading": int(row["reading"] or 0),
            "done": int(row["done"] or 0),
            "authors": int(row["authors"] or 0),
            "formats": formats,  # type: ignore[dict-item]
        }

    def update_progress(
        self,
        book_id: int,
        progress: float,
        position: int,
        offset: int = 0,
        chapter: str = "",
    ) -> None:
        progress = max(0.0, min(100.0, float(progress)))
        now = _now()
        with self._lock:
            if progress >= 99.0:
                status_sql = ", status='done'"
            elif progress > 0.5:
                status_sql = ", status=CASE WHEN status='done' THEN status ELSE 'reading' END"
            else:
                status_sql = ""
            self.conn.execute(
                "UPDATE books SET progress=?, position=?, position_offset=?, "
                f"chapter=?, last_read_at=?{status_sql} WHERE id=?",
                (progress, int(position), int(offset), chapter, now, int(book_id)),
            )
            self.conn.commit()

    def set_status(self, book_id: int, status: str) -> None:
        progress_sql = ""
        params: list[Any] = [status]
        if status == "done":
            progress_sql = ", progress=100"
        elif status == "new":
            progress_sql = ", progress=0, position=0, position_offset=0"
        self.conn.execute(
            f"UPDATE books SET status=?{progress_sql} WHERE id=?", params + [int(book_id)]
        )
        self.conn.commit()

    def set_favorite(self, book_id: int, value: bool) -> None:
        self.conn.execute(
            "UPDATE books SET favorite=? WHERE id=?", (1 if value else 0, int(book_id))
        )
        self.conn.commit()

    def toggle_favorite(self, book_id: int) -> bool:
        row = self.get(book_id)
        value = not bool(row["favorite"]) if row else True
        self.set_favorite(book_id, value)
        return value

    def set_rating(self, book_id: int, rating: int) -> None:
        self.conn.execute(
            "UPDATE books SET rating=? WHERE id=?", (max(0, min(5, rating)), int(book_id))
        )
        self.conn.commit()

    def remove(self, book_id: int) -> None:
        self.conn.execute("DELETE FROM books WHERE id=?", (int(book_id),))
        self.conn.commit()

    def remove_missing(self) -> int:
        rows = self.conn.execute("SELECT id, path FROM books").fetchall()
        gone = [int(r["id"]) for r in rows if not Path(r["path"]).exists()]
        if gone:
            self.conn.executemany(
                "DELETE FROM books WHERE id=?", [(book_id,) for book_id in gone]
            )
            self.conn.commit()
        return len(gone)

    def all_books(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM books").fetchall()

    # -------------------------------------------------------------- закладки
    def bookmarks(self, book_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM bookmarks WHERE book_id=? ORDER BY position, offset",
            (int(book_id),),
        ).fetchall()

    def add_bookmark(
        self,
        book_id: int,
        position: int,
        offset: int,
        chapter: str,
        page: int,
        note: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO bookmarks (book_id, position, offset, chapter, page, note, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (int(book_id), int(position), int(offset), chapter, int(page), note, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_bookmark(self, bookmark_id: int) -> None:
        self.conn.execute("DELETE FROM bookmarks WHERE id=?", (int(bookmark_id),))
        self.conn.commit()

    def update_bookmark_note(self, bookmark_id: int, note: str) -> None:
        self.conn.execute(
            "UPDATE bookmarks SET note=? WHERE id=?", (note, int(bookmark_id))
        )
        self.conn.commit()

    # ------------------------------------------------------------- заметки
    def annotations(self, book_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM annotations WHERE book_id=? "
            "ORDER BY start_block, start_offset, created_at",
            (int(book_id),),
        ).fetchall()

    def add_annotation(self, book_id: int, color: str, start_block: int,
                       start_offset: int, end_block: int, end_offset: int,
                       quote: str, comment: str = "") -> int:
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO annotations (book_id, color, start_block, start_offset, "
            "end_block, end_offset, quote, comment, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                int(book_id), color, int(start_block), int(start_offset),
                int(end_block), int(end_offset), quote[:4000], comment[:8000],
                now, now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_annotation(self, annotation_id: int, color: str, comment: str) -> None:
        self.conn.execute(
            "UPDATE annotations SET color=?, comment=?, updated_at=? WHERE id=?",
            (color, comment[:8000], _now(), int(annotation_id)),
        )
        self.conn.commit()

    def delete_annotation(self, annotation_id: int) -> None:
        self.conn.execute("DELETE FROM annotations WHERE id=?", (int(annotation_id),))
        self.conn.commit()

    # -------------------------------------------------------------- статистика
    def begin_session(self, book_id: int, started_at: str | None = None) -> int:
        now = datetime.now()
        started = started_at or now.isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO reading_sessions (book_id, started_at, ended_at, seconds, pages, date) "
            "VALUES (?,?,?,0,0,?)",
            (int(book_id), started, "", now.date().isoformat()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_session(self, session_id: int, seconds: int, pages: int,
                       ended_at: str | None = None) -> None:
        self.conn.execute(
            "UPDATE reading_sessions SET seconds=?, pages=?, ended_at=? WHERE id=?",
            (max(0, int(seconds)), max(0, int(pages)),
             ended_at or datetime.now().isoformat(timespec="seconds"), int(session_id)),
        )
        self.conn.commit()

    def stats_overview(self, goal_minutes: int = 600) -> dict:
        today = date.today()
        today_s = today.isoformat()
        week_start = (today - timedelta(days=6)).isoformat()
        month_prefix = today.strftime("%Y-%m")
        month_start = today.replace(day=1).isoformat()
        thirty_start = (today - timedelta(days=29)).isoformat()

        def totals(where: str = "", params: tuple = ()) -> tuple[int, int]:
            sql = ("SELECT COALESCE(SUM(seconds),0), COALESCE(SUM(pages),0) "
                   "FROM reading_sessions" + (" WHERE " + where if where else ""))
            row = self.conn.execute(sql, params).fetchone()
            return int(row[0] or 0), int(row[1] or 0)

        today_sec, today_pages = totals("date=?", (today_s,))
        week_sec, week_pages = totals("date>=?", (week_start,))
        month_sec, month_pages = totals("date LIKE ?", (month_prefix + "%",))
        total_sec, total_pages = totals()

        rows = self.conn.execute(
            "SELECT DISTINCT date FROM reading_sessions WHERE seconds > 0 ORDER BY date DESC"
        ).fetchall()
        days = [str(row["date"]) for row in rows if row["date"]]
        streak = 0
        if days:
            anchor = today
            if days[0] != today_s:
                anchor = today - timedelta(days=1)
                if days[0] != anchor.isoformat():
                    anchor = None
            if anchor is not None:
                available = set(days)
                cursor = anchor
                while cursor.isoformat() in available:
                    streak += 1
                    cursor -= timedelta(days=1)

        daily_rows = self.conn.execute(
            "SELECT date, SUM(seconds) AS sec, SUM(pages) AS pages "
            "FROM reading_sessions WHERE date>=? GROUP BY date",
            (thirty_start,),
        ).fetchall()
        by_date = {str(row["date"]): (int(row["sec"] or 0), int(row["pages"] or 0))
                   for row in daily_rows}
        daily = []
        for offset in range(29, -1, -1):
            day = today - timedelta(days=offset)
            sec, pages = by_date.get(day.isoformat(), (0, 0))
            daily.append({"date": day.isoformat(), "seconds": sec, "pages": pages})

        top_rows = self.conn.execute(
            "SELECT book_id, SUM(seconds) AS sec, SUM(pages) AS pages "
            "FROM reading_sessions WHERE seconds>0 AND book_id>0 "
            "GROUP BY book_id ORDER BY sec DESC LIMIT 5"
        ).fetchall()
        top = []
        for row in top_rows:
            book = self.get(int(row["book_id"]))
            if book is None:
                continue
            top.append({
                "book_id": int(row["book_id"]),
                "title": book["title"],
                "author": book["author"],
                "cover": book["cover"],
                "seconds": int(row["sec"] or 0),
                "pages": int(row["pages"] or 0),
            })

        month_goal_seconds = max(1, int(goal_minutes)) * 60
        return {
            "today_seconds": today_sec,
            "today_pages": today_pages,
            "week_seconds": week_sec,
            "week_pages": week_pages,
            "month_seconds": month_sec,
            "month_pages": month_pages,
            "total_seconds": total_sec,
            "total_pages": total_pages,
            "streak": streak,
            "daily": daily,
            "top": top,
            "goal_minutes": int(goal_minutes),
            "goal_seconds": month_goal_seconds,
            "goal_percent": min(100.0, month_sec / month_goal_seconds * 100),
            "month_label": today.strftime("%Y-%m"),
            "month_start": month_start,
            "reading_days": len(days),
        }

    # -------------------------------------------------------------- каталоги
    def catalogs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM catalogs ORDER BY name COLLATE NOCASE"
        ).fetchall()

    def add_catalog(self, name: str, url: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO catalogs (name, url, added_at) VALUES (?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET name=excluded.name",
            (name.strip() or url.strip(), url.strip(), _now()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM catalogs WHERE url=?", (url.strip(),)).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)

    def remove_catalog(self, catalog_id: int) -> None:
        self.conn.execute("DELETE FROM catalogs WHERE id=?", (int(catalog_id),))
        self.conn.commit()

    # -------------------------------------------------------------- папки
    def folders(self) -> list[str]:
        return [r["path"] for r in self.conn.execute("SELECT path FROM folders ORDER BY id")]

    def add_folder(self, path: str | Path) -> None:
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO folders (path, added_at) VALUES (?,?)",
                (str(path), _now()),
            )
            self.conn.commit()
        except sqlite3.Error:
            pass

    def remove_folder(self, path: str | Path) -> None:
        self.conn.execute("DELETE FROM folders WHERE path=?", (str(path),))
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        return self.counts()

    def check_writable(self) -> str:
        try:
            self.conn.execute(
                "INSERT INTO folders (path, added_at) VALUES (?,?) "
                "ON CONFLICT(path) DO UPDATE SET added_at=added_at",
                (f"__probe__{id(self)}", _now()),
            )
            self.conn.execute("DELETE FROM folders WHERE path LIKE '__probe__%'")
            self.conn.commit()
            return ""
        except sqlite3.Error as exc:
            return str(exc)


def rows_to_text(rows: Iterable[sqlite3.Row], key: str = "title") -> list[str]:
    return [str(r[key]) for r in rows]
