"""Главное окно: библиотека, поиск, карточки книг, импорт папок."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from ..config import (
    APP_ICON, APP_NAME, APP_TAGLINE, APP_VERSION, Settings, fit_geometry, human_size,
    load_settings,
)
from ..covers import ensure_cover
from ..db import LibraryDB
from ..formats import format_title
from ..importer import ImportResult, Importer
from ..theme import Palette, palette
from .icons import draw_icon
from .widgets import (
    Chip,
    CoverCache,
    Divider,
    IconButton,
    PillButton,
    ProgressBar,
    ScrollFrame,
    SearchEntry,
    Tooltip,
    configure_ttk,
    round_rect,
)

log = logging.getLogger(__name__)
UI = "Segoe UI"
SERIF = "Georgia"

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_BASE = TkinterDnD.Tk
    _DND_AVAILABLE = True
except Exception:  # noqa: BLE001
    DND_FILES = None
    _DND_BASE = tk.Tk
    _DND_AVAILABLE = False

CARD_W = 176
CARD_H = 338
CARD_COVER = (170, 255)
LIST_COVER = (54, 80)

SORTS = [
    ("recent", "Недавние"),
    ("title", "По названию"),
    ("author", "По автору"),
    ("year", "По году"),
    ("progress", "По прогрессу"),
    ("added", "По добавлению"),
]
SORT_LABELS = dict(SORTS)
SORT_KEYS = {label: key for key, label in SORTS}

FORMATS = [("all", "Все"), ("fb2", "FB2"), ("epub", "EPUB"), ("pdf", "PDF"), ("txt", "TXT")]


def plural(number: int, one: str, few: str, many: str) -> str:
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def short_author(value: str, limit: int = 30) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    cut = value[:limit]
    comma = cut.rfind(",")
    if comma > 8:
        cut = cut[:comma]
    return cut.rstrip(" ,;") + "…"


class NavItem(tk.Frame):
    def __init__(self, master, palette: Palette, icon: str, text: str,
                 command: Callable, *, active: bool = False, count: int = 0) -> None:
        self.palette = palette
        self.icon = icon
        self.text = text
        self.command = command
        self.active = active
        self.count = count
        self._hover = False
        super().__init__(master, bg=palette.panel, height=40, cursor="hand2")
        self.pack_propagate(False)
        self._bar = tk.Frame(self, width=3, bg=palette.accent if active else palette.panel)
        self._bar.pack(side="left", fill="y")
        self._icon = tk.Canvas(self, width=34, height=40, bg=palette.panel,
                               highlightthickness=0, bd=0)
        self._icon.pack(side="left")
        self._label = tk.Label(self, text=text, bg=palette.panel,
                               fg=palette.accent if active else palette.text,
                               font=(UI, 10, "bold" if active else "normal"), anchor="w")
        self._label.pack(side="left", fill="both", expand=True)
        self._count = tk.Label(self, text=str(count) if count else "", bg=palette.panel,
                               fg=palette.muted, font=(UI, 8), padx=10)
        self._count.pack(side="right")
        for widget in (self, self._icon, self._label, self._count, self._bar):
            widget.bind("<Button-1>", lambda _e: self.command())
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
        self._draw()

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _draw(self) -> None:
        palette = self.palette
        bg = palette.accent_soft if self.active else (palette.card if self._hover else palette.panel)
        for widget in (self, self._icon, self._label, self._count):
            widget.configure(bg=bg)
        self._bar.configure(bg=palette.accent if self.active else bg)
        self._label.configure(
            fg=palette.accent if self.active else palette.text,
            font=(UI, 10, "bold" if self.active else "normal"),
        )
        self._icon.delete("all")
        draw_icon(self._icon, self.icon, 17, 20, 17,
                  palette.accent if self.active else palette.muted)

    def set_count(self, count: int) -> None:
        self._count.configure(text=str(count) if count else "")

    def set_active(self, active: bool) -> None:
        self.active = active
        self._draw()


class BookCard(tk.Frame):
    def __init__(self, master, app: "LibraryApp", row) -> None:
        self.app = app
        self.row = row
        self.palette = app.palette
        self.book_id = int(row["id"])
        super().__init__(master, width=CARD_W, height=CARD_H, bg=self.palette.bg,
                         cursor="hand2")
        self.grid_propagate(False)
        self._photo = None
        self._hover = False
        self._selected = False

        self.cover = tk.Label(self, bg=self.palette.bg, bd=0,
                              highlightthickness=0, highlightbackground=self.palette.accent)
        self.cover.place(x=3, y=0, width=CARD_COVER[0], height=CARD_COVER[1])
        photo = app.cover_cache.get(row["cover"], CARD_COVER, radius=7)
        if photo:
            self.cover.configure(image=photo)
            self._photo = photo
        else:
            self.cover.configure(
                text=(row["title"] or "Книга")[:40], fg=self.palette.muted,
                font=(SERIF, 10), wraplength=150, justify="center",
            )

        self.progress = ProgressBar(self, width=CARD_COVER[0], height=3,
                                    palette=self.palette, bg=self.palette.bg)
        self.progress.place(x=3, y=CARD_COVER[1] + 3)
        self.progress.set(float(row["progress"] or 0))

        self.title = tk.Label(
            self, text=row["title"] or "Без названия", bg=self.palette.bg,
            fg=self.palette.text, font=(SERIF, 10, "bold"), anchor="nw",
            justify="left", wraplength=170,
        )
        self.title.place(x=3, y=CARD_COVER[1] + 12, width=170, height=38)
        author = short_author(row["author"] or "Автор неизвестен")
        self.author = tk.Label(
            self, text=author, bg=self.palette.bg, fg=self.palette.muted,
            font=(UI, 8), anchor="nw", justify="left", wraplength=170,
        )
        self.author.place(x=3, y=CARD_COVER[1] + 51, width=170, height=16)

        meta_parts = [format_title(row["format"])]
        if row["year"]:
            meta_parts.append(str(row["year"]))
        if row["progress"]:
            meta_parts.append(f"{float(row['progress']):.0f}%")
        self.meta = tk.Label(
            self, text="  ·  ".join(meta_parts), bg=self.palette.bg,
            fg=self.palette.dim, font=(UI, 7), anchor="nw",
        )
        self.meta.place(x=3, y=CARD_COVER[1] + 69, width=170, height=14)

        for widget in (self, self.cover, self.title, self.author, self.meta, self.progress):
            widget.bind("<Button-1>", self._select)
            widget.bind("<Double-Button-1>", self._open)
            widget.bind("<Button-3>", self._menu)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _select(self, _event=None) -> None:
        self.app.select_book(self.book_id)

    def _open(self, _event=None) -> None:
        self.app.open_book(self.book_id)

    def _menu(self, event) -> None:
        self.app.book_menu(self.book_id, event.x_root, event.y_root)

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw_hover()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self.after(30, self._check_hover)

    def _check_hover(self) -> None:
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            widget = None
        inside = False
        while widget is not None:
            if widget is self:
                inside = True
                break
            widget = getattr(widget, "master", None)
        if not inside:
            self._hover = False
            self._draw_hover()

    def _draw_hover(self) -> None:
        active = self._hover or self._selected
        self.cover.configure(
            highlightthickness=1 if active else 0,
            highlightbackground=self.palette.accent if self._selected else self.palette.border_light,
        )
        self.title.configure(fg=self.palette.accent if active else self.palette.text)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._draw_hover()


class BookRow(tk.Frame):
    def __init__(self, master, app: "LibraryApp", row) -> None:
        self.app = app
        self.row = row
        self.book_id = int(row["id"])
        self.palette = app.palette
        super().__init__(master, bg=app.palette.card, height=94, cursor="hand2")
        self.pack_propagate(False)
        self._photo = None
        self._selected = False
        self._hover = False
        cover = tk.Label(self, bg=app.palette.card, bd=0)
        cover.place(x=12, y=9, width=LIST_COVER[0], height=LIST_COVER[1])
        photo = app.cover_cache.get(row["cover"], LIST_COVER, radius=5)
        if photo:
            cover.configure(image=photo)
            self._photo = photo
        title = tk.Label(self, text=row["title"], bg=app.palette.card, fg=app.palette.text,
                         font=(SERIF, 11, "bold"), anchor="w")
        title.place(x=82, y=12, relwidth=1.0, width=-210, height=24)
        author = tk.Label(self, text=short_author(row["author"] or "Автор неизвестен"),
                          bg=app.palette.card,
                          fg=app.palette.muted, font=(UI, 8), anchor="w")
        author.place(x=82, y=38, relwidth=1.0, width=-210, height=18)
        meta = "  ·  ".join(filter(None, [
            format_title(row["format"]), str(row["year"] or ""),
            f"{float(row['progress'] or 0):.0f}%" if row["progress"] else "",
        ]))
        info = tk.Label(self, text=meta, bg=app.palette.card, fg=app.palette.dim,
                        font=(UI, 8), anchor="w")
        info.place(x=82, y=60, relwidth=1.0, width=-210, height=16)
        self.progress = ProgressBar(self, width=170, height=3, palette=app.palette,
                                    bg=app.palette.card)
        self.progress.place(relx=1.0, x=-190, y=68)
        self.progress.set(float(row["progress"] or 0))
        for widget in (self, cover, title, author, info, self.progress):
            widget.bind("<Button-1>", lambda _e: app.select_book(self.book_id))
            widget.bind("<Double-Button-1>", lambda _e: app.open_book(self.book_id))
            widget.bind("<Button-3>", lambda e: app.book_menu(self.book_id, e.x_root, e.y_root))
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _enter(self, _event=None) -> None:
        self._hover = True
        self.configure(bg=self.palette.card_hover)

    def _leave(self, _event=None) -> None:
        self._hover = False
        if not self._selected:
            self.configure(bg=self.palette.card)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self.configure(bg=self.palette.card_hover if value else self.palette.card)


class LibraryApp(_DND_BASE):
    def __init__(self, settings: Settings | None = None, show_wizard: bool = True) -> None:
        super().__init__()
        self.settings = settings or load_settings()
        self.show_wizard = show_wizard
        self.onboarding_window = None
        self.help_window = None
        self.palette = palette(self.settings.ui_theme)
        configure_ttk(self, self.palette)
        self.db = LibraryDB()
        self.cover_cache = CoverCache()
        self.books: list = []
        self.cards: list = []
        self.selected_id: int | None = None
        self.status_filter = "all"
        self.format_filter = self.settings.filter_format if self.settings.filter_format else "all"
        self.sort_key = self.settings.sort if self.settings.sort in SORT_LABELS else "recent"
        self.search_query = ""
        self.importing = False
        self._import_queue: queue.Queue = queue.Queue()
        self._importer: Importer | None = None
        self._search_after = None
        self._import_total = 0
        self._import_done = 0
        self._counts: dict = {}
        self.detail_visible = False
        self._closed = False

        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        self.configure(bg=self.palette.bg)
        self.minsize(1120, 700)
        try:
            fit_geometry(self, self.settings.window_geometry, 1120, 700)
        except tk.TclError:
            self.geometry("1400x860")
        self._set_icon()
        self._build()
        self._apply_simple_mode()
        self._setup_dnd()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-f>", lambda _e: self.search.focus())
        self.bind("<Control-o>", lambda _e: self.add_folder())
        self.bind("<F1>", lambda _e: self.show_help())
        self.bind("<Control-h>", lambda _e: self.show_help())
        self.bind("<Return>", lambda _e: self._open_selected())
        self.bind("<Escape>", lambda _e: self._clear_search_or_selection())
        self.after(120, self._poll_import)
        self.after(350, lambda: self.start_import(self.settings.folders))
        self.after(550, self._maybe_show_onboarding)

    # ------------------------------------------------------------------ окно
    def _set_icon(self) -> None:
        icon = APP_ICON
        try:
            if icon.exists():
                self.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    def _build(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.sidebar = tk.Frame(self, bg=self.palette.panel, width=232)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(self, bg=self.palette.bg)
        self.main.grid(row=0, column=1, sticky="nsew")
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self) -> None:
        palette = self.palette
        for child in self.sidebar.winfo_children():
            child.destroy()
        logo = tk.Frame(self.sidebar, bg=palette.panel, height=98)
        logo.pack(fill="x", pady=(14, 0))
        logo.pack_propagate(False)
        mark = tk.Canvas(logo, width=46, height=46, bg=palette.panel,
                         highlightthickness=0, bd=0)
        mark.place(x=20, y=18)
        round_rect(mark, 1, 1, 45, 45, 12, fill=palette.accent_soft, outline="")
        draw_icon(mark, "book", 23, 23, 24, palette.accent, width=1.7)
        tk.Label(logo, text=APP_NAME, bg=palette.panel, fg=palette.text,
                 font=(SERIF, 18, "bold"), anchor="w").place(x=76, y=17)
        tk.Label(logo, text=APP_TAGLINE, bg=palette.panel, fg=palette.muted,
                 font=(UI, 8), anchor="w").place(x=77, y=45)

        tk.Label(self.sidebar, text="БИБЛИОТЕКА", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", padx=22, pady=(18, 6))

        self.nav_all = NavItem(self.sidebar, palette, "library", "Все книги",
                               lambda: self._set_status_filter("all"), active=self.status_filter == "all")
        self.nav_all.pack(fill="x", padx=10, pady=1)
        self.nav_reading = NavItem(self.sidebar, palette, "book", "Читаю",
                                   lambda: self._set_status_filter("reading"))
        self.nav_reading.pack(fill="x", padx=10, pady=1)
        self.nav_done = NavItem(self.sidebar, palette, "check", "Прочитано",
                                lambda: self._set_status_filter("done"))
        self.nav_done.pack(fill="x", padx=10, pady=1)
        self.nav_fav = NavItem(self.sidebar, palette, "heart", "Избранное",
                               lambda: self._set_status_filter("favorite"))
        self.nav_fav.pack(fill="x", padx=10, pady=1)
        self.nav_stats = NavItem(self.sidebar, palette, "chart", "Статистика",
                                 self.open_stats)
        self.nav_stats.pack(fill="x", padx=10, pady=1)
        self.nav_notes = NavItem(self.sidebar, palette, "note", "Заметки",
                                 self.open_notes)
        self.nav_notes.pack(fill="x", padx=10, pady=1)
        self.nav_catalogs = NavItem(self.sidebar, palette, "globe", "Каталоги",
                                    self.open_catalogs)
        self.nav_catalogs.pack(fill="x", padx=10, pady=1)

        tk.Label(self.sidebar, text="ПАПКИ", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        self._folder_box = tk.Frame(self.sidebar, bg=palette.panel)
        self._folder_box.pack(fill="x", padx=14)
        self._render_folders()

        bottom = tk.Frame(self.sidebar, bg=palette.panel)
        bottom.pack(side="bottom", fill="x", pady=14, padx=14)
        Divider(bottom, palette).pack(fill="x", pady=(0, 10))
        self.simple_var = tk.BooleanVar(value=bool(self.settings.simple_mode))
        self.simple_check = tk.Checkbutton(
            bottom, text="  Только чтение", variable=self.simple_var,
            command=self._toggle_simple_mode, bg=palette.panel, fg=palette.muted,
            activebackground=palette.panel, activeforeground=palette.text,
            selectcolor=palette.panel, font=(UI, 8), anchor="w",
            bd=0, highlightthickness=0, cursor="hand2",
        )
        self.simple_check.pack(fill="x", pady=(0, 6))
        Tooltip(self.simple_check, "Скрыть каталоги и статистику", palette)
        row = tk.Frame(bottom, bg=palette.panel)
        row.pack(fill="x")
        self.theme_button = IconButton(
            row, palette, "sun" if self.settings.ui_theme == "dark" else "moon",
            self._toggle_theme, size=32, tooltip="Светлая тема" if self.settings.ui_theme == "dark" else "Тёмная тема",
            bg=palette.panel,
        )
        self.theme_button.pack(side="left")
        IconButton(row, palette, "refresh", lambda: self.start_import(self.settings.folders, force=True),
                   size=32, tooltip="Обновить библиотеку", bg=palette.panel).pack(side="left", padx=4)
        tk.Label(bottom, text=f"версия {APP_VERSION}", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7), anchor="w").pack(fill="x", pady=(6, 0))

    def _render_folders(self) -> None:
        palette = self.palette
        for child in self._folder_box.winfo_children():
            child.destroy()
        folders = [f for f in self.settings.folders if Path(f).exists()]
        for folder in folders[:3]:
            item = tk.Frame(self._folder_box, bg=palette.panel, height=28, cursor="hand2")
            item.pack(fill="x")
            icon = tk.Canvas(item, width=22, height=26, bg=palette.panel,
                             highlightthickness=0, bd=0)
            icon.pack(side="left")
            draw_icon(icon, "folder", 11, 13, 13, palette.muted)
            name = Path(folder).name or folder
            label = tk.Label(item, text=name, bg=palette.panel, fg=palette.muted,
                             font=(UI, 8), anchor="w")
            label.pack(side="left", fill="x", expand=True)
            Tooltip(item, folder, palette)
        add = tk.Label(self._folder_box, text="+  Добавить папку", bg=palette.panel,
                       fg=palette.accent, font=(UI, 8, "bold"), anchor="w", cursor="hand2")
        add.pack(fill="x", pady=(4, 0))
        add.bind("<Button-1>", lambda _e: self.add_folder())

    def _build_main(self) -> None:
        palette = self.palette
        for child in self.main.winfo_children():
            child.destroy()
        self.main.grid_rowconfigure(3, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        top = tk.Frame(self.main, bg=palette.bg)
        top.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 8))
        title_box = tk.Frame(top, bg=palette.bg)
        title_box.pack(side="left", fill="y")
        tk.Label(title_box, text="Библиотека", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 24, "bold"), anchor="w").pack(anchor="w")
        self.subtitle = tk.Label(title_box, text="", bg=palette.bg, fg=palette.muted,
                                 font=(UI, 9), anchor="w")
        self.subtitle.pack(anchor="w")

        right = tk.Frame(top, bg=palette.bg)
        right.pack(side="right", fill="y")
        self.add_button = PillButton(right, palette, "Добавить книги", self._add_menu,
                                     icon="plus", height=38, font_size=9)
        self.add_button.pack(side="right", padx=(12, 0))
        IconButton(right, palette, "help", self.show_help, size=36,
                   tooltip="Как пользоваться (F1)").pack(side="right", padx=(4, 0))
        self.view_list = IconButton(right, palette, "list", lambda: self._set_view("list"),
                                    size=36, tooltip="Списком")
        self.view_list.pack(side="right", padx=(4, 0))
        self.view_grid = IconButton(right, palette, "grid", lambda: self._set_view("grid"),
                                    size=36, tooltip="Обложками")
        self.view_grid.pack(side="right", padx=(4, 0))
        self.sort_box = ttk.Combobox(
            right, values=[label for _, label in SORTS], state="readonly",
            width=14, style="Chitalka.TCombobox", font=(UI, 9),
        )
        self.sort_box.set(SORT_LABELS.get(self.sort_key, "Недавние"))
        self.sort_box.pack(side="right", padx=(4, 10), ipady=2)
        self.sort_box.bind("<<ComboboxSelected>>", self._on_sort)
        self.search = SearchEntry(right, palette, "Название, автор, жанр…", width=290,
                                  command=self._on_search)
        self.search.pack(side="right", padx=(0, 12))
        self.search.configure(height=40)

        self.continue_bar = tk.Frame(self.main, bg=palette.bg)
        self.continue_bar.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.continue_bar.grid_remove()

        filters = tk.Frame(self.main, bg=palette.bg)
        filters.grid(row=2, column=0, sticky="ew", padx=28, pady=(2, 10))
        self.chips: dict[str, Chip] = {}
        for index, (key, label) in enumerate(FORMATS):
            chip = Chip(filters, palette, label,
                        lambda k=key: self._set_format(k), selected=self.format_filter == key)
            chip.pack(side="left", padx=(0 if index == 0 else 8, 0))
            self.chips[key] = chip

        body = tk.Frame(self.main, bg=palette.bg)
        body.grid(row=3, column=0, sticky="nsew", padx=(28, 20), pady=(0, 0))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.body = body
        self.grid_scroll = ScrollFrame(body, palette, bg=palette.bg)
        self.grid_scroll.grid(row=0, column=0, sticky="nsew")
        self.grid_scroll.canvas.bind(
            "<Configure>", lambda _e: self.after_idle(self._layout_grid), add="+"
        )
        self.detail = tk.Frame(body, bg=palette.panel, width=344)
        self.detail.grid(row=0, column=1, sticky="ns", padx=(18, 8))
        self.detail.grid_propagate(False)
        self.detail.pack_propagate(False)
        self.detail.grid_remove()
        self.detail_visible = False

        status = tk.Frame(self.main, bg=palette.bg, height=38)
        status.grid(row=4, column=0, sticky="ew", padx=28, pady=(6, 10))
        self.status_left = tk.Label(status, text="", bg=palette.bg, fg=palette.muted,
                                    font=(UI, 8), anchor="w")
        self.status_left.pack(side="left")
        self.status_progress = ProgressBar(status, width=120, height=4, palette=palette,
                                           bg=palette.bg)
        self.status_progress.pack(side="right", padx=(8, 0))
        self.status_right = tk.Label(status, text="", bg=palette.bg, fg=palette.dim,
                                     font=(UI, 8), anchor="e")
        self.status_right.pack(side="right")

        self._update_view_buttons()

    # ------------------------------------------------------------------ данные
    def _refresh(self, keep_scroll: bool = True) -> None:
        scroll = self.grid_scroll.yview() if keep_scroll else 0.0
        self._counts = self.db.counts()
        self.books = self.db.search(
            self.search_query, fmt=self.format_filter, status=self.status_filter,
            sort=self.sort_key, limit=800,
        )
        if self.selected_id and not any(int(row["id"]) == self.selected_id for row in self.books):
            self.selected_id = None
        self._update_sidebar_counts()
        self._update_chips()
        total = self._counts.get("total", 0)
        authors = self._counts.get("authors", 0)
        self.subtitle.configure(
            text=f"{total} {plural(total, 'книга', 'книги', 'книг')}  ·  "
                 f"{authors} {plural(authors, 'автор', 'автора', 'авторов')}"
        )
        self._rebuild_books()
        self._refresh_continue()
        self._render_detail()
        self.after_idle(lambda: self.grid_scroll.restore(scroll) if keep_scroll else None)
        if not self.importing:
            self._update_status()

    def _refresh_continue(self) -> None:
        if not hasattr(self, "continue_bar"):
            return
        for child in self.continue_bar.winfo_children():
            child.destroy()
        if self.detail_visible or self._counts.get("total", 0) <= 0:
            self.continue_bar.grid_remove()
            return
        row = self.db.last_read()
        if row is None:
            self.continue_bar.grid_remove()
            return
        palette = self.palette
        self.continue_bar.grid()
        panel = tk.Frame(self.continue_bar, bg=palette.panel)
        panel.pack(fill="x")
        cover = tk.Label(panel, bg=palette.panel, bd=0)
        cover.pack(side="left", padx=(14, 12), pady=9)
        photo = self.cover_cache.get(row["cover"], (34, 48), radius=4)
        if photo:
            cover.configure(image=photo)
            cover._photo = photo  # type: ignore[attr-defined]
        else:
            cover.configure(text=(row["title"] or "?")[:1], fg=palette.muted,
                            font=(SERIF, 14, "bold"))
        box = tk.Frame(panel, bg=palette.panel)
        box.pack(side="left", fill="x", expand=True, pady=9)
        tk.Label(box, text="ПРОДОЛЖИТЬ ЧТЕНИЕ", bg=palette.panel, fg=palette.dim,
                 font=(UI, 6, "bold"), anchor="w").pack(fill="x")
        tk.Label(box, text=row["title"] or "Без названия", bg=palette.panel,
                 fg=palette.text, font=(SERIF, 11, "bold"), anchor="w").pack(fill="x")
        progress = float(row["progress"] or 0)
        detail = f"{progress:.0f}% прочитано · {row['author'] or 'автор неизвестен'}"
        tk.Label(box, text=detail, bg=palette.panel, fg=palette.muted,
                 font=(UI, 7), anchor="w").pack(fill="x", pady=(2, 0))
        label = "Перечитать" if progress >= 99 else "Продолжить"
        PillButton(panel, palette, label, lambda book_id=int(row["id"]): self.open_book(book_id),
                   kind="primary", height=34, font_size=8,
                   bg=palette.panel).pack(side="right", padx=14)

    def _update_sidebar_counts(self) -> None:
        counts = self._counts
        self.nav_all.set_count(counts.get("total", 0))
        self.nav_reading.set_count(counts.get("reading", 0))
        self.nav_done.set_count(counts.get("done", 0))
        self.nav_fav.set_count(counts.get("favorite", 0))

    def _update_chips(self) -> None:
        formats = self._counts.get("formats", {})
        for key, chip in self.chips.items():
            chip.set_count(self._counts.get("total", 0) if key == "all" else formats.get(key, 0))
            chip.set_selected(key == self.format_filter)

    def _rebuild_books(self) -> None:
        self.grid_scroll.clear()
        self.cards = []
        inner = self.grid_scroll.inner
        if not self.books:
            self._show_empty(inner)
            self._update_status()
            return
        if self.settings.view == "list":
            for row in self.books:
                item = BookRow(inner, self, row)
                item.pack(fill="x", pady=4)
                item.set_selected(int(row["id"]) == self.selected_id)
                self.cards.append(item)
        else:
            for index, row in enumerate(self.books):
                card = BookCard(inner, self, row)
                card.grid(row=0, column=index, padx=7, pady=8, sticky="n")
                card.set_selected(int(row["id"]) == self.selected_id)
                self.cards.append(card)
            self.after_idle(self._layout_grid)
        self._update_status()

    def _show_empty(self, parent) -> None:
        palette = self.palette
        frame = tk.Frame(parent, bg=palette.bg)
        frame.pack(expand=True, fill="both", pady=120)
        icon = tk.Canvas(frame, width=64, height=64, bg=palette.bg,
                         highlightthickness=0, bd=0)
        icon.pack()
        draw_icon(icon, "book", 32, 32, 40, palette.dim, width=1.5)
        filtered = bool(self.search_query or self.format_filter != "all"
                        or self.status_filter != "all")
        if filtered:
            title = "Ничего не найдено"
            text = "Попробуйте изменить запрос или снять фильтры."
        else:
            title = "Начните с книг"
            text = ("Добавьте папку или файлы. Подойдут FB2, EPUB, PDF и TXT.\n"
                    "Или скачайте книгу из Gutenberg / Викитеки.\n"
                    "Двойной клик по обложке — открыть книгу.")
        tk.Label(frame, text=title, bg=palette.bg, fg=palette.text,
                 font=(SERIF, 18, "bold")).pack(pady=(14, 6))
        tk.Label(frame, text=text, bg=palette.bg, fg=palette.muted,
                 font=(UI, 9), justify="center").pack()
        if filtered:
            PillButton(frame, palette, "Сбросить фильтры", self._reset_filters,
                       kind="soft", height=36).pack(pady=16)
        else:
            PillButton(frame, palette, "Добавить папку", self.add_folder,
                       icon="folder", kind="primary", height=38).pack(pady=(16, 4))
            PillButton(frame, palette, "Добавить файлы", self.add_files,
                       icon="plus", kind="soft", height=36).pack(pady=4)
            if not self.settings.simple_mode:
                PillButton(frame, palette, "Скачать из Gutenberg", self.open_catalogs,
                           icon="globe", kind="ghost", height=36).pack(pady=4)
            link = tk.Label(frame, text="Как это работает (F1)", bg=palette.bg,
                            fg=palette.accent, font=(UI, 8), cursor="hand2")
            link.pack(pady=(10, 0))
            link.bind("<Button-1>", lambda _e: self.show_help())

    def _layout_grid(self) -> None:
        if self.settings.view != "grid" or not self.cards:
            return
        width = max(200, self.grid_scroll.canvas.winfo_width())
        columns = max(1, min(7, (width + 14) // (CARD_W + 14)))
        columns = min(columns, max(1, len(self.cards)))
        inner = self.grid_scroll.inner
        for index, card in enumerate(self.cards):
            card.grid(row=index // columns, column=index % columns, padx=7, pady=8, sticky="n")
        for column in range(7):
            inner.grid_columnconfigure(column, weight=1 if column < columns else 0)
        for row in range((len(self.cards) + columns - 1) // columns):
            pass

    def _update_status(self) -> None:
        if self.importing:
            return
        total = self._counts.get("total", 0)
        self.status_left.configure(
            text=f"{len(self.books)} из {total} {plural(total, 'книги', 'книг', 'книг')}"
            if len(self.books) != total else
            f"Всего {total} {plural(total, 'книга', 'книги', 'книг')}"
        )
        self.status_right.configure(text="Библиотека готова")
        self.status_progress.set(100)

    # ------------------------------------------------------------------ фильтры
    def _on_search(self, value: str) -> None:
        self.search_query = value
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(220, lambda: self._refresh())

    def _set_status_filter(self, status: str) -> None:
        self.status_filter = status
        for item, key in ((self.nav_all, "all"), (self.nav_reading, "reading"),
                          (self.nav_done, "done"), (self.nav_fav, "favorite")):
            item.set_active(key == status)
        self.grid_scroll.scroll_to_top()
        self._refresh(keep_scroll=False)

    def _set_format(self, fmt: str) -> None:
        self.format_filter = fmt
        self.settings.filter_format = fmt
        self._update_chips()
        self.grid_scroll.scroll_to_top()
        self._refresh(keep_scroll=False)

    def _set_view(self, view: str) -> None:
        self.settings.view = view
        self.settings.save()
        self._update_view_buttons()
        self._refresh(keep_scroll=False)

    def _update_view_buttons(self) -> None:
        self.view_grid.set_active(self.settings.view == "grid")
        self.view_list.set_active(self.settings.view == "list")

    def _on_sort(self, _event=None) -> None:
        self.sort_key = SORT_KEYS.get(self.sort_box.get(), "recent")
        self.settings.sort = self.sort_key
        self.settings.save()
        self._refresh(keep_scroll=False)

    def _reset_filters(self) -> None:
        self.search.set("")
        self.search_query = ""
        self.format_filter = "all"
        self.status_filter = "all"
        for item, key in ((self.nav_all, "all"), (self.nav_reading, "reading"),
                          (self.nav_done, "done"), (self.nav_fav, "favorite")):
            item.set_active(key == "all")
        self._update_chips()
        self._refresh(keep_scroll=False)

    # ------------------------------------------------------------- выделение
    def select_book(self, book_id: int) -> None:
        self.selected_id = int(book_id)
        for card in self.cards:
            card.set_selected(getattr(card, "book_id", 0) == self.selected_id)
        self._render_detail()

    def _render_detail(self) -> None:
        palette = self.palette
        for child in self.detail.winfo_children():
            child.destroy()
        if not self.selected_id:
            self.detail.grid_remove()
            self.detail_visible = False
            self._refresh_continue()
            self.after_idle(self._layout_grid)
            return
        row = self.db.get(self.selected_id)
        if row is None:
            self.selected_id = None
            self.detail.grid_remove()
            self.detail_visible = False
            self._refresh_continue()
            return
        self.detail.grid()
        self.detail_visible = True

        footer = tk.Frame(self.detail, bg=palette.panel)
        footer.pack(side="bottom", fill="x", padx=20, pady=16)
        scroll = ScrollFrame(self.detail, palette, bg=palette.panel)
        scroll.pack(fill="both", expand=True)
        wrap = tk.Frame(scroll.inner, bg=palette.panel)
        wrap.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        head = tk.Frame(wrap, bg=palette.panel)
        head.pack(fill="x")
        tk.Label(head, text="О КНИГЕ", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(side="left")
        IconButton(head, palette, "close", self._deselect, size=28,
                   bg=palette.panel, tooltip="Скрыть").pack(side="right")

        cover_h = 236
        cover_w = 157
        cover = tk.Label(wrap, bg=palette.panel, bd=0)
        cover.pack(pady=(8, 12))
        photo = self.cover_cache.get(row["cover"], (cover_w, cover_h), radius=8)
        if photo:
            cover.configure(image=photo)
            cover._photo = photo  # type: ignore[attr-defined]
        else:
            cover.configure(text=row["title"], fg=palette.muted, font=(SERIF, 10),
                            wraplength=150, justify="center")

        tk.Label(wrap, text=row["title"], bg=palette.panel, fg=palette.text,
                 font=(SERIF, 16, "bold"), wraplength=286, justify="left",
                 anchor="w").pack(fill="x")
        tk.Label(wrap, text=row["author"] or "Автор неизвестен", bg=palette.panel,
                 fg=palette.accent, font=(UI, 9), anchor="w", justify="left",
                 wraplength=286).pack(fill="x", pady=(3, 8))

        meta_bits = [format_title(row["format"])]
        if row["year"]:
            meta_bits.append(str(row["year"]))
        if row["genre"]:
            meta_bits.append(str(row["genre"]))
        tk.Label(wrap, text="  ·  ".join(meta_bits), bg=palette.panel, fg=palette.muted,
                 font=(UI, 8), anchor="w", justify="left", wraplength=286).pack(fill="x")
        tk.Label(wrap, text=f"{Path(row['path']).name}  ·  {human_size(row['size'])}",
                 bg=palette.panel, fg=palette.dim, font=(UI, 7), anchor="w",
                 justify="left", wraplength=286).pack(fill="x", pady=(5, 0))

        if row["series"]:
            tk.Label(wrap, text=f"Серия: {row['series']}", bg=palette.panel,
                     fg=palette.muted, font=(UI, 8), anchor="w").pack(fill="x", pady=(3, 0))

        description = (row["description"] or "").strip()
        if description:
            tk.Frame(wrap, bg=palette.border, height=1).pack(fill="x", pady=(12, 8))
            text = tk.Text(wrap, height=6, bg=palette.panel, fg=palette.muted,
                           font=(UI, 9), relief="flat", wrap="word", bd=0,
                           highlightthickness=0, spacing1=1, spacing3=4,
                           cursor="arrow")
            text.insert("1.0", description)
            text.configure(state="disabled")
            text.pack(fill="x")

        progress = float(row["progress"] or 0)
        if progress > 0:
            tk.Frame(wrap, bg=palette.border, height=1).pack(fill="x", pady=(12, 8))
            line = tk.Frame(wrap, bg=palette.panel)
            line.pack(fill="x")
            tk.Label(line, text="Прогресс", bg=palette.panel, fg=palette.muted,
                     font=(UI, 8)).pack(side="left")
            tk.Label(line, text=f"{progress:.0f}%", bg=palette.panel, fg=palette.accent,
                     font=(UI, 8, "bold")).pack(side="right")
            bar = ProgressBar(wrap, width=280, height=4, palette=palette, bg=palette.panel)
            bar.pack(fill="x", pady=(4, 0))
            bar.set(progress)

        if progress >= 99:
            label = "Перечитать"
        elif progress > 0:
            label = "Продолжить"
        else:
            label = "Читать"
        PillButton(footer, palette, label, lambda: self.open_book(self.selected_id),
                   kind="primary", height=40, bg=palette.panel).pack(fill="x")
        small = tk.Frame(footer, bg=palette.panel)
        small.pack(fill="x", pady=(8, 0))
        favorite = bool(row["favorite"])
        PillButton(small, palette, "В избранном" if favorite else "В избранное",
                   lambda: self._toggle_favorite(self.selected_id),
                   icon="heart", kind="soft", height=32, font_size=8,
                   bg=palette.panel).pack(side="left", fill="x", expand=True)
        PillButton(small, palette, "Ещё", lambda: self._detail_menu(), icon="more",
                   kind="ghost", height=32, font_size=8, bg=palette.panel).pack(
            side="left", padx=(6, 0)
        )
        self.after_idle(self._layout_grid)
        self._refresh_continue()

    def _deselect(self) -> None:
        self.selected_id = None
        for card in self.cards:
            card.set_selected(False)
        self._render_detail()

    def _toggle_favorite(self, book_id: int | None) -> None:
        if not book_id:
            return
        self.db.toggle_favorite(book_id)
        self._refresh()
        self._render_detail()

    def _detail_menu(self) -> None:
        if not self.selected_id:
            return
        row = self.db.get(self.selected_id)
        menu = self._make_menu()
        menu.add_command(label="Открыть папку", command=lambda: self._open_folder(row["path"]))
        menu.add_command(label="Отметить прочитанной",
                         command=lambda: self._set_status(self.selected_id, "done"))
        menu.add_command(label="Вернуть в «Читаю»",
                         command=lambda: self._set_status(self.selected_id, "reading"))
        menu.add_separator()
        menu.add_command(label="Удалить из библиотеки",
                         command=lambda: self._remove_book(self.selected_id))
        x = self.detail.winfo_rootx() + self.detail.winfo_width() - 24
        y = self.detail.winfo_rooty() + self.detail.winfo_height() - 70
        menu.tk_popup(x, y)

    # ------------------------------------------------------------------ меню
    def _make_menu(self) -> tk.Menu:
        return tk.Menu(
            self, tearoff=0, bg=self.palette.card, fg=self.palette.text,
            activebackground=self.palette.accent_soft, activeforeground=self.palette.accent,
            bd=0, relief="flat", font=(UI, 9), activeborderwidth=0,
        )

    def _add_menu(self) -> None:
        menu = self._make_menu()
        menu.add_command(label="Добавить папку…", command=self.add_folder)
        menu.add_command(label="Добавить файлы…", command=self.add_files)
        menu.add_separator()
        menu.add_command(label="Обновить библиотеку",
                         command=lambda: self.start_import(self.settings.folders, force=True))
        menu.add_command(label="Убрать отсутствующие", command=self._remove_missing)
        menu.add_separator()
        menu.add_command(label="Резервная копия…", command=self.backup_library)
        menu.add_command(label="Восстановить из копии…", command=self.restore_library)
        x = self.add_button.winfo_rootx()
        y = self.add_button.winfo_rooty() + self.add_button.winfo_height() + 4
        menu.tk_popup(x, y)

    def backup_library(self) -> None:
        from ..backup import create_backup

        default = f"chitalka-backup-{date.today():%Y-%m-%d}.zip"
        path = filedialog.asksaveasfilename(
            parent=self, title="Сохранить резервную копию", defaultextension=".zip",
            initialfile=default, filetypes=[("Архив", "*.zip")],
        )
        if not path:
            return
        try:
            result = create_backup(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Резервная копия", f"Не удалось сохранить:\n{exc}",
                                 parent=self)
            return
        self.status_right.configure(text=f"Копия сохранена: {Path(result).name}")

    def restore_library(self) -> None:
        from ..backup import restore_backup

        path = filedialog.askopenfilename(
            parent=self, title="Восстановить из резервной копии",
            filetypes=[("Архив", "*.zip")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Восстановление",
            "Заменить текущую библиотеку, настройки и обложки данными из копии?\n"
            "Текущая база будет сохранена рядом как .before-restore.",
            parent=self,
        ):
            return
        try:
            self.db.close()
            restore_backup(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Восстановление", f"Не удалось восстановить:\n{exc}",
                                 parent=self)
            self.db = LibraryDB()
            return
        messagebox.showinfo(
            "Восстановление",
            "Библиотека восстановлена. Приложение будет закрыто — запустите его снова.",
            parent=self,
        )
        self.destroy()

    def book_menu(self, book_id: int, x: int, y: int) -> None:
        row = self.db.get(book_id)
        if not row:
            return
        menu = self._make_menu()
        menu.add_command(label="Читать", command=lambda: self.open_book(book_id))
        menu.add_command(label="Показать сведения", command=lambda: self.select_book(book_id))
        menu.add_separator()
        menu.add_command(label="В избранном" if row["favorite"] else "В избранное",
                         command=lambda: (self.db.toggle_favorite(book_id), self._refresh()))
        menu.add_command(label="Отметить прочитанной",
                         command=lambda: self._set_status(book_id, "done"))
        menu.add_command(label="Вернуть в «Читаю»",
                         command=lambda: self._set_status(book_id, "reading"))
        menu.add_separator()
        menu.add_command(label="Открыть папку", command=lambda: self._open_folder(row["path"]))
        menu.add_command(label="Удалить из библиотеки",
                         command=lambda: self._remove_book(book_id))
        menu.tk_popup(x, y)

    def _set_status(self, book_id: int, status: str) -> None:
        self.db.set_status(book_id, status)
        self._refresh()
        self._render_detail()

    def _remove_book(self, book_id: int) -> None:
        row = self.db.get(book_id)
        if not row:
            return
        if not messagebox.askyesno(
            "Удалить из библиотеки",
            f"Убрать «{row['title']}» из библиотеки?\n\nСам файл на диске останется.",
            parent=self,
        ):
            return
        self.db.remove(book_id)
        if self.selected_id == book_id:
            self.selected_id = None
        self._refresh()
        self._render_detail()

    def _remove_missing(self) -> None:
        removed = self.db.remove_missing()
        self._refresh()
        self.status_right.configure(text=f"Убрано отсутствующих: {removed}")

    def _open_folder(self, path: str) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(path))])
        except OSError:
            try:
                os.startfile(str(Path(path).parent))  # type: ignore[attr-defined]
            except OSError:
                pass

    # ------------------------------------------------------------------ импорт
    def add_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="Папка с книгами (FB2, EPUB, PDF, TXT)",
            mustexist=True,
        )
        if not folder:
            return
        folder = str(Path(folder))
        if folder not in self.settings.folders:
            self.settings.folders.append(folder)
            self.settings.save()
            self._render_folders()
        self.start_import([folder])

    def add_files(self) -> None:
        files = filedialog.askopenfilenames(
            parent=self, title="Добавить книги",
            filetypes=[
                ("Книги", "*.fb2 *.fb2.zip *.epub *.pdf *.txt"),
                ("FB2", "*.fb2 *.fb2.zip"),
                ("EPUB", "*.epub"),
                ("PDF", "*.pdf"),
                ("Текст", "*.txt"),
                ("Все файлы", "*.*"),
            ],
        )
        if files:
            self.start_import(list(files))

    def start_import(self, paths, force: bool = False) -> None:
        if self.importing:
            return
        paths = [str(path) for path in paths if str(path)]
        if not paths:
            self.status_right.configure(text="Добавьте папку с книгами")
            return
        self.importing = True
        self._import_total = 0
        self._import_done = 0
        self.status_right.configure(text="Поиск книг…")
        self.status_progress.set(0)
        self._importer = Importer(self.db, paths, self._import_queue, force=force)
        self._importer.start()

    def _poll_import(self) -> None:
        if self._closed:
            return
        try:
            while True:
                event = self._import_queue.get_nowait()
                kind = event[0]
                if kind == "total":
                    self._import_total = int(event[1])
                    self.status_right.configure(text=f"Найдено книг: {self._import_total}")
                elif kind == "tick":
                    index, total, name, action = event[1], event[2], event[3], event[4]
                    self._import_done = index
                    self._import_total = total
                    percent = index / max(1, total) * 100
                    self.status_progress.set(percent)
                    self.status_right.configure(
                        text=f"Импорт {index} из {total}  ·  {name[:38]}"
                    )
                elif kind == "done":
                    result: ImportResult = event[1]
                    self.importing = False
                    self.status_progress.set(100)
                    self._refresh()
                    if result.added or result.updated:
                        message = f"Добавлено {result.added}, обновлено {result.updated}"
                    else:
                        message = "Библиотека актуальна"
                    if result.errors:
                        message += f"  ·  ошибок {len(result.errors)}"
                    self.status_right.configure(text=message)
                    if result.errors:
                        log.warning("Ошибки импорта: %s", result.errors[:5])
                elif kind == "scan":
                    self.status_right.configure(text="Поиск книг…")
        except queue.Empty:
            pass
        self.after(120, self._poll_import)

    # ------------------------------------------------------------------ темы
    def _toggle_theme(self) -> None:
        self.settings.ui_theme = "light" if self.settings.ui_theme == "dark" else "dark"
        self.settings.save()
        self.palette = palette(self.settings.ui_theme)
        configure_ttk(self, self.palette)
        self.configure(bg=self.palette.bg)
        for child in self.winfo_children():
            child.destroy()
        self._build()
        self._refresh()
        self._render_detail()

    # ------------------------------------------------------------------ книги
    def open_book(self, book_id: int | None, *, start_page: int | None = None,
                  start_block: int | None = None) -> None:
        if not book_id:
            return
        row = self.db.get(book_id)
        if not row:
            return
        path = Path(row["path"])
        if not path.exists():
            messagebox.showerror("Файл не найден", f"Книга не найдена:\n{path}", parent=self)
            return
        try:
            from .reader import ReaderWindow
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ошибка", f"Не удалось открыть читалку:\n{exc}", parent=self)
            return
        self.withdraw()
        try:
            ReaderWindow(
                self, row, self.settings, self.db, self.palette, self.cover_cache,
                on_close=self._reader_closed,
                start_page=start_page, start_block=start_block,
            )
        except Exception as exc:  # noqa: BLE001
            self.deiconify()
            messagebox.showerror("Ошибка чтения", f"{exc}", parent=self)
            log.exception("Не удалось открыть книгу")

    def _reader_closed(self, book_id: int) -> None:
        self.deiconify()
        self.lift()
        self.selected_id = None
        self.settings.last_book_id = int(book_id)
        self.settings.save()
        self._refresh()
        self._render_detail()
        stats = getattr(self, "stats_window", None)
        if stats is not None:
            try:
                if stats.winfo_exists():
                    stats.refresh()
            except tk.TclError:
                self.stats_window = None
        notes = getattr(self, "notes_window", None)
        if notes is not None:
            try:
                if notes.winfo_exists():
                    notes.refresh()
            except tk.TclError:
                self.notes_window = None

    def show_help(self) -> None:
        from .help import HelpWindow

        window = getattr(self, "help_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.lift()
                    window.focus_set()
                    return
            except tk.TclError:
                pass
        try:
            self.help_window = HelpWindow(self, self.palette)
            self.help_window.lift()
            self.help_window.focus_set()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Справка", str(exc), parent=self)

    def _open_selected(self) -> None:
        if self.selected_id:
            self.open_book(self.selected_id)

    def _clear_search_or_selection(self) -> None:
        if self.search.get():
            self.search.set("")
            return
        if self.selected_id:
            self._deselect()

    def open_notes(self) -> None:
        from .allnotes import NotesWindow

        window = getattr(self, "notes_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.lift()
                    window.refresh()
                    return
            except tk.TclError:
                pass
        try:
            self.notes_window = NotesWindow(
                self, self.db, self.palette, on_open=self._open_annotation,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Заметки", f"Не удалось открыть заметки:\n{exc}",
                                 parent=self)

    def _open_annotation(self, book_id: int, annotation) -> None:
        row = self.db.get(book_id)
        if not row:
            return
        if row["format"] == "pdf":
            page = max(0, int(annotation["page"] or 0))
            self.open_book(book_id, start_page=page)
        else:
            block = max(0, int(annotation["start_block"] or 0))
            self.open_book(book_id, start_block=block)

    def open_stats(self) -> None:
        from .stats import StatsWindow

        stats = getattr(self, "stats_window", None)
        if stats is not None:
            try:
                if stats.winfo_exists():
                    stats.lift()
                    stats.refresh()
                    return
            except tk.TclError:
                pass
        try:
            self.stats_window = StatsWindow(
                self, self.settings, self.db, self.palette, self.cover_cache
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Статистика", f"Не удалось открыть статистику:\n{exc}",
                                 parent=self)

    def open_catalogs(self) -> None:
        from .catalog import CatalogWindow

        catalog = getattr(self, "catalog_window", None)
        if catalog is not None:
            try:
                if catalog.winfo_exists():
                    catalog.lift()
                    return
            except tk.TclError:
                pass
        try:
            self.catalog_window = CatalogWindow(
                self, self.settings, self.db, self.palette, self.cover_cache,
                on_imported=self._catalog_imported,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Каталоги", f"Не удалось открыть каталоги:\n{exc}",
                                 parent=self)

    def _catalog_imported(self) -> None:
        self._refresh()
        if self.selected_id:
            self._render_detail()

    # ------------------------------------------------------------------ простой режим
    def _apply_simple_mode(self) -> None:
        if not hasattr(self, "nav_stats"):
            return
        simple = bool(self.settings.simple_mode)
        if hasattr(self, "simple_var"):
            self.simple_var.set(simple)
        if simple:
            self.nav_stats.pack_forget()
            self.nav_catalogs.pack_forget()
            for attr in ("stats_window", "catalog_window"):
                window = getattr(self, attr, None)
                if window is not None:
                    try:
                        window.destroy()
                    except tk.TclError:
                        pass
                    setattr(self, attr, None)
        else:
            self.nav_stats.pack(fill="x", padx=10, pady=1, before=self.nav_notes)
            self.nav_catalogs.pack(fill="x", padx=10, pady=1, after=self.nav_notes)

    def _toggle_simple_mode(self) -> None:
        self.settings.simple_mode = bool(self.simple_var.get())
        self.settings.save()
        self._apply_simple_mode()
        self._refresh()

    def _maybe_show_onboarding(self) -> None:
        if not self.show_wizard or self.settings.onboarding_done:
            return
        if self.onboarding_window is not None:
            try:
                if self.onboarding_window.winfo_exists():
                    return
            except tk.TclError:
                pass
        from .wizard import OnboardingWizard

        self.onboarding_window = OnboardingWizard(
            self, self.palette, on_finish=self._finish_onboarding,
            on_add_folder=self.add_folder, on_add_files=self.add_files,
            on_catalogs=self.open_catalogs,
        )

    def _finish_onboarding(self, simple_mode: bool) -> None:
        self.settings.simple_mode = bool(simple_mode)
        self.settings.onboarding_done = True
        self.settings.save()
        self._apply_simple_mode()
        self._refresh()
        self.onboarding_window = None

    # ------------------------------------------------------------------ drag & drop
    def _setup_dnd(self) -> None:
        if not _DND_AVAILABLE:
            return
        self.drop_hint = tk.Label(
            self, text="Отпустите файлы или папку, чтобы добавить в библиотеку",
            bg=self.palette.accent_soft, fg=self.palette.text,
            font=(UI, 10, "bold"), padx=24, pady=14,
            bd=1, relief="solid", highlightthickness=0,
        )
        targets = [self, self.sidebar, self.main, self.body,
                   self.grid_scroll.canvas]
        for widget in targets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            except Exception:
                continue

    def _on_drop_enter(self, _event=None):
        if self._closed:
            return
        try:
            self.drop_hint.place(relx=0.5, rely=0.5, anchor="center")
            self.drop_hint.lift()
        except tk.TclError:
            pass
        return "copy"

    def _on_drop_leave(self, _event=None):
        try:
            self.drop_hint.place_forget()
        except tk.TclError:
            pass
        return "copy"

    def _on_drop(self, event):
        try:
            self.drop_hint.place_forget()
        except tk.TclError:
            pass
        try:
            paths = [str(path) for path in self.tk.splitlist(event.data)]
        except Exception:
            paths = [str(event.data)]
        folders = []
        files = []
        supported = {".fb2", ".epub", ".pdf", ".txt"}
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                folders.append(str(path))
                continue
            name = path.name.lower()
            if path.suffix.lower() in supported or name.endswith(".fb2.zip"):
                files.append(str(path))
        for folder in folders:
            if folder not in self.settings.folders:
                self.settings.folders.append(folder)
        if folders:
            self.settings.save()
            self._render_folders()
        queue_paths = folders + files
        if queue_paths:
            self.start_import(queue_paths)
        else:
            self.status_right.configure(text="Эти файлы не подходят: нужны FB2, EPUB, PDF или TXT")
        return "copy"

    # ------------------------------------------------------------------ закрытие
    def _on_close(self) -> None:
        self._closed = True
        if self._importer and self._importer.is_alive():
            self._importer.stop()
        try:
            self.settings.window_geometry = self.geometry()
            self.settings.view = self.settings.view
            self.settings.filter_format = self.format_filter
            self.settings.sort = self.sort_key
            self.settings.last_book_id = self.selected_id or 0
            self.settings.save()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()


def run() -> int:
    app = LibraryApp()
    app.mainloop()
    return 0
