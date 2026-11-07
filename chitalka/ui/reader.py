"""Окно чтения: постраничная вёрстка, оглавление, закладки, поиск, темы."""

from __future__ import annotations

import bisect
import json
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ..config import APP_ICON, APP_NAME, Settings, fit_geometry
from ..db import LibraryDB
from ..formats import load_document
from ..formats.model import Block, Document, clean_text
from ..formats.pdf import PdfBook
from ..layout import LayoutResult, LayoutStyle, layout_document
from ..theme import Palette, READING_THEMES, ReadingTheme, reading_theme
from ..winutil import is_foreground
from .icons import draw_icon
from .lookup import LookupWindow
from .notes import (
    NOTE_COLOR_LABELS,
    ColorPopup,
    NoteDialog,
    SelectionToolbar,
    note_color,
)
from .widgets import (
    IconButton,
    PillButton,
    ProgressBar,
    ScrollFrame,
    SearchEntry,
    Slider,
    ask_text,
    round_rect,
)

UI = "Segoe UI"
SERIF = "Georgia"

FONT_CHOICES = [
    "Georgia",
    "Palatino Linotype",
    "Cambria",
    "Constantia",
    "Times New Roman",
    "Segoe UI",
]


def ellipsis(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


class ReaderWindow(tk.Toplevel):
    def __init__(
        self,
        master,
        row,
        settings: Settings,
        db: LibraryDB,
        palette: Palette,
        cover_cache=None,
        on_close=None,
        start_page: int | None = None,
        start_block: int | None = None,
    ) -> None:
        super().__init__(master)
        self.row = row
        self.book_id = int(row["id"])
        self.path = Path(row["path"])
        self.settings = settings
        self.db = db
        self.palette = palette
        self.on_close_cb = on_close
        self._start_page = start_page
        self._start_block = start_block
        self.doc: Document | None = None
        self.pdf: PdfBook | None = None
        self.is_pdf = False
        self.result: LayoutResult | None = None
        self.pages = []
        self.page_index = 0
        self.page_count = 0
        self.history: list[int] = []
        self.panel: tk.Frame | None = None
        self.panel_name = ""
        self.fullscreen = False
        self._ready = False
        self._closing = False
        self._layout_job = None
        self._resize_job = None
        self._save_job = None
        self._settings_job = None
        self._search_job = None
        self._initial_block = 0
        self._page_geom: dict = {}
        self._photos: dict[tuple, ImageTk.PhotoImage] = {}
        self._pdf_photos: dict[tuple, ImageTk.PhotoImage] = {}
        self._panel_buttons: dict[str, IconButton] = {}
        self._swatches: dict[str, tk.Canvas] = {}
        self.session_id: int | None = None
        self._session_seconds = 0
        self._session_pages = 0
        self._last_tick = time.monotonic()
        self._last_activity = time.monotonic()
        self.annotations: list = []
        self.selection: dict | None = None
        self._sel_anchor: tuple[int, int] | None = None
        self._pdf_anchor: int | None = None
        self._pdf_geom: dict = {}
        self._press_xy: tuple[int, int] | None = None
        self._selection_dragged = False
        self._selection_toolbar: SelectionToolbar | None = None
        self._lookup_window: LookupWindow | None = None

        self.title(f"{row['title']} — {APP_NAME}")
        self.configure(bg=palette.bg)
        self.minsize(820, 560)
        try:
            if APP_ICON.exists():
                self.iconbitmap(default=str(APP_ICON))
        except tk.TclError:
            pass
        try:
            fit_geometry(self, settings.reader_geometry, 820, 560)
        except tk.TclError:
            self.geometry("1140x850")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", self._on_escape)
        self.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.bind("<Control-f>", lambda _e: self._open_panel("search"))
        self.bind("<Control-t>", lambda _e: self._open_panel("toc"))
        self.bind("<Control-b>", lambda _e: self._open_panel("bookmarks"))
        self.bind("<Alt-Left>", lambda _e: self._back_history())
        self.bind("<Control-c>", lambda _e: self._copy_page())
        for sequence in ("<Motion>", "<Key>", "<Button-1>"):
            self.bind(sequence, self._touch_activity, add="+")
        self.after(60, self._load)
        self.after(220, self._activate)

    def _activate(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.canvas.focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        palette = self.palette
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.topbar = tk.Frame(self, bg=palette.panel)
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.configure(height=58)
        tk.Frame(self.topbar, bg=palette.border, height=1).pack(side="bottom", fill="x")

        IconButton(self.topbar, palette, "arrow_left", self.close, size=38,
                   tooltip="К библиотеке").pack(side="left", padx=(14, 6), pady=10)
        titles = tk.Frame(self.topbar, bg=palette.panel)
        titles.pack(side="left", fill="both", expand=True, pady=8)
        self.book_label = tk.Label(titles, text=ellipsis(self.row["title"], 62),
                                   bg=palette.panel, fg=palette.text,
                                   font=(SERIF, 11, "bold"), anchor="w")
        self.book_label.pack(fill="x")
        self.chapter_label = tk.Label(titles, text="", bg=palette.panel, fg=palette.muted,
                                      font=(UI, 8), anchor="w")
        self.chapter_label.pack(fill="x")

        right = tk.Frame(self.topbar, bg=palette.panel)
        right.pack(side="right", padx=(0, 10), pady=10)
        for name, icon, tip, command in (
            ("fullscreen", "fullscreen", "Во весь экран (F11)", self.toggle_fullscreen),
            ("settings", "type", "Оформление текста", lambda: self._open_panel("settings")),
            ("search", "search", "Поиск по книге (Ctrl+F)", lambda: self._open_panel("search")),
            ("notes", "note", "Заметки и выделения", lambda: self._open_panel("notes")),
            ("bookmarks", "bookmark", "Закладки (Ctrl+B)", lambda: self._open_panel("bookmarks")),
            ("toc", "toc", "Содержание (Ctrl+T)", lambda: self._open_panel("toc")),
        ):
            button = IconButton(right, palette, icon, command, size=36, tooltip=tip)
            button.pack(side="right", padx=1)
            self._panel_buttons[name] = button

        self.content = tk.Frame(self, bg=reading_theme(self.settings.reader_theme).desk)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.content, bg=reading_theme(self.settings.reader_theme).desk,
                                highlightthickness=0, bd=0, cursor="arrow")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.loading = tk.Label(self.content, text="Открываем книгу…",
                                bg=reading_theme(self.settings.reader_theme).desk,
                                fg=reading_theme(self.settings.reader_theme).muted,
                                font=(SERIF, 12))
        self.loading.place(relx=0.5, rely=0.5, anchor="center")
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_selection_press)
        self.canvas.bind("<B1-Motion>", self._on_selection_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_selection_release)
        self.canvas.bind("<Button-3>", self._context_menu)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.prev_page())
        self.canvas.bind("<Button-5>", lambda e: self.next_page())
        self.canvas.bind("<Left>", lambda e: self.prev_page())
        self.canvas.bind("<Right>", lambda e: self.next_page())
        self.canvas.bind("<Prior>", lambda e: self.prev_page())
        self.canvas.bind("<Next>", lambda e: self.next_page())
        self.canvas.bind("<space>", lambda e: self.next_page())
        self.canvas.bind("<Shift-space>", lambda e: self.prev_page())
        self.canvas.bind("<Home>", lambda e: self.go_to_page(0))
        self.canvas.bind("<End>", lambda e: self.go_to_page(self._total_pages() - 1))
        self.canvas.bind("<BackSpace>", lambda e: self._back_history())
        self.canvas.focus_set()

        self.bottombar = tk.Frame(self, bg=palette.panel, height=50)
        self.bottombar.grid(row=2, column=0, sticky="ew")
        self.bottombar.grid_propagate(False)
        tk.Frame(self.bottombar, bg=palette.border, height=1).pack(side="top", fill="x")
        IconButton(self.bottombar, palette, "chevron_left", self.prev_page, size=34,
                   tooltip="Предыдущая страница").pack(side="left", padx=(14, 2), pady=8)
        IconButton(self.bottombar, palette, "chevron_right", self.next_page, size=34,
                   tooltip="Следующая страница").pack(side="left", pady=8)
        self.percent_label = tk.Label(self.bottombar, text="0%", bg=palette.panel,
                                      fg=palette.muted, font=(UI, 8), width=5, anchor="e")
        self.percent_label.pack(side="right", padx=(4, 18))
        self.page_label = tk.Label(self.bottombar, text="", bg=palette.panel,
                                   fg=palette.text, font=(UI, 9, "bold"), width=13, anchor="e")
        self.page_label.pack(side="right", padx=(8, 6))
        self.slider = Slider(self.bottombar, palette, minimum=0, maximum=100,
                            value=0, step=1, command=self._on_slider,
                            width=300, height=22, bg=palette.panel)
        self.slider.pack(side="left", fill="x", expand=True, padx=12)

    # ------------------------------------------------------------------ загрузка
    def _load(self) -> None:
        if self._closing:
            return
        try:
            self.configure(cursor="watch")
            self.update_idletasks()
            doc = load_document(self.path)
            self.doc = doc
            try:
                self.annotations = self.db.annotations(self.book_id)
            except Exception:
                self.annotations = []
            self.title(f"{doc.title} — {APP_NAME}")
            self.book_label.configure(text=ellipsis(doc.title, 62))
            if doc.format == "pdf":
                self.is_pdf = True
                self.pdf = PdfBook(self.path)
                self.page_count = self.pdf.page_count
                if self.page_count <= 0:
                    raise ValueError("В PDF нет страниц")
                progress = float(self.row["progress"] or 0)
                start = 0 if progress >= 99 else int(self.row["position"] or 0)
                if self._start_page is not None:
                    start = int(self._start_page)
                self.page_index = max(0, min(self.page_count - 1, start))
                self.loading.place_forget()
                self._ready = True
                self._render_pdf()
                self._update_bottom()
                self.canvas.focus_set()
            else:
                self._initial_block = int(self.row["position"] or 0)
                if float(self.row["progress"] or 0) >= 99:
                    self._initial_block = 0
                if self._start_block is not None:
                    self._initial_block = max(0, int(self._start_block))
                self.loading.configure(text="Вёрстка…")
                self.update_idletasks()
                self._layout_text(initial=True)
            self._start_session()
            self.configure(cursor="")
        except Exception as exc:  # noqa: BLE001
            self.configure(cursor="")
            self.loading.configure(text="Не удалось открыть книгу")
            messagebox.showerror("Ошибка чтения", str(exc), parent=self)
            self.after(200, self.close)

    def _chapter_for_page(self) -> str:
        return self._chapter_at_page(self.page_index)

    def _chapter_at_page(self, page_index: int) -> str:
        if not self.doc:
            return ""
        if self.is_pdf:
            title = ""
            for chapter in self.doc.chapters:
                if chapter.position <= page_index:
                    title = chapter.title
                else:
                    break
            return title or f"Страница {page_index + 1}"
        if self.pages and page_index < len(self.pages):
            return self.pages[page_index].chapter or self.doc.title
        return self.doc.title

    # ------------------------------------------------------------------ вёрстка
    def _text_geometry(self) -> dict:
        cw = max(360, self.canvas.winfo_width())
        ch = max(360, self.canvas.winfo_height())
        panel_w = 350 if self.panel is not None else 0
        avail = max(340, cw - panel_w)
        margin = self.settings.page_margin
        header_h = 24 if self.settings.show_header else 0
        footer_h = 24 if self.settings.show_footer else 0
        page_h = max(320, ch - 34)
        page_w = min(max(340, avail - 48), 780)
        if page_w > avail - 20:
            page_w = avail - 20
        margin = min(margin, max(24, int(page_w * 0.14)))
        text_w = max(180, page_w - 2 * margin)
        text_h = max(160, page_h - 2 * margin - header_h - footer_h)
        px = (avail - page_w) / 2
        py = (ch - page_h) / 2
        return {
            "page_x": px, "page_y": py, "page_w": page_w, "page_h": page_h,
            "margin": margin, "header_h": header_h, "footer_h": footer_h,
            "text_x": px + margin, "text_y": py + margin + header_h,
            "text_w": text_w, "text_h": text_h,
        }

    def _layout_text(self, initial: bool = False) -> None:
        if self._closing or self.is_pdf or not self.doc:
            return
        if self._layout_job:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
            self._layout_job = None
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 200 or height < 200:
            self.after(80, lambda: self._layout_text(initial))
            return
        block = self._initial_block if initial else self._current_block()
        geom = self._text_geometry()
        self._page_geom = geom
        style = LayoutStyle(
            family=self.settings.font_family,
            size=max(11, min(34, int(self.settings.font_size))),
            line_spacing=max(1.1, min(2.2, float(self.settings.line_spacing))),
            justify=bool(self.settings.justify),
            width=int(geom["text_w"]),
            height=int(geom["text_h"]),
            chapter_page_break=bool(self.settings.chapter_page_break),
            header=bool(self.settings.show_header),
            footer=bool(self.settings.show_footer),
        )
        self.loading.configure(text="Вёрстка…")
        self.loading.place(relx=0.5, rely=0.5, anchor="center")
        self.update_idletasks()
        started = time.time()
        try:
            result = layout_document(self.doc, style, self)
        except Exception as exc:  # noqa: BLE001
            self.loading.configure(text="Ошибка вёрстки")
            messagebox.showerror("Ошибка вёрстки", str(exc), parent=self)
            return
        self.result = result
        self.pages = result.pages
        self.page_count = len(self.pages)
        index = result.page_for_block(block)
        self.page_index = max(0, min(index, self.page_count - 1))
        self._ready = True
        self.loading.place_forget()
        self._render_text()
        self._update_bottom()
        if initial and not self.page_index:
            self._initial_block = 0

    def _on_resize(self, _event=None) -> None:
        if not self._ready:
            return
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(220, self._after_resize)

    def _after_resize(self) -> None:
        self._resize_job = None
        if self.is_pdf:
            self._render_pdf()
        else:
            self._layout_text()

    # ------------------------------------------------------------------ отрисовка
    def _render_text(self) -> None:
        self.canvas.delete("all")
        if not self.pages or not self.result:
            return
        theme = reading_theme(self.settings.reader_theme)
        self.canvas.configure(bg=theme.desk)
        self.content.configure(bg=theme.desk)
        self.loading.configure(bg=theme.desk, fg=theme.muted)
        page = self.pages[self.page_index]
        g = self._page_geom
        if not g:
            g = self._text_geometry()
            self._page_geom = g
        px, py = g["page_x"], g["page_y"]
        pw, ph = g["page_w"], g["page_h"]
        self.canvas.create_rectangle(px + 7, py + 7, px + pw + 7, py + ph + 7,
                                     fill=theme.shadow, outline="")
        self.canvas.create_rectangle(px, py, px + pw, py + ph,
                                     fill=theme.page, outline=theme.rule, width=1)

        tx, ty = g["text_x"], g["text_y"]
        if self.settings.show_header:
            header = ellipsis(page.chapter or self.doc.title, 84)
            self.canvas.create_text(tx, py + g["margin"] * 0.48, text=header,
                                    anchor="nw", fill=theme.muted,
                                    font=(UI, 8))
        if self.settings.show_footer:
            total = self._total_pages()
            percent = (self.page_index + 1) / max(1, total) * 100
            fy = py + ph - g["margin"] * 0.52
            title = ellipsis(self.doc.title, 38)
            self.canvas.create_text(tx, fy, text=title, anchor="nw",
                                    fill=theme.muted, font=(UI, 7))
            self.canvas.create_text(tx + g["text_w"] / 2, fy,
                                    text=f"{self.page_index + 1}", anchor="n",
                                    fill=theme.muted, font=(UI, 8))
            self.canvas.create_text(tx + g["text_w"], fy,
                                    text=f"{percent:.0f}%", anchor="ne",
                                    fill=theme.muted, font=(UI, 7))

        self._draw_annotation_backgrounds(page, g, tx, ty, theme)
        self._draw_selection()

        for image in page.images:
            photo = self._photo_for(image)
            if photo is not None:
                self.canvas.create_image(tx + image.x, ty + image.y,
                                         anchor="nw", image=photo)
        fonts = self.result.fonts
        for line in page.lines:
            for segment in line.segments:
                sy = ty + line.y + segment.dy
                color = theme.accent if segment.link else theme.text
                tags = ("text",)
                if segment.link:
                    tag = f"link:{segment.link}"
                    tags = ("text", tag)
                    self.canvas.tag_bind(tag, "<Button-1>",
                                         lambda _e, link=segment.link: self._follow_link(link))
                    self.canvas.tag_bind(tag, "<Enter>",
                                         lambda _e: self.canvas.configure(cursor="hand2"))
                    self.canvas.tag_bind(tag, "<Leave>",
                                         lambda _e: self.canvas.configure(cursor="arrow"))
                self.canvas.create_text(
                    tx + segment.x, sy, text=segment.text,
                    font=fonts.font(segment.key), fill=color, anchor="nw", tags=tags,
                )
                ascent = fonts.metrics(segment.key)[1]
                if segment.underline or segment.link:
                    self.canvas.create_line(
                        tx + segment.x, sy + ascent + 1,
                        tx + segment.x + segment.width, sy + ascent + 1,
                        fill=color, width=1,
                    )
                if segment.strike:
                    self.canvas.create_line(
                        tx + segment.x, sy + ascent * 0.55,
                        tx + segment.x + segment.width, sy + ascent * 0.55,
                        fill=color, width=1,
                    )
        for rule in page.rules:
            x1 = tx + (g["text_w"] - rule.width) / 2
            self.canvas.create_line(x1, ty + rule.y, x1 + rule.width, ty + rule.y,
                                    fill=theme.rule, width=rule.thickness)
        self._draw_annotation_markers(page, g, tx, ty, theme)

    def _photo_for(self, image) -> ImageTk.PhotoImage | None:
        key = (image.path, int(image.width), int(image.height))
        photo = self._photos.get(key)
        if photo is not None:
            return photo
        try:
            pil = Image.open(image.path).convert("RGB")
            pil = pil.resize((max(1, image.width), max(1, image.height)), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil)
        except Exception:
            return None
        if len(self._photos) > 30:
            self._photos.pop(next(iter(self._photos)))
        self._photos[key] = photo
        return photo

    def _render_pdf(self) -> None:
        if not self.pdf:
            return
        self.canvas.delete("all")
        theme = reading_theme(self.settings.reader_theme)
        self.canvas.configure(bg=theme.desk)
        self.content.configure(bg=theme.desk)
        cw = max(360, self.canvas.winfo_width())
        ch = max(360, self.canvas.winfo_height())
        panel_w = 350 if self.panel is not None else 0
        avail_w = max(320, cw - panel_w)
        try:
            page = self.pdf.doc[self.page_index]
        except Exception:
            return
        pw_pt = float(page.rect.width or 1)
        ph_pt = float(page.rect.height or 1)
        max_w = avail_w - 48
        max_h = ch - 46
        zoom = min(max_w / pw_pt, max_h / ph_pt)
        width = int(pw_pt * zoom)
        height = int(ph_pt * zoom)
        x = (avail_w - width) / 2
        y = (ch - height) / 2
        self.canvas.create_rectangle(x + 7, y + 7, x + width + 7, y + height + 7,
                                     fill=theme.shadow, outline="")
        self.canvas.create_rectangle(x, y, x + width, y + height,
                                     fill="#ffffff", outline=theme.rule, width=1)
        key = (self.page_index, int(zoom * 100))
        photo = self._pdf_photos.get(key)
        if photo is None:
            try:
                pil = self.pdf.render(self.page_index, zoom)
                if pil.size != (width, height):
                    pil = pil.resize((width, height), Image.LANCZOS)
                photo = ImageTk.PhotoImage(pil)
                if len(self._pdf_photos) > 8:
                    self._pdf_photos.pop(next(iter(self._pdf_photos)))
                self._pdf_photos[key] = photo
            except Exception:
                self.canvas.create_text(avail_w / 2, ch / 2, text="Не удалось отрисовать страницу",
                                        fill=theme.muted, font=(UI, 10))
                return
        self.canvas.create_image(x, y, anchor="nw", image=photo)
        self._pdf_geom = {
            "x": x, "y": y, "w": width, "h": height,
            "pw": pw_pt, "ph": ph_pt, "page": self.page_index,
        }
        self._draw_pdf_annotations(theme)
        self._draw_pdf_selection(theme)

    def _parse_pdf_rects(self, annotation) -> list[list[float]]:
        raw = str(annotation["rects"] or "")
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
        result = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 4:
                try:
                    result.append([float(item[0]), float(item[1]),
                                   float(item[2]), float(item[3])])
                except (TypeError, ValueError):
                    continue
        return result

    def _pdf_rect_canvas(self, rect: list[float], g: dict) -> tuple[float, float, float, float]:
        x1 = g["x"] + rect[0] * g["w"]
        y1 = g["y"] + rect[1] * g["h"]
        x2 = g["x"] + rect[2] * g["w"]
        y2 = g["y"] + rect[3] * g["h"]
        return x1, y1, x2, y2

    def _draw_pdf_annotations(self, theme) -> None:
        g = self._pdf_geom
        if not g:
            return
        for annotation in self.annotations:
            if int(annotation["page"] if annotation["page"] is not None else -1) != self.page_index:
                continue
            rects = self._parse_pdf_rects(annotation)
            if not rects:
                continue
            fill = note_color(str(annotation["color"]), theme.is_dark)
            for rect in rects:
                x1, y1, x2, y2 = self._pdf_rect_canvas(rect, g)
                self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=fill, outline="",
                    stipple="gray50", tags=("annotation",),
                )
            first = self._pdf_rect_canvas(rects[0], g)
            marker_x = max(g["x"] + 7, first[0] - 8)
            marker_y = (first[1] + first[3]) / 2
            tag = f"ann:{annotation['id']}"
            self.canvas.create_oval(
                marker_x - 4, marker_y - 4, marker_x + 4, marker_y + 4,
                fill=fill, outline=theme.rule, tags=("annotation_marker", tag),
            )
            self.canvas.tag_bind(
                tag, "<Button-1>", lambda _e: self._open_panel("notes")
            )

    def _draw_pdf_selection(self, theme) -> None:
        selection = self.selection
        g = self._pdf_geom
        if not selection or not g or selection.get("kind") != "pdf":
            return
        if int(selection.get("page", -1)) != self.page_index:
            return
        fill = "#31465a" if theme.is_dark else "#cfe2f3"
        for rect in selection.get("rects", []):
            x1, y1, x2, y2 = self._pdf_rect_canvas(rect, g)
            self.canvas.create_rectangle(
                x1, y1, x2, y2, fill=fill, outline="",
                stipple="gray50", tags=("selection",),
            )

    def _update_bottom(self) -> None:
        total = self._total_pages()
        self.page_label.configure(text=f"{self.page_index + 1} / {max(1, total)}")
        percent = (self.page_index + 1) / max(1, total) * 100
        self.percent_label.configure(text=f"{percent:.0f}%")
        self.slider.set(percent)
        chapter = self._chapter_for_page()
        self.chapter_label.configure(text=ellipsis(chapter or "", 92))
        if self.panel_name == "toc":
            self._populate_toc()

    def _total_pages(self) -> int:
        return self.page_count if self.is_pdf else len(self.pages)

    # -------------------------------------------------------------- статистика
    def _start_session(self) -> None:
        try:
            self.session_id = self.db.begin_session(self.book_id)
        except Exception:
            self.session_id = None
        self._last_tick = time.monotonic()
        self._last_activity = time.monotonic()
        self.after(30_000, self._tick_session)

    def _touch_activity(self, _event=None) -> None:
        self._last_activity = time.monotonic()

    def _current_session_seconds(self) -> int:
        now = time.monotonic()
        delta = now - self._last_tick
        self._last_tick = now
        if delta <= 0:
            return 0
        try:
            foreground = is_foreground(self)
        except Exception:
            foreground = False
        try:
            focused = self.focus_displayof() is not None
            visible = bool(self.winfo_viewable()) and self.state() != "iconic"
        except tk.TclError:
            focused = False
            visible = False
        active = (foreground or focused) and visible and (now - self._last_activity) < 300
        if active:
            self._session_seconds += int(min(delta, 60))
        return self._session_seconds

    def _tick_session(self) -> None:
        if self._closing:
            return
        self._current_session_seconds()
        self._save_session()
        self.after(30_000, self._tick_session)

    def _save_session(self) -> None:
        if not self.session_id:
            return
        try:
            self.db.update_session(self.session_id, self._session_seconds, self._session_pages)
        except Exception:
            pass

    def _finish_session(self) -> None:
        if not self.session_id:
            return
        self._current_session_seconds()
        self._save_session()
        self.session_id = None

    # ------------------------------------------------------------- выделение
    def _on_selection_press(self, event) -> None:
        self.canvas.focus_set()
        self._press_xy = (event.x, event.y)
        self._selection_dragged = False
        self._sel_anchor = None
        self._pdf_anchor = None
        if self.selection:
            self._clear_selection()
        if self.is_pdf:
            self._pdf_anchor = self._pdf_hit_word(event.x, event.y)
            if self._pdf_anchor is None and self.pdf and not self.pdf.words(self.page_index):
                self._flash("В PDF нет текстового слоя")
            return
        self._sel_anchor = self._hit_test(event.x, event.y)

    def _on_selection_motion(self, event) -> None:
        if self._press_xy is None:
            return
        dx = event.x - self._press_xy[0]
        dy = event.y - self._press_xy[1]
        if not self._selection_dragged and abs(dx) + abs(dy) < 4:
            return
        if self.is_pdf:
            if self._pdf_anchor is None:
                return
            position = self._pdf_hit_word(event.x, event.y)
            if position is None:
                return
            selection = self._make_pdf_selection(self._pdf_anchor, position)
            if selection is None:
                self._clear_selection()
                return
            self._selection_dragged = True
            self.selection = selection
            self._render_pdf()
            return
        if not self._sel_anchor:
            return
        position = self._hit_test(event.x, event.y)
        if position is None:
            return
        selection = self._make_selection(self._sel_anchor, position)
        if selection is None:
            self._clear_selection()
            return
        self._selection_dragged = True
        self.selection = selection
        self._render_text()

    def _on_selection_release(self, event) -> None:
        self._selection_point = (event.x_root, event.y_root)
        if self._selection_dragged and self.selection:
            self._show_selection_toolbar(event.x_root, event.y_root)
            self._selection_dragged = False
            self._sel_anchor = None
            self._pdf_anchor = None
            return
        self._selection_dragged = False
        self._sel_anchor = None
        self._pdf_anchor = None
        self._on_canvas_click(event)

    def _pdf_hit_word(self, x: float, y: float) -> int | None:
        if not self.is_pdf or not self.pdf or not self._pdf_geom:
            return None
        g = self._pdf_geom
        if not (g["x"] - 4 <= x <= g["x"] + g["w"] + 4
                and g["y"] - 4 <= y <= g["y"] + g["h"] + 4):
            return None
        px = (x - g["x"]) / max(1, g["w"]) * g["pw"]
        py = (y - g["y"]) / max(1, g["h"]) * g["ph"]
        words = self.pdf.words(self.page_index)
        if not words:
            return None
        best = None
        for index, word in enumerate(words):
            x0, y0, x1, y1 = word[0], word[1], word[2], word[3]
            if x0 - 2 <= px <= x1 + 2 and y0 - 2 <= py <= y1 + 2:
                return index
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            distance = (px - cx) ** 2 + (py - cy) ** 2
            if best is None or distance < best[0]:
                best = (distance, index)
        return best[1] if best is not None else None

    def _make_pdf_selection(self, start: int, end: int) -> dict | None:
        if not self.is_pdf or not self.pdf or not self._pdf_geom:
            return None
        if start > end:
            start, end = end, start
        words = self.pdf.words(self.page_index)
        if not words:
            return None
        g = self._pdf_geom
        pw = max(1.0, g["pw"])
        ph = max(1.0, g["ph"])
        parts: list[str] = []
        rects: list[list[float]] = []
        last_line = None
        for index in range(start, end + 1):
            x0, y0, x1, y1, text, block, line, _word = words[index]
            if last_line is not None and (block, line) != last_line:
                parts.append("\n")
            elif parts and parts[-1] != "\n":
                parts.append(" ")
            parts.append(text)
            last_line = (block, line)
            rects.append([
                max(0.0, min(1.0, x0 / pw)),
                max(0.0, min(1.0, y0 / ph)),
                max(0.0, min(1.0, x1 / pw)),
                max(0.0, min(1.0, y1 / ph)),
            ])
        quote = "".join(parts).strip()
        if not quote:
            return None
        return {
            "kind": "pdf",
            "page": self.page_index,
            "start_word": start,
            "end_word": end,
            "rects": rects,
            "quote": quote[:4000],
        }

    def _hit_test(self, x: float, y: float) -> tuple[int, int] | None:
        if self.is_pdf or not self.result or not self.pages:
            return None
        g = self._page_geom
        if not g:
            return None
        lx = x - g["text_x"]
        ly = y - g["text_y"]
        if lx < -4 or lx > g["text_w"] + 4 or ly < -4 or ly > g["text_h"] + 4:
            return None
        page = self.pages[self.page_index]
        if not page.lines:
            return None
        line = min(
            page.lines,
            key=lambda item: 0
            if item.y <= ly <= item.y + item.height
            else min(abs(ly - item.y), abs(ly - (item.y + item.height))),
        )
        if not line.segments:
            return None
        fonts = self.result.fonts
        nearest = None
        for segment in line.segments:
            left = segment.x
            right = segment.x + segment.width
            if left - 2 <= lx <= right + 2:
                offset = segment.start + self._char_offset(segment, lx, fonts)
                return (segment.block_index, offset)
            distance = min(abs(lx - left), abs(lx - right))
            if nearest is None or distance < nearest[0]:
                offset = segment.start if lx < left else segment.end
                nearest = (distance, segment.block_index, offset)
        if nearest is not None:
            return (nearest[1], nearest[2])
        return None

    def _char_offset(self, segment, lx: float, fonts) -> int:
        text = segment.text
        if lx <= segment.x:
            return 0
        cursor = segment.x
        for index, char in enumerate(text):
            width = fonts.width(segment.key, char)
            if lx < cursor + width / 2:
                return index
            cursor += width
        return len(text)

    def _make_selection(self, start: tuple[int, int],
                        end: tuple[int, int]) -> dict | None:
        if start == end:
            return None
        if start > end:
            start, end = end, start
        quote = self._quote_between(start[0], start[1], end[0], end[1])
        if not quote.strip():
            return None
        return {
            "start_block": start[0], "start_offset": start[1],
            "end_block": end[0], "end_offset": end[1],
            "quote": quote[:4000],
        }

    def _quote_between(self, start_block: int, start_offset: int,
                       end_block: int, end_offset: int) -> str:
        if not self.doc:
            return ""
        blocks = self.doc.blocks
        if start_block < 0 or end_block >= len(blocks):
            return ""
        if start_block == end_block:
            text = blocks[start_block].text()[start_offset:end_offset]
        else:
            parts = [blocks[start_block].text()[start_offset:]]
            for index in range(start_block + 1, end_block):
                parts.append(blocks[index].text())
            parts.append(blocks[end_block].text()[:end_offset])
            text = "\n".join(parts)
        return text.replace("\u2028", "\n").replace("\n\n", "\n").strip()

    def _segment_span(self, segment, start_block: int, start_offset: int,
                      end_block: int, end_offset: int, fonts) -> tuple[float, float] | None:
        block = segment.block_index
        if block < start_block or block > end_block:
            return None
        if start_block == end_block == block:
            left = max(start_offset, segment.start)
            right = min(end_offset, segment.end)
        elif block == start_block:
            left = max(start_offset, segment.start)
            right = segment.end
        elif block == end_block:
            left = segment.start
            right = min(end_offset, segment.end)
        else:
            left = segment.start
            right = segment.end
        if left >= right:
            return None
        local_left = max(0, min(len(segment.text), left - segment.start))
        local_right = max(0, min(len(segment.text), right - segment.start))
        if local_right <= local_left:
            return None
        x1 = fonts.width(segment.key, segment.text[:local_left])
        x2 = fonts.width(segment.key, segment.text[:local_right])
        return (x1, x2)

    def _draw_selection(self) -> None:
        self.canvas.delete("selection")
        if not self.selection or self.is_pdf or not self.result or not self.pages:
            return
        theme = reading_theme(self.settings.reader_theme)
        g = self._page_geom
        if not g:
            return
        fonts = self.result.fonts
        selection = self.selection
        page = self.pages[self.page_index]
        fill = "#31465a" if theme.is_dark else "#cfe2f3"
        for line in page.lines:
            for segment in line.segments:
                span = self._segment_span(
                    segment, selection["start_block"], selection["start_offset"],
                    selection["end_block"], selection["end_offset"], fonts,
                )
                if span is None:
                    continue
                x1, x2 = span
                self.canvas.create_rectangle(
                    g["text_x"] + segment.x + x1, g["text_y"] + line.y + 2,
                    g["text_x"] + segment.x + x2, g["text_y"] + line.y + line.height - 1,
                    fill=fill, outline="", tags=("selection",),
                )

    def _show_selection_toolbar(self, x_root: int, y_root: int) -> None:
        if self._selection_toolbar is not None:
            try:
                self._selection_toolbar.destroy()
            except tk.TclError:
                pass
        self._selection_toolbar = SelectionToolbar(
            self, self.palette, self._selection_action
        )
        self._selection_toolbar.show_at(x_root, y_root)

    def _hide_selection_toolbar(self) -> None:
        if self._selection_toolbar is not None:
            try:
                self._selection_toolbar.destroy()
            except tk.TclError:
                pass
            self._selection_toolbar = None

    def _clear_selection(self) -> None:
        self.selection = None
        try:
            self.canvas.delete("selection")
        except tk.TclError:
            pass
        self._hide_selection_toolbar()
        if self.is_pdf and self._ready and self.pdf:
            self._render_pdf()

    def _selection_action(self, action: str) -> None:
        if not self.selection:
            return
        if action in ("dict", "translate"):
            self._open_lookup(action)
        elif action == "highlight":
            self._quick_highlight()
        elif action == "note":
            self._note_from_selection()
        elif action == "copy":
            self._copy_selection()
        self._hide_selection_toolbar()

    def _open_lookup(self, mode: str) -> None:
        if not self.selection:
            self._flash("Сначала выделите текст")
            return
        if self._lookup_window is not None:
            try:
                if self._lookup_window.winfo_exists():
                    self._lookup_window.lift()
                    return
            except tk.TclError:
                self._lookup_window = None
        self._lookup_window = LookupWindow(
            self, self.palette, self.selection["quote"], mode=mode,
            on_close=lambda: setattr(self, "_lookup_window", None),
            cache=self.db,
        )

    def _quick_highlight(self) -> None:
        if not self.selection:
            return
        x, y = getattr(self, "_selection_point", (self.winfo_rootx() + 100,
                                                  self.winfo_rooty() + 100))
        popup = ColorPopup(self, self.palette, x, y)
        self.wait_window(popup)
        if popup.result:
            self._add_annotation(popup.result, "")

    def _note_from_selection(self) -> None:
        if not self.selection:
            return
        dialog = NoteDialog(self, self.palette, self.selection["quote"])
        self.wait_window(dialog)
        if dialog.result:
            color, comment = dialog.result
            self._add_annotation(color, comment)

    def _add_annotation(self, color: str, comment: str) -> None:
        if not self.selection:
            return
        selection = self.selection
        try:
            if selection.get("kind") == "pdf":
                self.db.add_annotation(
                    self.book_id, color, -1, 0, -1, 0, selection["quote"], comment,
                    page=int(selection.get("page", -1)),
                    rects=json.dumps(selection.get("rects", []), ensure_ascii=False),
                    kind="pdf",
                )
            else:
                self.db.add_annotation(
                    self.book_id, color, selection["start_block"], selection["start_offset"],
                    selection["end_block"], selection["end_offset"], selection["quote"], comment,
                    page=self.page_index, kind="text",
                )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Заметка", str(exc), parent=self)
            return
        self._reload_annotations()
        self._clear_selection()
        self._flash("Заметка добавлена")

    def _edit_annotation(self, annotation) -> None:
        dialog = NoteDialog(
            self, self.palette, annotation["quote"],
            color=annotation["color"], comment=annotation["comment"],
            title="Редактировать заметку",
        )
        self.wait_window(dialog)
        if dialog.result:
            color, comment = dialog.result
            self.db.update_annotation(int(annotation["id"]), color, comment)
            self._reload_annotations()

    def _delete_annotation(self, annotation) -> None:
        if not messagebox.askyesno(
            "Удалить заметку", "Удалить эту заметку вместе с выделением?", parent=self
        ):
            return
        self.db.delete_annotation(int(annotation["id"]))
        self._reload_annotations()

    def _reload_annotations(self) -> None:
        try:
            self.annotations = self.db.annotations(self.book_id)
        except Exception:
            self.annotations = []
        if self.is_pdf:
            self._render_pdf()
        elif self.pages:
            self._render_text()
        if self.panel_name == "notes":
            self._populate_notes()
        self._save_session()

    def _draw_annotation_backgrounds(self, page, g, tx, ty, theme) -> None:
        if not self.annotations or not self.result:
            return
        fonts = self.result.fonts
        for annotation in self.annotations:
            color = note_color(str(annotation["color"]), theme.is_dark)
            for line in page.lines:
                for segment in line.segments:
                    span = self._segment_span(
                        segment, int(annotation["start_block"]),
                        int(annotation["start_offset"]),
                        int(annotation["end_block"]),
                        int(annotation["end_offset"]), fonts,
                    )
                    if span is None:
                        continue
                    x1, x2 = span
                    self.canvas.create_rectangle(
                        tx + segment.x + x1, ty + line.y + 2,
                        tx + segment.x + x2, ty + line.y + line.height - 1,
                        fill=color, outline="", tags=("annotation",),
                    )

    def _draw_annotation_markers(self, page, g, tx, ty, theme) -> None:
        if not self.annotations or not self.result:
            return
        fonts = self.result.fonts
        for annotation in self.annotations:
            block = int(annotation["start_block"])
            offset = int(annotation["start_offset"])
            for line in page.lines:
                for segment in line.segments:
                    if segment.block_index != block:
                        continue
                    if not (segment.start <= offset <= segment.end):
                        continue
                    fill = note_color(str(annotation["color"]), theme.is_dark)
                    local = max(0, min(len(segment.text), offset - segment.start))
                    marker_x = tx + segment.x + fonts.width(segment.key, segment.text[:local])
                    marker_y = ty + line.y + line.height / 2
                    tag = f"ann:{annotation['id']}"
                    self.canvas.create_oval(
                        marker_x - 10, marker_y - 4, marker_x - 2, marker_y + 4,
                        fill=fill, outline=theme.rule, tags=("annotation_marker", tag),
                    )
                    self.canvas.tag_bind(
                        tag, "<Button-1>",
                        lambda _e: self._open_panel("notes"),
                    )
                    break
                else:
                    continue
                break

    def _copy_selection(self) -> None:
        if not self.selection:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self.selection["quote"])
            self._flash("Выделенный текст скопирован")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ навигация
    def _on_slider(self, value: float) -> None:
        total = self._total_pages()
        if total <= 0:
            return
        index = int(round((value / 100.0) * total))
        index = max(0, min(total - 1, index))
        self.go_to_page(index)

    def go_to_page(self, index: int, *, add_history: bool = False) -> None:
        total = self._total_pages()
        if total <= 0:
            return
        index = max(0, min(total - 1, int(index)))
        if add_history and index != self.page_index:
            self.history.append(self.page_index)
            if len(self.history) > 50:
                self.history.pop(0)
        if index == self.page_index and self._ready:
            return
        self._clear_selection()
        changed = index != self.page_index
        self.page_index = index
        if changed:
            self._session_pages += 1
            self._touch_activity()
        if self.is_pdf:
            self._render_pdf()
        else:
            self._render_text()
        self._update_bottom()
        self._schedule_save()
        self.canvas.focus_set()

    def next_page(self) -> None:
        if self.page_index + 1 >= self._total_pages():
            self._flash("Конец книги")
            return
        self.go_to_page(self.page_index + 1)

    def prev_page(self) -> None:
        if self.page_index <= 0:
            self._flash("Начало книги")
            return
        self.go_to_page(self.page_index - 1)

    def _back_history(self) -> None:
        if not self.history:
            return
        page = self.history.pop()
        self.go_to_page(page)

    def _on_wheel(self, event) -> None:
        if self.panel:
            return
        if getattr(event, "delta", 0) > 0:
            self.prev_page()
        elif getattr(event, "delta", 0) < 0:
            self.next_page()

    def _on_canvas_click(self, event) -> None:
        self.canvas.focus_set()
        if not self._ready:
            return
        current = self.canvas.find_withtag("current")
        if current:
            tags = self.canvas.gettags(current[0])
            if any(tag.startswith("link:") for tag in tags):
                return
            if "annotation_marker" in tags:
                return
        width = max(1, self.canvas.winfo_width())
        if event.x < width * 0.24:
            self.prev_page()
        elif event.x > width * 0.76:
            self.next_page()

    def _on_escape(self, _event=None) -> None:
        if self.selection:
            self._clear_selection()
            return
        if self.fullscreen:
            self.toggle_fullscreen()
        elif self.panel:
            self._close_panel()
        else:
            self.close()

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        try:
            self.attributes("-fullscreen", self.fullscreen)
        except tk.TclError:
            return
        if self.fullscreen:
            self.topbar.grid_remove()
            self.bottombar.grid_remove()
        else:
            self.topbar.grid()
            self.bottombar.grid()
        self.after(220, self._after_resize)

    def _flash(self, text: str) -> None:
        previous = self.chapter_label.cget("text")
        self.chapter_label.configure(text=text)
        self.after(1600, lambda: self.chapter_label.configure(text=previous)
                   if self.winfo_exists() else None)

    # ------------------------------------------------------------------ сохранение
    def _current_block(self) -> int:
        if self.is_pdf:
            return self.page_index
        if self.result and self.page_index < len(self.result.page_first_blocks):
            return self.result.page_first_blocks[self.page_index]
        return 0

    def _schedule_save(self) -> None:
        if self._save_job:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.after(500, self._save_progress)

    def _save_progress(self) -> None:
        self._save_job = None
        if not self._ready:
            return
        total = self._total_pages()
        if total <= 0:
            return
        progress = (self.page_index + 1) / total * 100
        chapter = self._chapter_for_page()
        try:
            self.db.update_progress(self.book_id, progress, self._current_block(), 0, chapter)
        except Exception:
            pass

    def _save_settings_soon(self) -> None:
        if self._settings_job:
            try:
                self.after_cancel(self._settings_job)
            except tk.TclError:
                pass
        self._settings_job = self.after(420, self.settings.save)

    # ------------------------------------------------------------------ ссылки
    def _follow_link(self, link: str) -> None:
        if link.startswith("note:"):
            note_id = link[5:]
            if self.doc and note_id in self.doc.notes:
                self._show_note(note_id)
            else:
                self._jump_anchor(note_id)
        elif link.startswith("anchor:"):
            anchor = link[7:]
            if self.doc and anchor in self.doc.notes:
                self._show_note(anchor)
            else:
                self._jump_anchor(anchor)
        elif link.startswith("url:"):
            try:
                webbrowser.open(link[4:])
            except Exception:
                pass
        elif link.startswith("ref:"):
            ref = link[4:]
            if "#" in ref:
                self._jump_anchor(ref.split("#", 1)[1])

    def _jump_anchor(self, anchor: str) -> None:
        if not self.doc or not self.result or self.is_pdf:
            return
        block = self.doc.anchors.get(anchor)
        if block is None:
            self._flash("Ссылка не найдена")
            return
        page = self.result.page_for_block(block)
        if page != self.page_index:
            self.history.append(self.page_index)
        self.go_to_page(page)

    def _show_note(self, note_id: str) -> None:
        if not self.doc:
            return
        blocks = self.doc.notes.get(note_id)
        if not blocks:
            self._flash("Примечание не найдено")
            return
        palette = self.palette
        dialog = tk.Toplevel(self)
        dialog.title("Примечание")
        dialog.configure(bg=palette.panel)
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.geometry("480x320")
        header = tk.Frame(dialog, bg=palette.panel)
        header.pack(fill="x", padx=18, pady=(14, 6))
        tk.Label(header, text="Примечание", bg=palette.panel, fg=palette.muted,
                 font=(UI, 8, "bold")).pack(side="left")
        IconButton(header, palette, "close", dialog.destroy, size=28,
                   bg=palette.panel, tooltip="Закрыть").pack(side="right")
        body = tk.Frame(dialog, bg=palette.panel)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        text = tk.Text(body, bg=palette.card, fg=palette.text, relief="flat",
                       wrap="word", padx=14, pady=12, font=(SERIF, 11),
                       insertbackground=palette.text, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview,
                               style="Chitalka.Vertical.TScrollbar")
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("h", font=(SERIF, 13, "bold"), foreground=palette.accent,
                           spacing1=4, spacing3=8)
        text.tag_configure("p", font=(SERIF, 11), spacing3=8, lmargin1=0, lmargin2=0)
        text.tag_configure("i", font=(SERIF, 11, "italic"), spacing3=6)
        for block in blocks:
            kind = block.kind
            value = block.text().strip()
            if not value:
                continue
            if kind.startswith("h"):
                text.insert("end", value + "\n", "h")
            elif kind in ("epigraph", "cite"):
                text.insert("end", value + "\n", "i")
            else:
                text.insert("end", value + "\n\n", "p")
        text.configure(state="disabled")
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 480) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 320) // 3
        dialog.geometry(f"480x320+{max(0, x)}+{max(0, y)}")
        dialog.focus_set()

    # ------------------------------------------------------------------ панели
    def _open_panel(self, name: str) -> None:
        if self.panel_name == name:
            self._close_panel()
            return
        self._close_panel(relayout=False)
        palette = self.palette
        panel = tk.Frame(self.content, bg=palette.panel, width=350)
        panel.place(relx=1.0, y=0, rely=0, anchor="ne", relheight=1.0)
        panel.pack_propagate(False)
        self.panel = panel
        self.panel_name = name
        tk.Frame(panel, bg=palette.border, width=1).pack(side="left", fill="y")
        inner = tk.Frame(panel, bg=palette.panel)
        inner.pack(side="left", fill="both", expand=True)
        header = tk.Frame(inner, bg=palette.panel, height=54)
        header.pack(fill="x")
        header.pack_propagate(False)
        titles = {
            "toc": "Содержание", "bookmarks": "Закладки",
            "search": "Поиск по книге", "settings": "Оформление",
            "notes": "Заметки и выделения",
        }
        tk.Label(header, text=titles.get(name, ""), bg=palette.panel, fg=palette.text,
                 font=(SERIF, 14, "bold")).pack(side="left", padx=18, pady=14)
        IconButton(header, palette, "close", self._close_panel, size=30,
                   bg=palette.panel, tooltip="Закрыть").pack(side="right", padx=12)
        body = tk.Frame(inner, bg=palette.panel)
        body.pack(fill="both", expand=True)
        if name == "toc":
            self.toc_body = body
            self._populate_toc()
        elif name == "bookmarks":
            self._build_bookmarks(body)
        elif name == "notes":
            self._build_notes(body)
        elif name == "search":
            self._build_search(body)
        elif name == "settings":
            self._build_settings(body)
        for key, button in self._panel_buttons.items():
            button.set_active(key == name)
        if name == "search":
            self.after(30, self._focus_search)
        self.after(30, self._relayout_panel)

    def _relayout_panel(self) -> None:
        if not self._ready:
            return
        if self.is_pdf:
            self._render_pdf()
        else:
            self._layout_text()

    def _close_panel(self, relayout: bool = True) -> None:
        if self.panel is not None:
            try:
                self.panel.destroy()
            except tk.TclError:
                pass
        self.panel = None
        self.panel_name = ""
        for button in self._panel_buttons.values():
            button.set_active(False)
        if relayout and self._ready:
            if self.is_pdf:
                self._render_pdf()
            else:
                self._layout_text()
        elif self._ready:
            self.canvas.focus_set()

    def _populate_toc(self) -> None:
        if not hasattr(self, "toc_body") or not self.toc_body.winfo_exists():
            return
        for child in self.toc_body.winfo_children():
            child.destroy()
        if not self.doc or not self.doc.chapters:
            tk.Label(self.toc_body, text="Оглавление не найдено", bg=self.palette.panel,
                     fg=self.palette.muted, font=(UI, 9)).pack(pady=30)
            return
        scroll = ScrollFrame(self.toc_body, self.palette, bg=self.palette.panel)
        scroll.pack(fill="both", expand=True, pady=(0, 8))
        current_block = self._current_block()
        current_index = -1
        for index, chapter in enumerate(self.doc.chapters):
            if chapter.position <= current_block:
                current_index = index
            else:
                break
        for index, chapter in enumerate(self.doc.chapters):
            active = index == current_index
            row = tk.Frame(scroll.inner, bg=self.palette.panel, cursor="hand2")
            row.pack(fill="x", pady=1)
            if active:
                tk.Frame(row, bg=self.palette.accent, width=3).pack(side="left", fill="y")
            marker = tk.Frame(row, bg=self.palette.panel, height=42)
            marker.pack(side="left", fill="x", expand=True)
            pad = 16 + max(0, chapter.level - 1) * 14
            label = tk.Label(
                marker, text=ellipsis(chapter.title, 52), bg=self.palette.panel,
                fg=self.palette.accent if active else self.palette.text,
                font=(UI, 9, "bold" if active else "normal"), anchor="w", justify="left",
                wraplength=230,
            )
            label.place(x=pad, y=6, relwidth=1.0, width=-pad - 54, height=32)
            page_no = chapter.page if not self.is_pdf else chapter.position + 1
            number = tk.Label(marker, text=str(page_no + (0 if self.is_pdf else 1)),
                              bg=self.palette.panel, fg=self.palette.dim,
                              font=(UI, 8), anchor="e")
            number.place(relx=1.0, x=-14, y=12, width=38, height=18, anchor="ne")
            for widget in (row, marker, label, number):
                widget.bind("<Button-1>",
                            lambda _e, pos=chapter.position: self._toc_click(pos))
                widget.bind("<Enter>", lambda _e, widget=row: self._toc_hover(widget, True))
                widget.bind("<Leave>", lambda _e, widget=row: self._toc_hover(widget, False))

    def _toc_hover(self, row: tk.Frame, inside: bool) -> None:
        if inside:
            row.configure(bg=self.palette.card_hover)

    def _toc_click(self, position: int) -> None:
        self._close_panel()
        if self.is_pdf:
            page = position
        elif self.result:
            page = self.result.page_for_block(position)
        else:
            return
        self.go_to_page(page, add_history=True)

    # ------------------------------------------------------------------ закладки
    def _build_bookmarks(self, body: tk.Frame) -> None:
        top = tk.Frame(body, bg=self.palette.panel)
        top.pack(fill="x", padx=16, pady=(0, 8))
        PillButton(top, self.palette, "Добавить закладку", self._add_bookmark,
                   icon="plus", kind="primary", height=34, font_size=8,
                   bg=self.palette.panel).pack(fill="x")
        self.bookmarks_body = tk.Frame(body, bg=self.palette.panel)
        self.bookmarks_body.pack(fill="both", expand=True)
        self._populate_bookmarks()

    def _populate_bookmarks(self) -> None:
        if not hasattr(self, "bookmarks_body") or not self.bookmarks_body.winfo_exists():
            return
        for child in self.bookmarks_body.winfo_children():
            child.destroy()
        rows = self.db.bookmarks(self.book_id)
        if not rows:
            tk.Label(self.bookmarks_body, text="Закладок пока нет.\nДобавьте её кнопкой выше.",
                     bg=self.palette.panel, fg=self.palette.muted,
                     font=(UI, 9), justify="center").pack(pady=30)
            return
        scroll = ScrollFrame(self.bookmarks_body, self.palette, bg=self.palette.panel)
        scroll.pack(fill="both", expand=True)
        for bookmark in rows:
            row = tk.Frame(scroll.inner, bg=self.palette.panel, cursor="hand2")
            row.pack(fill="x", pady=1)
            text_box = tk.Frame(row, bg=self.palette.panel)
            text_box.pack(side="left", fill="x", expand=True, padx=(14, 4), pady=6)
            title = bookmark["note"] or bookmark["chapter"] or "Закладка"
            title_label = tk.Label(text_box, text=ellipsis(title, 44), bg=self.palette.panel,
                                   fg=self.palette.text, font=(UI, 9, "bold"), anchor="w",
                                   wraplength=240, justify="left")
            title_label.pack(fill="x")
            page_label = tk.Label(text_box, text=f"стр. {bookmark['page']}", bg=self.palette.panel,
                                  fg=self.palette.dim, font=(UI, 7), anchor="w")
            page_label.pack(fill="x")
            IconButton(row, self.palette, "trash",
                       lambda b_id=bookmark["id"]: self._delete_bookmark(b_id),
                       size=28, bg=self.palette.panel, tooltip="Удалить").pack(
                side="right", padx=(0, 8)
            )
            for widget in (row, text_box, title_label, page_label):
                widget.bind("<Button-1>", lambda _e, b=bookmark: self._goto_bookmark(b))

    def _add_bookmark(self) -> None:
        chapter = self._chapter_for_page()
        note = ask_text(self, self.palette, "Новая закладка",
                        "Заметка (необязательно)", initial="")
        if note is None:
            return
        self.db.add_bookmark(
            self.book_id, self._current_block(), 0, chapter,
            self.page_index + 1, note,
        )
        self._populate_bookmarks()
        self._flash("Закладка добавлена")

    def _delete_bookmark(self, bookmark_id: int) -> None:
        self.db.delete_bookmark(bookmark_id)
        self._populate_bookmarks()

    def _goto_bookmark(self, bookmark) -> None:
        block = int(bookmark["position"])
        pdf_page = int(bookmark["page"]) - 1
        self._close_panel()
        if self.is_pdf:
            page = pdf_page
        elif self.result:
            page = self.result.page_for_block(block)
        else:
            page = 0
        self.go_to_page(page, add_history=True)

    # ------------------------------------------------------------------ заметки
    def _build_notes(self, body: tk.Frame) -> None:
        palette = self.palette
        top = tk.Frame(body, bg=palette.panel)
        top.pack(fill="x", padx=16, pady=(0, 8))
        PillButton(top, palette, "Экспорт в Markdown", self._export_notes,
                   kind="soft", height=34, font_size=8,
                   bg=palette.panel).pack(fill="x")
        tk.Label(
            body, text="Выделите текст в книге, чтобы добавить маркер или заметку.",
            bg=palette.panel, fg=palette.dim, font=(UI, 8), justify="left",
            wraplength=300, anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 6))
        self.notes_body = tk.Frame(body, bg=palette.panel)
        self.notes_body.pack(fill="both", expand=True)
        self._populate_notes()

    def _populate_notes(self) -> None:
        if not hasattr(self, "notes_body") or not self.notes_body.winfo_exists():
            return
        for child in self.notes_body.winfo_children():
            child.destroy()
        palette = self.palette
        if not self.annotations:
            tk.Label(
                self.notes_body,
                text="Пока нет заметок.\nВыделите фрагмент и выберите «Заметка».",
                bg=palette.panel, fg=palette.muted, font=(UI, 9),
                justify="center",
            ).pack(pady=30)
            return
        scroll = ScrollFrame(self.notes_body, palette, bg=palette.panel)
        scroll.pack(fill="both", expand=True)
        for annotation in self.annotations:
            if self.is_pdf:
                page = int(annotation["page"] or 0) + 1
                chapter = self._chapter_at_page(page - 1)
            else:
                block = int(annotation["start_block"])
                page = self.result.page_for_block(block) + 1 if self.result else 0
                chapter = self.result.chapter_for_block(block) if self.result else ""
            row = tk.Frame(scroll.inner, bg=palette.panel, cursor="hand2")
            row.pack(fill="x", pady=2)
            swatch = tk.Canvas(row, width=5, height=74, bg=palette.panel,
                               highlightthickness=0, bd=0)
            swatch.pack(side="left", fill="y", padx=(3, 8))
            swatch.create_rectangle(
                0, 2, 5, 72, fill=note_color(str(annotation["color"])), outline=""
            )
            text_box = tk.Frame(row, bg=palette.panel)
            text_box.pack(side="left", fill="x", expand=True, pady=7)
            quote = " ".join(str(annotation["quote"]).split())
            quote_label = tk.Label(
                text_box, text=ellipsis(quote, 64), bg=palette.panel, fg=palette.text,
                font=(SERIF, 9, "bold"), anchor="w", justify="left",
                wraplength=220,
            )
            quote_label.pack(fill="x")
            comment = " ".join(str(annotation["comment"] or "").split())
            comment_label = None
            if comment:
                comment_label = tk.Label(
                    text_box, text=ellipsis(comment, 80), bg=palette.panel,
                    fg=palette.muted, font=(UI, 8), anchor="w", justify="left",
                    wraplength=220,
                )
                comment_label.pack(fill="x")
            color_label = NOTE_COLOR_LABELS.get(str(annotation["color"]), "маркер")
            if self.is_pdf:
                meta = f"{chapter} · {color_label}"
            else:
                meta = f"{chapter or 'Без главы'}  ·  стр. {page}"
            meta_label = tk.Label(
                text_box, text=ellipsis(meta, 44), bg=palette.panel, fg=palette.dim,
                font=(UI, 7), anchor="w",
            )
            meta_label.pack(fill="x", pady=(2, 0))
            IconButton(row, palette, "trash",
                       lambda a=annotation: self._delete_annotation(a),
                       size=26, bg=palette.panel, tooltip="Удалить").pack(
                side="right", padx=(0, 2)
            )
            IconButton(row, palette, "note",
                       lambda a=annotation: self._edit_annotation(a),
                       size=26, bg=palette.panel, tooltip="Изменить").pack(
                side="right", padx=0
            )
            for widget in (row, text_box, quote_label, meta_label):
                widget.bind("<Button-1>", lambda _e, a=annotation: self._jump_to_annotation(a))
            if comment_label is not None:
                comment_label.bind(
                    "<Button-1>", lambda _e, a=annotation: self._jump_to_annotation(a)
                )

    def _jump_to_annotation(self, annotation) -> None:
        self._close_panel()
        if self.is_pdf:
            page = int(annotation["page"] or 0)
        elif self.result:
            page = self.result.page_for_block(int(annotation["start_block"]))
        else:
            page = 0
        self.go_to_page(page, add_history=True)

    def _jump_to_block(self, block: int) -> None:
        self._close_panel()
        if not self.result:
            return
        page = self.result.page_for_block(block)
        self.go_to_page(page, add_history=True)

    def _export_notes(self) -> None:
        if not self.annotations:
            messagebox.showinfo("Экспорт заметок", "В этой книге пока нет заметок.",
                                parent=self)
            return
        safe_title = "".join(
            char if char not in '<>:"/\\|?*' else " " for char in self.doc.title
        ).strip()[:60]
        target = filedialog.asksaveasfilename(
            parent=self, title="Экспорт заметок в Markdown",
            defaultextension=".md", initialfile=f"Заметки — {safe_title}.md",
            filetypes=[("Markdown", "*.md"), ("Текст", "*.txt")],
        )
        if not target:
            return
        lines = [
            f"# Заметки — «{self.doc.title}»",
            "",
        ]
        if self.doc.author:
            lines += [f"**Автор:** {self.doc.author}", ""]
        lines += [f"*Экспорт: {date.today():%d.%m.%Y}*", ""]
        current_chapter = None
        for annotation in self.annotations:
            if self.is_pdf:
                page = int(annotation["page"] or 0) + 1
                chapter = self._chapter_at_page(page - 1)
            else:
                block = int(annotation["start_block"])
                chapter = self.result.chapter_for_block(block) if self.result else ""
                page = self.result.page_for_block(block) + 1 if self.result else 0
            if chapter and chapter != current_chapter:
                lines += [f"## {chapter}", ""]
                current_chapter = chapter
            color = NOTE_COLOR_LABELS.get(str(annotation["color"]), "Маркер")
            lines += [f"*Страница {page} · {color}*", ""]
            quote = str(annotation["quote"]).strip().replace("\n", "\n> ")
            lines += ["> " + quote, ""]
            comment = str(annotation["comment"] or "").strip()
            if comment:
                lines += [comment, ""]
            lines += ["---", ""]
        try:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
        except OSError as exc:
            messagebox.showerror("Экспорт заметок", str(exc), parent=self)
            return
        self._flash(f"Заметки сохранены: {Path(target).name}")

    # ------------------------------------------------------------------ поиск
    def _build_search(self, body: tk.Frame) -> None:
        self.search_entry = SearchEntry(
            body, self.palette, "Слово или фраза…", width=300,
            command=self._search_debounced,
        )
        self.search_entry.pack(fill="x", padx=16, pady=(0, 8))
        self.search_hint = tk.Label(body, text="Введите минимум два символа", bg=self.palette.panel,
                                    fg=self.palette.dim, font=(UI, 8), anchor="w")
        self.search_hint.pack(fill="x", padx=18)
        self.search_results = tk.Frame(body, bg=self.palette.panel)
        self.search_results.pack(fill="both", expand=True, pady=(4, 0))

    def _focus_search(self) -> None:
        if self.panel_name == "search" and hasattr(self, "search_entry"):
            self.search_entry.focus()

    def _search_debounced(self, _value: str) -> None:
        if self._search_job:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(260, self._do_search)

    def _do_search(self) -> None:
        self._search_job = None
        if self.panel_name != "search" or not hasattr(self, "search_results"):
            return
        query = self.search_entry.get().strip()
        for child in self.search_results.winfo_children():
            child.destroy()
        if len(query) < 2:
            self.search_hint.configure(text="Введите минимум два символа")
            return
        results: list[tuple[int, int, str, str]] = []
        if self.is_pdf and self.pdf:
            for page, snippet in self.pdf.search(query, limit=60):
                chapter = ""
                if self.doc:
                    for item in self.doc.chapters:
                        if item.position <= page:
                            chapter = item.title
                results.append((page, page, chapter, snippet))
        elif self.doc and self.result:
            needle = query.lower()
            for index, block in enumerate(self.doc.blocks):
                text = block.text()
                if not text:
                    continue
                start = text.lower().find(needle)
                if start < 0:
                    continue
                left = max(0, start - 45)
                right = min(len(text), start + len(query) + 70)
                snippet = ("…" if left else "") + " ".join(text[left:right].split())
                if right < len(text):
                    snippet += "…"
                page = self.result.page_for_block(index)
                chapter = self.result.chapter_for_block(index)
                results.append((index, page, chapter, snippet))
                if len(results) >= 60:
                    break
        self.search_hint.configure(
            text=f"Найдено: {len(results)}" if results else "Ничего не найдено"
        )
        if not results:
            return
        scroll = ScrollFrame(self.search_results, self.palette, bg=self.palette.panel)
        scroll.pack(fill="both", expand=True)
        for index, page, chapter, snippet in results:
            row = tk.Frame(scroll.inner, bg=self.palette.panel, cursor="hand2")
            row.pack(fill="x", pady=1)
            box = tk.Frame(row, bg=self.palette.panel)
            box.pack(fill="x", padx=14, pady=6)
            caption = f"{ellipsis(chapter, 34)}  ·  стр. {page + 1}"
            caption_label = tk.Label(box, text=caption, bg=self.palette.panel,
                                     fg=self.palette.accent, font=(UI, 7, "bold"), anchor="w")
            caption_label.pack(fill="x")
            snippet_label = tk.Label(box, text=snippet, bg=self.palette.panel,
                                     fg=self.palette.text, font=(UI, 9), anchor="w",
                                     justify="left", wraplength=280)
            snippet_label.pack(fill="x")
            for widget in (row, box, caption_label, snippet_label):
                widget.bind("<Button-1>", lambda _e, b=index, p=page: self._search_click(b, p))

    def _search_click(self, block: int, page: int) -> None:
        self._close_panel()
        if self.is_pdf:
            target = page
        elif self.result:
            target = self.result.page_for_block(block)
        else:
            target = page
        self.go_to_page(target, add_history=True)

    # ------------------------------------------------------------------ настройки
    def _build_settings(self, body: tk.Frame) -> None:
        palette = self.palette
        scroll = ScrollFrame(body, palette, bg=palette.panel)
        scroll.pack(fill="both", expand=True, padx=0)
        inner = scroll.inner
        pad = tk.Frame(inner, bg=palette.panel)
        pad.pack(fill="x", padx=18, pady=(0, 18))

        def section(title: str) -> tk.Frame:
            tk.Label(pad, text=title.upper(), bg=palette.panel, fg=palette.dim,
                     font=(UI, 7, "bold"), anchor="w").pack(fill="x", pady=(16, 6))
            return pad

        section("Тема страницы")
        theme_row = tk.Frame(pad, bg=palette.panel)
        theme_row.pack(fill="x")
        self._swatches = {}
        for key, theme in READING_THEMES.items():
            cell = tk.Frame(theme_row, bg=palette.panel)
            cell.pack(side="left", padx=(0, 8))
            swatch = tk.Canvas(cell, width=68, height=48, bg=palette.panel,
                               highlightthickness=0, bd=0, cursor="hand2")
            swatch.pack()
            self._swatches[key] = swatch
            self._draw_swatch(swatch, theme, key == self.settings.reader_theme)
            swatch.bind("<Button-1>", lambda _e, k=key: self._set_theme(k))
            tk.Label(cell, text=theme.name, bg=palette.panel, fg=palette.muted,
                     font=(UI, 7)).pack(pady=(3, 0))

        if not self.is_pdf:
            section("Шрифт и размер")
            self.font_combo = ttk.Combobox(
                pad, values=[f for f in FONT_CHOICES if f],
                state="readonly", style="Chitalka.TCombobox", font=(UI, 9),
            )
            self.font_combo.set(self.settings.font_family)
            self.font_combo.pack(fill="x", ipady=1)
            self.font_combo.bind("<<ComboboxSelected>>", self._on_font_family)
            size_line = tk.Frame(pad, bg=palette.panel)
            size_line.pack(fill="x", pady=(12, 0))
            tk.Label(size_line, text="Размер", bg=palette.panel, fg=palette.muted,
                     font=(UI, 8)).pack(side="left")
            self.size_label = tk.Label(size_line, text=f"{self.settings.font_size} px",
                                       bg=palette.panel, fg=palette.accent,
                                       font=(UI, 8, "bold"))
            self.size_label.pack(side="right")
            self.size_slider = Slider(pad, palette, minimum=13, maximum=32,
                                      value=self.settings.font_size, step=1,
                                      command=self._set_font_size, width=280, height=24,
                                      bg=palette.panel)
            self.size_slider.pack(fill="x", pady=(2, 8))

            row = tk.Frame(pad, bg=palette.panel)
            row.pack(fill="x")
            tk.Label(row, text="Межстрочный интервал", bg=palette.panel, fg=palette.muted,
                     font=(UI, 8)).pack(side="left")
            self.spacing_label = tk.Label(row, text=f"{self.settings.line_spacing:.2f}",
                                          bg=palette.panel, fg=palette.accent,
                                          font=(UI, 8, "bold"))
            self.spacing_label.pack(side="right")
            self.spacing_slider = Slider(pad, palette, minimum=1.15, maximum=2.05,
                                         value=self.settings.line_spacing, step=0.05,
                                         command=self._set_spacing, width=280, height=24,
                                         bg=palette.panel)
            self.spacing_slider.pack(fill="x", pady=(2, 8))

            row = tk.Frame(pad, bg=palette.panel)
            row.pack(fill="x")
            tk.Label(row, text="Поля страницы", bg=palette.panel, fg=palette.muted,
                     font=(UI, 8)).pack(side="left")
            self.margin_label = tk.Label(row, text=f"{self.settings.page_margin} px",
                                         bg=palette.panel, fg=palette.accent,
                                         font=(UI, 8, "bold"))
            self.margin_label.pack(side="right")
            self.margin_slider = Slider(pad, palette, minimum=28, maximum=96,
                                        value=self.settings.page_margin, step=2,
                                        command=self._set_margin, width=280, height=24,
                                        bg=palette.panel)
            self.margin_slider.pack(fill="x", pady=(2, 8))

            section("Набор")
            self._check(pad, "Выравнивать по ширине", "justify")
            self._check(pad, "Показывать колонтитулы", "show_header_footer")
            self._check(pad, "Новая страница с главы", "chapter_page_break")
        else:
            section("PDF")
            tk.Label(pad, text="PDF показывается постранично, как в оригинале.\n"
                              "Тема меняет только фон вокруг страницы.",
                     bg=palette.panel, fg=palette.muted, font=(UI, 8),
                     justify="left").pack(fill="x")

        section("Сброс")
        PillButton(pad, palette, "Вернуть настройки по умолчанию",
                   self._reset_reader_settings, kind="soft", height=34,
                   font_size=8, bg=palette.panel).pack(fill="x", pady=(0, 8))

    def _draw_swatch(self, canvas: tk.Canvas, theme: ReadingTheme, selected: bool) -> None:
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 68, 48, fill=theme.page,
                                outline=self.palette.accent if selected else self.palette.border,
                                width=2 if selected else 1)
        canvas.create_text(34, 19, text="Aa", fill=theme.text,
                           font=(self.settings.font_family, 12, "bold"))
        canvas.create_text(34, 37, text=theme.name, fill=theme.muted, font=(UI, 6))

    def _set_theme(self, key: str) -> None:
        self.settings.reader_theme = key
        self._save_settings_soon()
        for theme_key, canvas in self._swatches.items():
            if canvas.winfo_exists():
                self._draw_swatch(canvas, READING_THEMES[theme_key], theme_key == key)
        if self.is_pdf:
            self._render_pdf()
        else:
            self._render_text()

    def _on_font_family(self, _event=None) -> None:
        self.settings.font_family = self.font_combo.get()
        self._save_settings_soon()
        self._schedule_layout()

    def _set_font_size(self, value: float) -> None:
        self.settings.font_size = int(value)
        if hasattr(self, "size_label"):
            self.size_label.configure(text=f"{int(value)} px")
        self._save_settings_soon()
        self._schedule_layout()

    def _set_spacing(self, value: float) -> None:
        self.settings.line_spacing = round(float(value), 2)
        if hasattr(self, "spacing_label"):
            self.spacing_label.configure(text=f"{self.settings.line_spacing:.2f}")
        self._save_settings_soon()
        self._schedule_layout()

    def _set_margin(self, value: float) -> None:
        self.settings.page_margin = int(value)
        if hasattr(self, "margin_label"):
            self.margin_label.configure(text=f"{int(value)} px")
        self._save_settings_soon()
        self._schedule_layout()

    def _check(self, parent, text: str, key: str) -> None:
        palette = self.palette
        if key == "show_header_footer":
            var = tk.BooleanVar(value=bool(self.settings.show_header and self.settings.show_footer))
        else:
            var = tk.BooleanVar(value=bool(getattr(self.settings, key)))
        cb = tk.Checkbutton(
            parent, text=text, variable=var, bg=palette.panel, fg=palette.text,
            selectcolor=palette.card, activebackground=palette.panel,
            activeforeground=palette.text, font=(UI, 9), anchor="w", bd=0,
            highlightthickness=0, padx=0, command=lambda: self._toggle_check(key, var),
        )
        cb.pack(fill="x", pady=2)

    def _toggle_check(self, key: str, var: tk.BooleanVar) -> None:
        value = bool(var.get())
        if key == "show_header_footer":
            self.settings.show_header = value
            self.settings.show_footer = value
        else:
            setattr(self.settings, key, value)
        self._save_settings_soon()
        self._schedule_layout()

    def _schedule_layout(self) -> None:
        if self.is_pdf:
            return
        if self._layout_job:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.after(180, lambda: self._layout_text())

    def _reset_reader_settings(self) -> None:
        defaults = Settings()
        for key in (
            "reader_theme", "font_family", "font_size", "line_spacing", "page_margin",
            "justify", "show_header", "show_footer", "chapter_page_break",
        ):
            setattr(self.settings, key, getattr(defaults, key))
        self._save_settings_soon()
        was_settings = self.panel_name == "settings"
        self._close_panel()
        if was_settings:
            self._open_panel("settings")
        if self.is_pdf:
            self._render_pdf()
        else:
            self._schedule_layout()

    # ------------------------------------------------------------------ копирование
    def _page_text(self) -> str:
        if self.is_pdf and self.pdf:
            return self.pdf.page_text(self.page_index)
        if not self.pages or self.page_index >= len(self.pages):
            return ""
        lines = [line.text for line in self.pages[self.page_index].lines]
        return "\n".join(lines)

    def _copy_page(self) -> None:
        text = (self.selection or {}).get("quote", "").strip()
        if not text:
            text = self._page_text().strip()
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._flash("Скопировано")
        except tk.TclError:
            pass

    def _context_menu(self, event) -> None:
        menu = tk.Menu(
            self, tearoff=0, bg=self.palette.card, fg=self.palette.text,
            activebackground=self.palette.accent_soft, activeforeground=self.palette.accent,
            bd=0, relief="flat", font=(UI, 9),
        )
        if self.selection:
            menu.add_command(label="Словарь", command=lambda: self._open_lookup("dict"))
            menu.add_command(label="Перевод", command=lambda: self._open_lookup("translate"))
            menu.add_command(label="Выделить маркером", command=self._quick_highlight)
            menu.add_command(label="Заметка к выделению", command=self._note_from_selection)
            menu.add_command(label="Копировать выделенное", command=self._copy_selection)
            menu.add_separator()
        menu.add_command(label="Скопировать страницу", command=self._copy_page)
        menu.add_command(label="Добавить закладку", command=self._add_bookmark)
        menu.add_separator()
        menu.add_command(label="Заметки и выделения", command=lambda: self._open_panel("notes"))
        menu.add_command(label="Содержание", command=lambda: self._open_panel("toc"))
        menu.add_command(label="Оформление", command=lambda: self._open_panel("settings"))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ закрытие
    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._finish_session()
        except Exception:
            pass
        try:
            self._save_progress()
        except Exception:
            pass
        try:
            if self.fullscreen:
                self.attributes("-fullscreen", False)
                self.update_idletasks()
            self.settings.reader_geometry = self.geometry()
            self.settings.last_book_id = self.book_id
            self.settings.save()
        except Exception:
            pass
        try:
            if self.pdf:
                self.pdf.close()
        except Exception:
            pass
        book_id = self.book_id
        callback = self.on_close_cb
        try:
            self.destroy()
        finally:
            if callback:
                try:
                    callback(book_id)
                except Exception:
                    pass
