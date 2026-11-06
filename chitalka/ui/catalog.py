"""Окно каталогов: Project Gutenberg, Викитека и произвольные OPDS-ленты."""

from __future__ import annotations

import queue
import time
import tkinter as tk
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from .. import opds, wikisource
from ..config import APP_NAME, BOOKS_DIR, Settings, fit_geometry
from ..covers import ensure_cover
from ..db import LibraryDB
from ..formats import parse_meta
from ..theme import Palette
from .icons import draw_icon
from .widgets import (
    CoverCache,
    IconButton,
    PillButton,
    ScrollFrame,
    SearchEntry,
    ask_text,
    round_rect,
)

UI = "Segoe UI"
SERIF = "Georgia"
CARD_W = 170
CARD_H = 300
NAV_H = 150


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + "…"


class SourceRow(tk.Frame):
    def __init__(self, master, palette: Palette, title: str, subtitle: str,
                 command: Callable, *, selected: bool = False,
                 on_delete: Callable | None = None) -> None:
        self.palette = palette
        self.command = command
        self.selected = selected
        self.on_delete = on_delete
        self._hover = False
        super().__init__(master, bg=palette.panel, cursor="hand2")
        self._bar = tk.Frame(self, width=3, bg=palette.accent if selected else palette.panel)
        self._bar.pack(side="left", fill="y")
        icon = tk.Canvas(self, width=34, height=56, bg=palette.panel,
                         highlightthickness=0, bd=0)
        icon.pack(side="left", padx=(4, 0))
        draw_icon(icon, "globe", 17, 28, 17,
                  palette.accent if selected else palette.muted)
        text = tk.Frame(self, bg=palette.panel)
        text.pack(side="left", fill="both", expand=True, pady=8)
        self.title_label = tk.Label(
            text, text=_short(title, 28), bg=palette.panel,
            fg=palette.accent if selected else palette.text,
            font=(UI, 9, "bold" if selected else "normal"), anchor="w",
        )
        self.title_label.pack(fill="x")
        self.subtitle_label = tk.Label(
            text, text=_short(subtitle, 29), bg=palette.panel, fg=palette.muted,
            font=(UI, 7), anchor="w",
        )
        self.subtitle_label.pack(fill="x")
        for widget in (self, icon, text, self.title_label, self.subtitle_label, self._bar):
            widget.bind("<Button-1>", lambda _e: self.command())
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
            if on_delete is not None:
                widget.bind("<Button-3>", lambda e: self._menu(e))
        self._paint()

    def _menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0, bg=self.palette.card, fg=self.palette.text,
                       activebackground=self.palette.accent_soft,
                       activeforeground=self.palette.accent, bd=0, relief="flat",
                       font=(UI, 9))
        menu.add_command(label="Удалить каталог", command=self.on_delete)
        menu.tk_popup(event.x_root, event.y_root)

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._paint()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._paint()

    def _paint(self) -> None:
        palette = self.palette
        bg = palette.accent_soft if self.selected else (
            palette.card if self._hover else palette.panel
        )
        for widget in (self, self._bar.master, self.title_label, self.subtitle_label):
            widget.configure(bg=bg)
        for child in self.winfo_children():
            try:
                child.configure(bg=bg)
            except tk.TclError:
                pass
        self._bar.configure(bg=palette.accent if self.selected else bg)
        self.title_label.configure(
            fg=palette.accent if self.selected else palette.text,
            font=(UI, 9, "bold" if self.selected else "normal"),
        )
        self.subtitle_label.configure(fg=palette.muted)


class CatalogWindow(tk.Toplevel):
    def __init__(self, master, settings: Settings, db: LibraryDB,
                 palette: Palette, cover_cache: CoverCache,
                 on_imported: Callable | None = None) -> None:
        super().__init__(master)
        self.settings = settings
        self.db = db
        self.palette = palette
        self.cover_cache = cover_cache
        self.on_imported = on_imported
        self.queue: queue.Queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.closed = False
        self.req = 0
        self.download_seq = 0
        self.page: opds.CatalogPage | None = None
        self.source_key = ""
        self.state_key = ""
        self.source_name = ""
        self.state: tuple | None = None
        self.history: list[tuple] = []
        self.cards: list[tk.Frame] = []
        self.cards_parent: tk.Frame | None = None
        self.cover_labels: dict[str, list[tk.Label]] = {}
        self.cover_jobs: set[str] = set()
        self.detail_dialog: tk.Toplevel | None = None
        self._poll_job = None
        self._resize_job = None
        self._source_rows: dict[str, SourceRow] = {}

        self.title(f"Каталоги — {APP_NAME}")
        self.configure(bg=palette.bg)
        self.minsize(900, 620)
        try:
            fit_geometry(self, "1200x800+120+40", 900, 620)
        except tk.TclError:
            self.geometry("1200x800")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.after(120, lambda: self.select_source("gutenberg"))
        self._poll_job = self.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        palette = self.palette
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        sidebar = tk.Frame(self, bg=palette.panel, width=236)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.pack_propagate(False)

        logo = tk.Frame(sidebar, bg=palette.panel, height=80)
        logo.pack(fill="x", pady=(12, 0))
        logo.pack_propagate(False)
        mark = tk.Canvas(logo, width=38, height=38, bg=palette.panel,
                         highlightthickness=0, bd=0)
        mark.place(x=16, y=16)
        round_rect(mark, 1, 1, 37, 37, 10, fill=palette.accent_soft, outline="")
        draw_icon(mark, "globe", 19, 19, 20, palette.accent)
        tk.Label(logo, text="Каталоги", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 16, "bold"), anchor="w").place(x=62, y=15)
        tk.Label(logo, text="общественное достояние", bg=palette.panel, fg=palette.muted,
                 font=(UI, 7), anchor="w").place(x=63, y=40)

        tk.Label(sidebar, text="ИСТОЧНИКИ", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", padx=18, pady=(16, 6))
        self.sources_box = tk.Frame(sidebar, bg=palette.panel)
        self.sources_box.pack(fill="x", padx=8)
        self.add_button = PillButton(sidebar, palette, "Добавить OPDS", self._add_catalog,
                                     icon="plus", kind="soft", height=32, font_size=8,
                                     bg=palette.panel)
        self.add_button.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(sidebar, text="Любые каталоги OPDS 1/2\nможно добавить по ссылке.",
                 bg=palette.panel, fg=palette.dim, font=(UI, 7), justify="left",
                 anchor="w").pack(fill="x", padx=18, pady=(10, 0))
        self._refresh_sources()

        main = tk.Frame(self, bg=palette.bg)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        top = tk.Frame(main, bg=palette.panel, height=64)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        tk.Frame(top, bg=palette.border, height=1).pack(side="bottom", fill="x")
        IconButton(top, palette, "arrow_left", self._back, size=38,
                   tooltip="Назад").pack(side="left", padx=(12, 4), pady=12)
        title_box = tk.Frame(top, bg=palette.panel)
        title_box.pack(side="left", fill="both", expand=True, pady=8)
        self.title_label = tk.Label(title_box, text="Каталоги", bg=palette.panel,
                                    fg=palette.text, font=(SERIF, 13, "bold"), anchor="w")
        self.title_label.pack(fill="x")
        self.subtitle_label = tk.Label(title_box, text="", bg=palette.panel,
                                       fg=palette.muted, font=(UI, 8), anchor="w")
        self.subtitle_label.pack(fill="x")
        right = tk.Frame(top, bg=palette.panel)
        right.pack(side="right", padx=(0, 10), pady=12)
        IconButton(right, palette, "close", self.close, size=34,
                   tooltip="Закрыть").pack(side="right", padx=(4, 0))
        IconButton(right, palette, "refresh", self._reload, size=34,
                   tooltip="Обновить").pack(side="right", padx=2)
        self.search = SearchEntry(right, palette, "Поиск в каталоге…", width=250,
                                  command=None)
        self.search.pack(side="right", padx=(0, 8))
        self.search.entry.bind("<Return>", lambda _e: self._perform_search())
        PillButton(right, palette, "Найти", self._perform_search, kind="soft",
                   height=34, font_size=8).pack(side="right", padx=(0, 6))

        self.content = tk.Frame(main, bg=palette.bg)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.scroll = ScrollFrame(self.content, palette, bg=palette.bg)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.canvas.bind("<Configure>", self._on_canvas_resize, add="+")

        status = tk.Frame(main, bg=palette.bg, height=34)
        status.grid(row=2, column=0, sticky="ew", padx=22)
        self.status_label = tk.Label(status, text="", bg=palette.bg, fg=palette.muted,
                                     font=(UI, 8), anchor="w")
        self.status_label.pack(side="left")
        self.count_label = tk.Label(status, text="", bg=palette.bg, fg=palette.dim,
                                    font=(UI, 8), anchor="e")
        self.count_label.pack(side="right")

    # ------------------------------------------------------------- источники
    def _refresh_sources(self) -> None:
        for child in self.sources_box.winfo_children():
            child.destroy()
        self._source_rows = {}
        for source in opds.BUILTIN_CATALOGS:
            row = SourceRow(
                self.sources_box, self.palette, source.name, source.description,
                lambda key=source.key: self.select_source(key),
                selected=self.source_key == source.key,
            )
            row.pack(fill="x", pady=1)
            self._source_rows[source.key] = row
        custom = self.db.catalogs()
        if custom:
            tk.Frame(self.sources_box, bg=self.palette.border, height=1).pack(
                fill="x", pady=6, padx=8
            )
        for item in custom:
            key = f"custom:{item['id']}"
            row = SourceRow(
                self.sources_box, self.palette, item["name"],
                urllib.parse.urlparse(item["url"]).netloc,
                lambda key=key: self.select_source(key),
                selected=self.source_key == key,
                on_delete=lambda item=item: self._delete_catalog(item),
            )
            row.pack(fill="x", pady=1)
            self._source_rows[key] = row

    def _set_active_source(self, key: str) -> None:
        self.source_key = key
        self.state_key = "wikisource" if key == "wikisource" else "opds"
        for row_key, row in self._source_rows.items():
            row.selected = row_key == key
            row._paint()

    def select_source(self, key: str) -> None:
        self.history = []
        self._set_active_source(key)
        if key == "gutenberg":
            source = next(s for s in opds.BUILTIN_CATALOGS if s.key == key)
            self.source_name = source.name
            self._load_opds(source.url, source.name, push=False)
        elif key == "wikisource":
            self.source_name = "Викитека"
            self._load_wikisource_featured(push=False)
        else:
            try:
                catalog_id = int(key.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            row = next((item for item in self.db.catalogs()
                        if int(item["id"]) == catalog_id), None)
            if row is None:
                return
            self.source_name = row["name"]
            self._load_opds(row["url"], row["name"], push=False)

    def _add_catalog(self) -> None:
        name = ask_text(self, self.palette, "Новый OPDS-каталог", "Название каталога", "")
        if not name:
            return
        url = ask_text(self, self.palette, "Новый OPDS-каталог",
                       "Ссылка на OPDS-ленту (http:// или https://)", "https://")
        if not url:
            return
        try:
            url = opds.validate_url(url)
        except opds.OPDSFeedError as exc:
            messagebox.showerror("OPDS", str(exc), parent=self)
            return
        catalog_id = self.db.add_catalog(name.strip(), url)
        self._refresh_sources()
        self.select_source(f"custom:{catalog_id}")

    def _delete_catalog(self, row) -> None:
        if not messagebox.askyesno(
            "Удалить каталог", f"Удалить «{row['name']}» из списка?", parent=self
        ):
            return
        self.db.remove_catalog(int(row["id"]))
        if self.source_key == f"custom:{row['id']}":
            self.select_source("gutenberg")
        self._refresh_sources()

    # ------------------------------------------------------------- загрузка
    def _new_request(self) -> int:
        self.req += 1
        return self.req

    def _load_opds(self, url: str, title: str, push: bool = True) -> None:
        if push and self.state:
            self.history.append(self.state)
        self.state = ("opds", url, title)
        self.state_key = "opds"
        self._set_active_source(self.source_key)
        req = self._new_request()
        self._show_loading(f"Загружаю {title}…")
        self.status_label.configure(text="Соединение…")

        def worker() -> None:
            try:
                data, content_type, final_url = opds.fetch(url)
                page = opds.parse_feed(data, final_url)
                self.queue.put(("page", req, page))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", req, str(exc)))

        self.executor.submit(worker)

    def _load_wikisource_featured(self, push: bool = True) -> None:
        if push and self.state:
            self.history.append(self.state)
        self.state = ("ws-featured",)
        self.state_key = "wikisource"
        self._set_active_source("wikisource")
        self.req = self._new_request()
        self._show_loading("Открываю Викитеку…")
        request = self.req
        self.after(
            30,
            lambda: self._render_page(wikisource.featured())
            if not self.closed and request == self.req else None,
        )

    def _load_wikisource_search(self, query: str, push: bool = True) -> None:
        if push and self.state:
            self.history.append(self.state)
        self.state = ("ws-search", query)
        self.state_key = "wikisource"
        self._set_active_source("wikisource")
        req = self._new_request()
        self._show_loading(f"Поиск: {query}…")
        self.status_label.configure(text="Запрос к Викитеке…")

        def worker() -> None:
            try:
                page = wikisource.search(query)
                self.queue.put(("page", req, page))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", req, str(exc)))

        self.executor.submit(worker)

    def _load_wikisource_random(self, push: bool = True) -> None:
        if push and self.state:
            self.history.append(self.state)
        self.state = ("ws-random",)
        self.state_key = "wikisource"
        self._set_active_source("wikisource")
        req = self._new_request()
        self._show_loading("Случайные произведения…")
        self.status_label.configure(text="Запрос к Викитеке…")

        def worker() -> None:
            try:
                page = wikisource.random_works()
                self.queue.put(("page", req, page))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", req, str(exc)))

        self.executor.submit(worker)

    def _perform_search(self) -> None:
        query = self.search.get().strip()
        if not query:
            return
        if self.state_key == "wikisource" or self.source_key == "wikisource":
            self._load_wikisource_search(query, push=True)
            return
        if self.source_key == "gutenberg":
            template = next(
                source.search for source in opds.BUILTIN_CATALOGS
                if source.key == "gutenberg"
            )
            self._load_opds(template.format(query=urllib.parse.quote_plus(query)),
                            f"Gutenberg · {query}", push=True)
            return
        if self.page is None:
            return
        try:
            url = opds.resolve_search(self.page, query)
        except Exception as exc:  # noqa: BLE001
            self.status_label.configure(text=f"Ошибка поиска: {exc}")
            return
        if not url:
            self.status_label.configure(text="Этот каталог не поддерживает поиск")
            return
        self._load_opds(url, f"Поиск · {query}", push=True)

    def _reload(self) -> None:
        if not self.state:
            return
        state = self.state
        self._restore(state)

    def _back(self) -> None:
        if not self.history:
            self.status_label.configure(text="Это первый экран каталога")
            return
        state = self.history.pop()
        self._restore(state)

    def _restore(self, state: tuple) -> None:
        kind = state[0]
        if kind == "opds":
            self._load_opds(state[1], state[2], push=False)
        elif kind == "ws-featured":
            self._load_wikisource_featured(push=False)
        elif kind == "ws-search":
            self._load_wikisource_search(state[1], push=False)
        elif kind == "ws-random":
            self._load_wikisource_random(push=False)

    # ------------------------------------------------------------- отрисовка
    def _clear(self) -> None:
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        self.cards = []
        self.cards_parent = None
        self.cover_labels = {}

    def _show_loading(self, text: str) -> None:
        self._clear()
        self.page = None
        label = tk.Label(self.scroll.inner, text=text, bg=self.palette.bg,
                         fg=self.palette.muted, font=(SERIF, 12))
        label.pack(pady=100)
        self.title_label.configure(text=self.source_name or "Каталоги")
        self.subtitle_label.configure(text="")
        self.count_label.configure(text="")

    def _show_error(self, message: str) -> None:
        self._clear()
        frame = tk.Frame(self.scroll.inner, bg=self.palette.bg)
        frame.pack(pady=90)
        tk.Label(frame, text="Не удалось загрузить каталог", bg=self.palette.bg,
                 fg=self.palette.text, font=(SERIF, 15, "bold")).pack(pady=(0, 6))
        tk.Label(frame, text=message, bg=self.palette.bg, fg=self.palette.muted,
                 font=(UI, 9), wraplength=520, justify="center").pack()
        PillButton(frame, self.palette, "Повторить", self._reload,
                   kind="soft", height=34).pack(pady=14)
        self.status_label.configure(text="Ошибка")

    def _render_page(self, page: opds.CatalogPage) -> None:
        self.page = page
        self._clear()
        self.title_label.configure(text=page.title or self.source_name)
        subtitle = page.subtitle or ""
        self.subtitle_label.configure(text=subtitle)
        entries = self._merge_entries(page.entries)
        count = len(entries)
        if count % 10 == 1 and count % 100 != 11:
            word = "запись"
        elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
            word = "записи"
        else:
            word = "записей"
        self.count_label.configure(text=f"{count} {word}")
        self.status_label.configure(
            text="Выберите книгу или раздел"
            if entries else "Каталог пуст"
        )
        if not entries:
            tk.Label(self.scroll.inner, text="В этом каталоге пока нет записей.",
                     bg=self.palette.bg, fg=self.palette.muted,
                     font=(UI, 10)).pack(pady=90)
            return
        parent = tk.Frame(self.scroll.inner, bg=self.palette.bg)
        parent.pack(fill="both", expand=True, padx=22, pady=(12, 20))
        self.cards_parent = parent
        for entry in entries:
            card = self._make_card(parent, entry)
            self.cards.append(card)
        self.after_idle(self._layout_cards)
        if page.next_url:
            PillButton(self.scroll.inner, self.palette, "Показать ещё",
                       lambda: self._load_opds(page.next_url, page.title, push=True),
                       kind="soft", height=36).pack(pady=(0, 24))

    def _merge_entries(self, entries: list[opds.CatalogEntry]) -> list[opds.CatalogEntry]:
        merged: list[opds.CatalogEntry] = []
        index: dict[tuple[str, str], opds.CatalogEntry] = {}
        for entry in entries:
            key = (entry.title.strip().lower(), entry.author.strip().lower())
            existing = index.get(key)
            if existing is not None and not entry.nav_url and not existing.nav_url:
                for fmt, url in entry.acquisitions.items():
                    existing.acquisitions.setdefault(fmt, url)
                if not existing.image_url:
                    existing.image_url = entry.image_url
                if not existing.summary:
                    existing.summary = entry.summary
                continue
            index[key] = entry
            merged.append(entry)
        return merged

    def _make_card(self, parent: tk.Frame, entry: opds.CatalogEntry) -> tk.Frame:
        palette = self.palette
        nav = entry.is_navigation
        height = NAV_H if nav else CARD_H
        card = tk.Frame(parent, width=CARD_W, height=height, bg=palette.bg,
                        cursor="hand2", highlightthickness=0)
        card.grid_propagate(False)
        card._entry = entry  # type: ignore[attr-defined]
        card._widgets = []  # type: ignore[attr-defined]

        if nav:
            icon = tk.Canvas(card, width=40, height=40, bg=palette.bg,
                             highlightthickness=0, bd=0)
            icon.place(x=12, y=10)
            draw_icon(icon, "folder", 20, 20, 22, palette.accent)
            title = tk.Label(card, text=entry.title, bg=palette.bg, fg=palette.text,
                             font=(SERIF, 9, "bold"), anchor="nw", justify="left",
                             wraplength=148)
            title.place(x=10, y=52, width=150, height=66)
            kind = tk.Label(card, text="Раздел", bg=palette.bg, fg=palette.dim,
                            font=(UI, 7), anchor="w")
            kind.place(x=12, y=124, width=146, height=14)
            widgets = [card, icon, title, kind]
            for widget in widgets:
                widget.bind("<Button-1>", lambda _e, e=entry: self._open_entry(e))
                widget.bind("<Enter>", lambda _e, c=card: self._hover_card(c, True))
                widget.bind("<Leave>", lambda _e, c=card: self._hover_card(c, False))
            card._widgets = widgets  # type: ignore[attr-defined]
            return card

        cover = tk.Label(card, bg=palette.card, bd=0,
                         highlightthickness=1, highlightbackground=palette.border)
        cover.place(x=10, y=0, width=150, height=210)
        photo = self._cover_photo(entry)
        if photo is not None:
            cover.configure(image=photo)
            cover._photo = photo  # type: ignore[attr-defined]
        else:
            cover.configure(
                text=entry.title[:40], fg=palette.muted, font=(SERIF, 9),
                wraplength=126, justify="center",
            )
            if entry.image_url.startswith(("http://", "https://")):
                self.cover_labels.setdefault(entry.image_url, []).append(cover)
                self._request_cover(entry.image_url)
        title = tk.Label(card, text=entry.title, bg=palette.bg, fg=palette.text,
                         font=(SERIF, 10, "bold"), anchor="nw", justify="left",
                         wraplength=160)
        title.place(x=5, y=218, width=160, height=38)
        author = tk.Label(card, text=entry.author or "Автор неизвестен",
                          bg=palette.bg, fg=palette.muted, font=(UI, 8), anchor="nw",
                          wraplength=160)
        author.place(x=5, y=258, width=160, height=16)
        formats = sorted(fmt for fmt in entry.acquisitions if fmt in opds.READABLE)
        if entry.source == "wikisource":
            formats = ["fb2"]
        elif not formats and entry.acquisitions:
            formats = ["—"]
        meta = " · ".join(fmt.upper() for fmt in formats) if formats else "Нет файла"
        info = tk.Label(card, text=meta, bg=palette.bg, fg=palette.dim,
                        font=(UI, 7), anchor="w")
        info.place(x=5, y=278, width=160, height=14)
        widgets = [card, cover, title, author, info]
        for widget in widgets:
            widget.bind("<Button-1>", lambda _e, e=entry: self._open_entry(e))
            widget.bind("<Enter>", lambda _e, c=card: self._hover_card(c, True))
            widget.bind("<Leave>", lambda _e, c=card: self._hover_card(c, False))
        card._widgets = widgets  # type: ignore[attr-defined]
        return card

    def _hover_card(self, card: tk.Frame, hover: bool) -> None:
        # Лёгкая подсветка рамки обложки, без перерисовки всей карточки.
        for child in card.winfo_children():
            if isinstance(child, tk.Label) and child.cget("highlightthickness"):
                child.configure(
                    highlightbackground=self.palette.accent if hover else self.palette.border
                )
                break

    def _cover_photo(self, entry: opds.CatalogEntry):
        if not entry.image_url.startswith(("http://", "https://")):
            return None
        path = opds.cover_path(entry.image_url)
        if path.exists():
            return self.cover_cache.get(path, (150, 210), radius=5)
        return None

    def _request_cover(self, url: str) -> None:
        if url in self.cover_jobs:
            return
        self.cover_jobs.add(url)

        def worker() -> None:
            try:
                path = opds.cache_cover(url)
                self.queue.put(("cover", url, path))
            except Exception:
                pass

        self.executor.submit(worker)

    def _layout_cards(self) -> None:
        if not self.cards or self.cards_parent is None:
            return
        width = max(300, self.scroll.canvas.winfo_width() - 44)
        columns = max(1, min(5, (width + 12) // (CARD_W + 12)))
        for index, card in enumerate(self.cards):
            card.grid(row=index // columns, column=index % columns,
                      padx=6, pady=8, sticky="n")
        for column in range(5):
            self.cards_parent.grid_columnconfigure(
                column, weight=1 if column < columns else 0
            )

    def _on_canvas_resize(self, _event=None) -> None:
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(120, self._layout_cards)

    # ------------------------------------------------------------- записи
    def _open_entry(self, entry: opds.CatalogEntry) -> None:
        if entry.nav_url:
            if entry.nav_url.startswith("ws-search:"):
                query = urllib.parse.unquote(entry.nav_url.split(":", 1)[1])
                self._load_wikisource_search(query, push=True)
            elif entry.nav_url == "ws-random":
                self._load_wikisource_random(push=True)
            else:
                self._load_opds(entry.nav_url, entry.title, push=True)
            return
        self._open_details(entry)

    def _open_details(self, entry: opds.CatalogEntry) -> None:
        if self.detail_dialog is not None:
            try:
                self.detail_dialog.destroy()
            except tk.TclError:
                pass
        palette = self.palette
        dialog = tk.Toplevel(self)
        self.detail_dialog = dialog
        dialog.title(entry.title)
        dialog.configure(bg=palette.panel)
        dialog.transient(self)
        dialog.geometry("620x560")
        dialog.minsize(560, 480)
        body = tk.Frame(dialog, bg=palette.panel)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        top = tk.Frame(body, bg=palette.panel)
        top.pack(fill="x")
        cover = tk.Label(top, bg=palette.card, bd=0)
        cover.pack(side="left", padx=(0, 16))
        photo = self._cover_photo(entry)
        if photo:
            cover.configure(image=photo)
            cover._photo = photo  # type: ignore[attr-defined]
        else:
            cover.configure(text=entry.title[:40], fg=palette.muted, font=(SERIF, 9),
                            wraplength=130, justify="center", width=18, height=10,
                            anchor="center")
            if entry.image_url.startswith(("http://", "https://")):
                self.cover_labels.setdefault(entry.image_url, []).append(cover)
                self._request_cover(entry.image_url)
        info = tk.Frame(top, bg=palette.panel)
        info.pack(side="left", fill="both", expand=True)
        tk.Label(info, text=entry.title, bg=palette.panel, fg=palette.text,
                 font=(SERIF, 16, "bold"), wraplength=380, justify="left",
                 anchor="w").pack(fill="x")
        tk.Label(info, text=entry.author or "Автор неизвестен", bg=palette.panel,
                 fg=palette.accent, font=(UI, 9), anchor="w").pack(fill="x", pady=(4, 8))
        source = "Викитека" if entry.source == "wikisource" else "OPDS"
        tk.Label(info, text=source, bg=palette.panel, fg=palette.dim,
                 font=(UI, 7), anchor="w").pack(fill="x")

        summary = entry.summary or "Описание не указано."
        text = tk.Text(body, height=7, bg=palette.card, fg=palette.muted,
                       font=(UI, 9), relief="flat", wrap="word", bd=0,
                       highlightthickness=0, padx=10, pady=8, spacing3=4)
        text.insert("1.0", summary)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=(16, 6))

        self.download_status = tk.Label(body, text="", bg=palette.panel,
                                        fg=palette.muted, font=(UI, 8), anchor="w")
        self.download_status.pack(fill="x")
        actions = tk.Frame(body, bg=palette.panel)
        actions.pack(fill="x", pady=(8, 0))

        if entry.source == "wikisource":
            PillButton(actions, palette, "Скачать FB2", lambda: self._start_download(entry, "fb2"),
                       icon="plus", kind="primary", height=38, bg=palette.panel).pack(fill="x")
        else:
            formats = [fmt for fmt in opds.PREFERENCE if fmt in entry.acquisitions]
            if not formats:
                tk.Label(actions, text="В этой записи нет EPUB/PDF/FB2/TXT.",
                         bg=palette.panel, fg=palette.danger, font=(UI, 8)).pack(fill="x")
            for fmt in formats:
                PillButton(actions, palette, f"Скачать {fmt.upper()}",
                           lambda f=fmt: self._start_download(entry, f),
                           icon="plus", kind="primary", height=38,
                           bg=palette.panel).pack(fill="x", pady=2)
            if entry.nav_url:
                PillButton(actions, palette, "Открыть раздел",
                           lambda: self._open_from_dialog(entry),
                           kind="soft", height=32, bg=palette.panel).pack(fill="x", pady=(6, 0))
        IconButton(body, palette, "close", dialog.destroy, size=28,
                   bg=palette.panel, tooltip="Закрыть").place(relx=1.0, x=-8, y=0, anchor="ne")
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def _open_from_dialog(self, entry: opds.CatalogEntry) -> None:
        if self.detail_dialog is not None:
            self.detail_dialog.destroy()
            self.detail_dialog = None
        self._open_entry(entry)

    # ------------------------------------------------------------- скачивание
    def _start_download(self, entry: opds.CatalogEntry, fmt: str) -> None:
        self.download_seq += 1
        token = self.download_seq
        self.status_label.configure(text=f"Скачивание «{entry.title}»…")
        if hasattr(self, "download_status") and self.download_status.winfo_exists():
            self.download_status.configure(text="Скачивание…")
        source_folder = opds.safe_filename(self.source_name or "Каталог", "")
        folder = BOOKS_DIR / "Каталоги" / source_folder

        def worker() -> None:
            try:
                if entry.source == "wikisource":
                    title = entry.extra.get("ws_title") or entry.title
                    path = wikisource.download(title, folder)
                else:
                    url = entry.acquisitions.get(fmt)
                    if not url:
                        raise opds.OPDSFeedError("Нет ссылки на файл")
                    extension = opds.EXTENSIONS.get(fmt, ".bin")
                    target = opds.unique_path(
                        folder, opds.safe_filename(entry.title, extension)
                    )
                    path = opds.download(
                        url, target,
                        progress=lambda done, total: self.queue.put(
                            ("progress", token, done, total)
                        ),
                    )
                meta = parse_meta(path)
                meta["cover"] = ensure_cover(
                    path,
                    title=meta.get("title") or entry.title,
                    author=meta.get("author") or entry.author,
                    genre=meta.get("genre", ""),
                    stored=meta.get("cover", ""),
                )
                book_id, _ = self.db.upsert(meta)
                self.queue.put(("downloaded", token, path, meta.get("title") or entry.title, book_id))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("download_error", token, str(exc)))

        self.executor.submit(worker)

    # ------------------------------------------------------------- очередь
    def _poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                event = self.queue.get_nowait()
                kind = event[0]
                if kind == "page":
                    req, page = event[1], event[2]
                    if req != self.req:
                        continue
                    self._render_page(page)
                elif kind == "error":
                    req, message = event[1], event[2]
                    if req != self.req:
                        continue
                    self._show_error(message)
                elif kind == "cover":
                    url, path = event[1], event[2]
                    self._apply_cover(url, path)
                elif kind == "progress":
                    token, done, total = event[1], event[2], event[3]
                    if total:
                        percent = min(100, int(done * 100 / total))
                        self.status_label.configure(
                            text=f"Скачивание… {percent}%  ({done / 1048576:.1f} МБ)"
                        )
                    else:
                        self.status_label.configure(
                            text=f"Скачивание… {done / 1048576:.1f} МБ"
                        )
                elif kind == "downloaded":
                    token, path, title, book_id = event[1], event[2], event[3], event[4]
                    self.status_label.configure(text=f"Добавлено в библиотеку: {title}")
                    if self.detail_dialog is not None:
                        try:
                            self.detail_dialog.destroy()
                        except tk.TclError:
                            pass
                        self.detail_dialog = None
                    if BOOKS_DIR not in [Path(folder) for folder in self.settings.folders]:
                        self.settings.folders.append(str(BOOKS_DIR))
                        self.settings.save()
                    if self.on_imported:
                        self.on_imported()
                elif kind == "download_error":
                    message = event[2]
                    self.status_label.configure(text=f"Ошибка скачивания: {message}")
                    if hasattr(self, "download_status") and self.download_status.winfo_exists():
                        self.download_status.configure(text=f"Ошибка: {message}")
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll)

    def _apply_cover(self, url: str, path: Path) -> None:
        labels = self.cover_labels.get(url, [])
        photo = self.cover_cache.get(path, (150, 210), radius=5)
        if photo is None:
            return
        for label in labels:
            try:
                if label.winfo_exists():
                    label.configure(image=photo, text="")
                    label._photo = photo  # type: ignore[attr-defined]
            except tk.TclError:
                pass

    # ------------------------------------------------------------- закрытие
    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
