"""Все заметки библиотеки: список, поиск и экспорт в Markdown."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from ..db import LibraryDB
from ..theme import Palette
from .icons import draw_icon
from .notes import NOTE_COLOR_LABELS, note_color
from .widgets import IconButton, PillButton, ScrollFrame, SearchEntry

UI = "Segoe UI"
SERIF = "Georgia"


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


class NotesWindow(tk.Toplevel):
    def __init__(self, master, db: LibraryDB, palette: Palette, *,
                 on_open: Callable[[int, object], None]) -> None:
        super().__init__(master)
        self.db = db
        self.palette = palette
        self.on_open = on_open
        self.title("Все заметки")
        self.configure(bg=palette.bg)
        width, height = 860, 680
        x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(620, 480)
        self.transient(master)
        self._build()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())

    def _build(self) -> None:
        palette = self.palette
        outer = tk.Frame(self, bg=palette.bg)
        outer.pack(fill="both", expand=True, padx=22, pady=18)
        header = tk.Frame(outer, bg=palette.bg)
        header.pack(fill="x")
        tk.Label(header, text="Все заметки", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 22, "bold"), anchor="w").pack(side="left")
        IconButton(header, palette, "close", self.close, size=32,
                   bg=palette.bg, tooltip="Закрыть").pack(side="right")
        self.subtitle = tk.Label(outer, text="", bg=palette.bg, fg=palette.muted,
                                 font=(UI, 9), anchor="w")
        self.subtitle.pack(fill="x", pady=(2, 12))

        tools = tk.Frame(outer, bg=palette.bg)
        tools.pack(fill="x", pady=(0, 10))
        self.search = SearchEntry(tools, palette, "Книга, цитата, комментарий…",
                                  width=420, command=self.refresh)
        self.search.pack(side="left", fill="x", expand=True)
        PillButton(tools, palette, "Экспорт в Markdown", self.export_all,
                   kind="soft", height=36, font_size=8,
                   bg=palette.bg).pack(side="right", padx=(10, 0))

        self.body = tk.Frame(outer, bg=palette.bg)
        self.body.pack(fill="both", expand=True)
        self.rows: list[tk.Widget] = []

    def refresh(self, _value=None) -> None:
        if not hasattr(self, "body"):
            return
        for child in self.body.winfo_children():
            child.destroy()
        query = self.search.get().strip().lower()
        try:
            annotations = self.db.all_annotations()
        except Exception:
            annotations = []
        if query:
            annotations = [
                row for row in annotations
                if query in " ".join((
                    str(row["book_title"] or ""), str(row["book_author"] or ""),
                    str(row["quote"] or ""), str(row["comment"] or ""),
                )).lower()
            ]
        total = len(annotations)
        books = len({int(row["book_id"]) for row in annotations})
        if total % 10 == 1 and total % 100 != 11:
            notes_word = "заметка"
        elif 2 <= total % 10 <= 4 and not 12 <= total % 100 <= 14:
            notes_word = "заметки"
        else:
            notes_word = "заметок"
        if books % 10 == 1 and books % 100 != 11:
            books_word = "книга"
        elif 2 <= books % 10 <= 4 and not 12 <= books % 100 <= 14:
            books_word = "книги"
        else:
            books_word = "книг"
        self.subtitle.configure(
            text=f"{total} {notes_word} · {books} {books_word}" if total else "Пока нет заметок"
        )
        if not annotations:
            tk.Label(
                self.body, text="Выделите текст в читалке и добавьте маркер или заметку.",
                bg=self.palette.bg, fg=self.palette.muted, font=(UI, 10),
            ).pack(pady=60)
            return
        scroll = ScrollFrame(self.body, self.palette, bg=self.palette.bg)
        scroll.pack(fill="both", expand=True)
        current_book = None
        for annotation in annotations:
            book_id = int(annotation["book_id"])
            if book_id != current_book:
                current_book = book_id
                heading = tk.Frame(scroll.inner, bg=self.palette.bg)
                heading.pack(fill="x", pady=(12, 2))
                tk.Label(
                    heading, text=_short(str(annotation["book_title"] or ""), 60),
                    bg=self.palette.bg, fg=self.palette.text,
                    font=(SERIF, 12, "bold"), anchor="w",
                ).pack(side="left")
                author = str(annotation["book_author"] or "")
                if author:
                    tk.Label(
                        heading, text=_short(author, 42), bg=self.palette.bg,
                        fg=self.palette.muted, font=(UI, 8), anchor="e",
                    ).pack(side="right")
            row = tk.Frame(scroll.inner, bg=self.palette.panel, cursor="hand2")
            row.pack(fill="x", pady=2)
            swatch = tk.Canvas(row, width=5, height=64, bg=self.palette.panel,
                               highlightthickness=0, bd=0)
            swatch.pack(side="left", fill="y", padx=(0, 10))
            swatch.create_rectangle(
                0, 0, 5, 64, fill=note_color(str(annotation["color"])), outline=""
            )
            text_box = tk.Frame(row, bg=self.palette.panel)
            text_box.pack(side="left", fill="x", expand=True, pady=7)
            quote = " ".join(str(annotation["quote"]).split())
            quote_label = tk.Label(
                text_box, text=_short(quote, 110), bg=self.palette.panel,
                fg=self.palette.text, font=(SERIF, 9, "bold"), anchor="w",
                justify="left", wraplength=650,
            )
            quote_label.pack(fill="x")
            comment = " ".join(str(annotation["comment"] or "").split())
            comment_label = None
            if comment:
                comment_label = tk.Label(
                    text_box, text=_short(comment, 120), bg=self.palette.panel,
                    fg=self.palette.muted, font=(UI, 8), anchor="w",
                    justify="left", wraplength=650,
                )
                comment_label.pack(fill="x")
            page_raw = annotation["page"]
            page = int(page_raw) if page_raw is not None else -1
            page_text = f"стр. {page + 1}" if page >= 0 else "без страницы"
            color = NOTE_COLOR_LABELS.get(str(annotation["color"]), "маркер")
            meta = f"{page_text} · {color} · {str(annotation['book_format']).upper()}"
            tk.Label(
                text_box, text=meta, bg=self.palette.panel, fg=self.palette.dim,
                font=(UI, 7), anchor="w",
            ).pack(fill="x", pady=(2, 0))
            IconButton(row, self.palette, "trash",
                       lambda a=annotation: self._delete(a), size=26,
                       bg=self.palette.panel, tooltip="Удалить").pack(
                side="right", padx=(0, 6)
            )
            for widget in (row, text_box, quote_label):
                widget.bind("<Button-1>", lambda _e, a=annotation: self._open(a))
            if comment_label is not None:
                comment_label.bind(
                    "<Button-1>", lambda _e, a=annotation: self._open(a)
                )

    def _open(self, annotation) -> None:
        self.close()
        try:
            self.on_open(int(annotation["book_id"]), annotation)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Заметка", str(exc), parent=self)

    def _delete(self, annotation) -> None:
        if not messagebox.askyesno(
            "Удалить заметку", "Удалить эту заметку вместе с выделением?", parent=self
        ):
            return
        try:
            self.db.delete_annotation(int(annotation["id"]))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Заметка", str(exc), parent=self)
            return
        self.refresh()

    def export_all(self) -> None:
        try:
            annotations = self.db.all_annotations()
        except Exception:
            annotations = []
        if not annotations:
            messagebox.showinfo("Экспорт заметок", "В библиотеке пока нет заметок.",
                                parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self, title="Экспорт всех заметок в Markdown",
            defaultextension=".md", initialfile="Заметки библиотеки.md",
            filetypes=[("Markdown", "*.md"), ("Текст", "*.txt")],
        )
        if not target:
            return
        lines = ["# Заметки библиотеки", "", f"*Экспорт: {date.today():%d.%m.%Y}*", ""]
        current_book = None
        for annotation in annotations:
            book_id = int(annotation["book_id"])
            if book_id != current_book:
                current_book = book_id
                lines += [f"## {annotation['book_title']}", ""]
                if annotation["book_author"]:
                    lines += [f"**Автор:** {annotation['book_author']}", ""]
            page_raw = annotation["page"]
            page = int(page_raw) if page_raw is not None else -1
            page_text = f"Страница {page + 1}" if page >= 0 else "Без страницы"
            color = NOTE_COLOR_LABELS.get(str(annotation["color"]), "Маркер")
            lines += [f"*{page_text} · {color}*", ""]
            quote = str(annotation["quote"]).strip().replace("\n", "\n> ")
            lines += ["> " + quote, ""]
            comment = str(annotation["comment"] or "").strip()
            if comment:
                lines += [comment, ""]
            lines += ["---", ""]
        try:
            Path(target).write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Экспорт заметок", str(exc), parent=self)
            return
        self.subtitle.configure(text=f"Экспортировано: {Path(target).name}")

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass
