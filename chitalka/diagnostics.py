"""Самопроверка, снимки окон и обслуживание библиотеки."""

from __future__ import annotations

import queue
import sys
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from .config import BOOKS_DIR, DATA_DIR, DB_PATH, Settings, load_settings
from .db import LibraryDB
from .formats import load_document, parse_meta
from .importer import Importer
from .layout import LayoutStyle, layout_document
from . import opds
from . import dictionary


def _say(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


def _log(lines: list[str], name: str = "selftest.log") -> Path:
    path = DATA_DIR / name
    text = "\n".join(lines) + "\n"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}")
    except OSError:
        pass
    return path


def _pump(root, seconds: float = 0.5) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            root.update()
        except tk.TclError:
            return
        time.sleep(0.02)


def _import_samples(db: LibraryDB, timeout: float = 90.0) -> None:
    events: queue.Queue = queue.Queue()
    importer = Importer(db, [BOOKS_DIR], events, force=False)
    importer.start()
    importer.join(timeout)
    while not events.empty():
        try:
            events.get_nowait()
        except queue.Empty:
            break


def _sample_files() -> list[Path]:
    if not BOOKS_DIR.exists():
        return []
    return sorted(path for path in BOOKS_DIR.iterdir() if path.is_file())


def run_selftest() -> int:
    lines: list[str] = [
        f"Python: {sys.version.split()[0]}",
        f"База: {DB_PATH}",
        f"Книги: {BOOKS_DIR}",
    ]
    ok = True
    app = None
    reader = None
    dialogs: list[str] = []
    original_error = messagebox.showerror
    original_warning = messagebox.showwarning

    def fake_error(*args, **kwargs):
        dialogs.append(" ".join(str(arg) for arg in args))

    def fake_warning(*args, **kwargs):
        dialogs.append(" ".join(str(arg) for arg in args))

    messagebox.showerror = fake_error
    messagebox.showwarning = fake_warning
    try:
        db = LibraryDB(DB_PATH)
        issue = db.check_writable()
        lines.append("Запись в базу: " + ("OK" if not issue else f"ОШИБКА — {issue}"))
        if issue:
            ok = False
        _import_samples(db)
        rows = db.search(limit=500)
        lines.append(f"Книг в базе: {len(rows)}")
        if len(rows) < 1:
            ok = False
            lines.append("ОШИБКА: библиотека пуста")

        files = _sample_files()
        lines.append(f"Файлов в data/books: {len(files)}")

        sample_feed = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Test catalog</title>
<entry>
  <title>Sample book</title>
  <author><name>Sample author</name></author>
  <link rel="http://opds-spec.org/acquisition" type="application/epub+zip" href="/books/sample.epub"/>
</entry>
</feed>"""
        try:
            parsed = opds.parse_feed(sample_feed, "https://example.org/catalog/")
            entry = parsed.entries[0]
            lines.append(
                f"OPDS-парсер: записей {len(parsed.entries)}, "
                f"EPUB {entry.acquisitions.get('epub', '—')}"
            )
            if not entry.acquisitions.get("epub", "").endswith("/books/sample.epub"):
                ok = False
                lines.append("ОШИБКА: OPDS не разрешил относительную ссылку")
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"ОШИБКА OPDS: {exc}")

        stats = db.stats_overview(load_settings().monthly_goal_minutes)
        lines.append(
            f"Статистика: сегодня {stats['today_seconds']} с, "
            f"серия {stats['streak']} дн., цель {stats['goal_minutes']} мин"
        )
        if stats["today_seconds"] < 0 or "daily" not in stats or len(stats["daily"]) != 30:
            ok = False
            lines.append("ОШИБКА: статистика вернула некорректные данные")
        if dictionary.detect_language("привет") != "ru" or dictionary.detect_language("hello") != "en":
            ok = False
            lines.append("ОШИБКА: определение языка")
        else:
            lines.append("Словарь/перевод: определение языка работает")
        try:
            offline = dictionary.offline_stats()
            lines.append(f"Офлайн-словарь: {offline}")
            if not offline.get("ru") or not offline.get("en"):
                ok = False
                lines.append("ОШИБКА: офлайн-словарь не загрузился")
                error = dictionary.offline_last_error()
                if error:
                    lines.append(f"  {error}")
            local = dictionary.lookup("дама", "ru")
            if "офлайн" not in str(local.get("source", "")):
                ok = False
                lines.append("ОШИБКА: офлайн-статья не найдена")
            cache_key = "selftest:lookup"
            db.cache_set(cache_key, "ok")
            if db.cache_get(cache_key) != "ok":
                ok = False
                lines.append("ОШИБКА: кэш словаря не работает")
            db.cache_delete(cache_key)
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"ОШИБКА офлайн-словаря: {exc}")
        for path in files:
            try:
                meta = parse_meta(path)
                doc = load_document(path)
                if doc.format == "pdf":
                    detail = f"PDF, страниц {doc.page_count}"
                    if doc.page_count <= 0:
                        ok = False
                    # Проверяем, что первая страница рендерится.
                    from .formats.pdf import PdfBook

                    pdf = PdfBook(path)
                    image = pdf.render(0, 1.0)
                    if image.width < 10 or image.height < 10:
                        ok = False
                        lines.append(f"  ОШИБКА рендера PDF: {path.name}")
                    words = pdf.words(0)
                    lines.append(f"  PDF-слов на первой странице: {len(words)}")
                    pdf.close()
                else:
                    detail = f"блоков {len(doc.blocks)}, глав {len(doc.chapters)}"
                    if len(doc.blocks) < 1:
                        ok = False
                    if doc.format == "fb2" and "Стихи" in path.name:
                        if not doc.notes:
                            ok = False
                            lines.append("  ОШИБКА: не найдены сноски в стихах")
                        if not any(block.image for block in doc.blocks):
                            ok = False
                            lines.append("  ОШИБКА: не найдена иллюстрация в стихах")
                lines.append(f"  {path.name}: {meta['title']} / {meta['author']} — {detail}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                lines.append(f"  ОШИБКА {path.name}: {exc}")
                traceback.print_exc()

        # Вёрстка всех текстовых форматов.
        root = tk.Tk()
        root.withdraw()
        try:
            for path in files:
                try:
                    doc = load_document(path)
                    if doc.format == "pdf":
                        continue
                    result = layout_document(
                        doc, LayoutStyle(width=640, height=600, size=18), root
                    )
                    if len(result.pages) < 1 or not any(page.lines for page in result.pages):
                        ok = False
                        lines.append(f"  ОШИБКА вёрстки: {path.name}")
                    else:
                        lines.append(
                            f"  Вёрстка {path.name}: {len(result.pages)} стр."
                        )
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"  ОШИБКА вёрстки {path.name}: {exc}")
        finally:
            root.destroy()

        # Интерфейс библиотеки и читалки.
        from .ui.library import LibraryApp

        app = LibraryApp(load_settings(), show_wizard=False)
        app.suppress_dialogs = True
        _pump(app, 2.0)
        lines.append(f"Окно библиотеки: карточек {len(app.cards)}, всего {len(app.books)}")
        if not app.cards:
            ok = False
            lines.append("ОШИБКА: карточки не отрисованы")

        target = next(
            (row for row in rows if row["title"] == "Пиковая дама"),
            next((row for row in rows if row["format"] == "fb2"), rows[0] if rows else None),
        )
        if target is not None:
            app.select_book(int(target["id"]))
            _pump(app, 0.4)
            lines.append("Карточка книги: " + ("открыта" if app.detail_visible else "ОШИБКА"))
            if not app.detail_visible:
                ok = False
            app.open_book(int(target["id"]))
            _pump(app, 1.0)
            tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
            if tops:
                reader = tops[-1]
                for _ in range(100):
                    _pump(app, 0.1)
                    if getattr(reader, "_ready", False):
                        break
                pages = reader._total_pages() if hasattr(reader, "_total_pages") else 0
                lines.append(f"Читалка: страниц {pages}, элементов {len(reader.canvas.find_all())}")
                if pages < 1:
                    ok = False
                try:
                    first = next(
                        segment
                        for page in reader.pages
                        for line in page.lines
                        for segment in line.segments
                        if segment.block_index >= 0
                    )
                    source = reader.doc.blocks[first.block_index].text()
                    exact = source[first.start:first.end]
                    if exact != first.text:
                        ok = False
                        lines.append("ОШИБКА: смещения текста не совпадают")
                    else:
                        annotation_id = db.add_annotation(
                            int(target["id"]), "green", first.block_index, first.start,
                            first.block_index, first.end, first.text, "selftest",
                        )
                        reader._reload_annotations()
                        reader._open_panel("notes")
                        _pump(app, 0.5)
                        if reader.panel_name != "notes":
                            ok = False
                            lines.append("ОШИБКА: панель заметок не открылась")
                        else:
                            lines.append("Заметки и выделения: панель открыта")
                        reader._close_panel()
                        db.delete_annotation(annotation_id)
                        reader._reload_annotations()
                        _pump(app, 0.3)
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА заметок: {exc}")
                reader.next_page()
                _pump(app, 0.2)
                reader._open_panel("toc")
                _pump(app, 0.8)
                if reader.panel_name != "toc":
                    ok = False
                reader._close_panel()
                reader._open_panel("search")
                _pump(app, 0.4)
                if hasattr(reader, "search_entry"):
                    reader.search_entry.set("Пиковая")
                    reader._do_search()
                    _pump(app, 0.5)
                    hint = reader.search_hint.cget("text")
                    lines.append(f"Поиск: {hint}")
                    if "Найдено: 0" in hint:
                        ok = False
                reader.close()
                _pump(app, 0.5)
                try:
                    sessions = db.conn.execute(
                        "SELECT COUNT(*) FROM reading_sessions"
                    ).fetchone()[0]
                    lines.append(f"Сессий чтения: {sessions}")
                    if sessions < 1:
                        ok = False
                        lines.append("ОШИБКА: сессия чтения не записалась")
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА сессий: {exc}")
                try:
                    app.open_stats()
                    _pump(app, 0.8)
                    stats_window = getattr(app, "stats_window", None)
                    if stats_window is None or not stats_window.winfo_exists():
                        ok = False
                        lines.append("ОШИБКА: окно статистики не открылось")
                    else:
                        lines.append("Окно статистики: открыто")
                        stats_window.destroy()
                        app.stats_window = None
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА статистики: {exc}")
                try:
                    app.open_notes()
                    _pump(app, 0.8)
                    notes_window = getattr(app, "notes_window", None)
                    if notes_window is None or not notes_window.winfo_exists():
                        ok = False
                        lines.append("ОШИБКА: окно всех заметок не открылось")
                    else:
                        lines.append("Все заметки: окно открыто")
                        notes_window.destroy()
                        app.notes_window = None
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА всех заметок: {exc}")
                try:
                    app.show_help()
                    _pump(app, 0.6)
                    help_window = getattr(app, "help_window", None)
                    if help_window is None or not help_window.winfo_exists():
                        ok = False
                        lines.append("ОШИБКА: справка не открылась")
                    else:
                        lines.append("Быстрый старт: справка открыта")
                        help_window.destroy()
                        app.help_window = None
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА справки: {exc}")
                try:
                    from .ui.about import AboutWindow

                    about = AboutWindow(app, app.palette)
                    _pump(app, 0.4)
                    if not about.winfo_exists():
                        ok = False
                        lines.append("ОШИБКА: окно «О программе» не открылось")
                    else:
                        lines.append("О программе: лицензии доступны")
                        about.destroy()
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    lines.append(f"ОШИБКА окна «О программе»: {exc}")
            else:
                ok = False
                lines.append("ОШИБКА: окно чтения не открылось")

        if dialogs:
            ok = False
            lines.append("ОШИБКА: диалоги — " + "; ".join(dialogs))
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append("ОШИБКА: " + str(exc))
        lines.append(traceback.format_exc())
    finally:
        messagebox.showerror = original_error
        messagebox.showwarning = original_warning
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        if app is not None:
            try:
                app._on_close()
            except Exception:
                pass

    lines.append("ИТОГ: " + ("OK" if ok else "ПРОБЛЕМЫ"))
    log = _log(lines)
    for line in lines:
        _say(line)
    _say(f"Отчёт: {log}")
    return 0 if ok else 1


def run_repair() -> int:
    import sqlite3

    lines = [f"База: {DB_PATH}"]
    ok = True
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        try:
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            lines.append(f"wal_checkpoint: {checkpoint}")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            lines.append(f"integrity_check: {integrity}")
            if not integrity or str(integrity[0]).lower() != "ok":
                ok = False
        finally:
            conn.close()
    except sqlite3.Error as exc:
        ok = False
        lines.append(f"ОШИБКА: {exc}")
    try:
        db = LibraryDB(DB_PATH)
        removed = db.remove_missing()
        lines.append(f"Убрано отсутствующих книг: {removed}")
        lines.append(f"Книг осталось: {db.counts().get('total', 0)}")
        db.close()
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"ОШИБКА: {exc}")
    lines.append("ИТОГ: " + ("OK" if ok else "ПРОБЛЕМЫ"))
    log = _log(lines, "repair.log")
    for line in lines:
        _say(line)
    _say(f"Отчёт: {log}")
    return 0 if ok else 1


# ---------------------------------------------------------------------- снимки
def _capture(widget, target: Path) -> bool:
    try:
        from .winutil import capture_window, is_mostly_black
    except Exception:
        capture_window = None
        is_mostly_black = None
    image = None
    if capture_window is not None:
        try:
            image = capture_window(widget)
        except Exception:
            image = None
    if image is None:
        from PIL import ImageGrab

        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        image = ImageGrab.grab(
            bbox=(x, y, x + widget.winfo_width(), y + widget.winfo_height())
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return bool(image)


def screenshot_from_argv(argv: list[str]):
    if "--shot" not in argv:
        return None
    index = argv.index("--shot")
    target = Path(argv[index + 1]) if len(argv) > index + 1 else DATA_DIR / "shot.png"
    delay = 5000
    book = ""
    page = 0
    panel = ""
    select = ""
    query = ""
    rest = argv[index + 2:]
    for pos, item in enumerate(rest):
        if item == "--book" and pos + 1 < len(rest):
            book = rest[pos + 1]
        elif item == "--select" and pos + 1 < len(rest):
            select = rest[pos + 1]
        elif item == "--page" and pos + 1 < len(rest):
            try:
                page = int(rest[pos + 1])
            except ValueError:
                pass
        elif item == "--panel" and pos + 1 < len(rest):
            panel = rest[pos + 1]
        elif item == "--query" and pos + 1 < len(rest):
            query = rest[pos + 1]
    if rest and rest[0].isdigit():
        delay = int(rest[0])

    def action() -> int:
        from .ui.library import LibraryApp
        from .ui.reader import ReaderWindow

        app = LibraryApp(show_wizard=False)
        app.geometry("1440x900+30+20")
        app.attributes("-topmost", True)
        app.lift()
        holder: dict = {}

        def capture_library() -> None:
            if select:
                found = app.db.search(select, limit=1)
                if found:
                    app.select_book(int(found[0]["id"]))
            app.update_idletasks()
            app.update()
            _capture(app, target)
            _say(f"Сохранено: {target}")
            app.destroy()

        def open_reader(attempt: int = 0) -> None:
            if getattr(app, "importing", False) and attempt < 80:
                app.after(120, lambda: open_reader(attempt + 1))
                return
            found = app.db.search(book, limit=1)
            if not found and attempt < 40:
                app.after(150, lambda: open_reader(attempt + 1))
                return
            if not found:
                _say(f"Книга не найдена: {book}")
                app.destroy()
                return
            row = found[0]
            app.select_book(int(row["id"]))
            app.withdraw()
            reader = ReaderWindow(
                app, row, app.settings, app.db, app.palette, app.cover_cache,
                on_close=lambda _bid: None,
            )
            holder["reader"] = reader

            def prepare() -> None:
                for _ in range(120):
                    _pump(app, 0.1)
                    if getattr(reader, "_ready", False):
                        break
                if page:
                    reader.go_to_page(page)
                if panel:
                    reader._open_panel(panel)
                if panel == "search" and query:
                    try:
                        reader.search_entry.set(query)
                        reader._do_search()
                    except Exception:
                        pass
                app.after(700, capture_reader)

            def capture_reader() -> None:
                reader.update_idletasks()
                reader.update()
                _capture(reader, target)
                _say(f"Сохранено: {target}")
                reader.close()
                app.destroy()

            app.after(1500, prepare)

        if book:
            app.after(1200, open_reader)
        else:
            app.after(delay, capture_library)
        app.mainloop()
        return 0

    return action
