"""Мастер первого запуска: три коротких экрана."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..theme import Palette
from .icons import draw_icon
from .widgets import IconButton, PillButton

UI = "Segoe UI"
SERIF = "Georgia"


class OnboardingWizard(tk.Toplevel):
    def __init__(self, master, palette: Palette, *, on_finish: Callable[[bool], None],
                 on_add_folder: Callable[[], None],
                 on_add_files: Callable[[], None],
                 on_catalogs: Callable[[], None]) -> None:
        super().__init__(master)
        self.palette = palette
        self.on_finish = on_finish
        self.on_add_folder = on_add_folder
        self.on_add_files = on_add_files
        self.on_catalogs = on_catalogs
        self.step = 0
        self.simple = tk.BooleanVar(value=True)
        self._done = False
        self.title("Добро пожаловать")
        self.configure(bg=palette.panel)
        self.resizable(False, False)
        self.transient(master)
        width, height = 620, 500
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + (master.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.bind("<Escape>", lambda _e: self._skip())
        self._render()

    def _build(self) -> None:
        palette = self.palette
        header = tk.Frame(self, bg=palette.panel)
        header.pack(fill="x", padx=24, pady=(16, 0))
        self.step_label = tk.Label(header, text="", bg=palette.panel, fg=palette.dim,
                                   font=(UI, 8, "bold"), anchor="w")
        self.step_label.pack(side="left")
        IconButton(header, palette, "close", self._skip, size=30,
                   bg=palette.panel, tooltip="Пропустить").pack(side="right")
        self.body = tk.Frame(self, bg=palette.panel)
        self.body.pack(fill="both", expand=True, padx=24, pady=(8, 0))
        footer = tk.Frame(self, bg=palette.panel)
        footer.pack(fill="x", padx=24, pady=16)
        self.back_button = PillButton(footer, palette, "Назад", self._back,
                                      kind="ghost", height=38, bg=palette.panel)
        self.back_button.pack(side="left")
        self.next_button = PillButton(footer, palette, "Далее", self._next,
                                      kind="primary", height=38, bg=palette.panel)
        self.next_button.pack(side="right")

    def _render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.step_label.configure(text=f"ШАГ {self.step + 1} ИЗ 3")
        self.back_button.set_enabled(self.step > 0)
        self.next_button.set_text("Начать читать" if self.step == 2 else "Далее")
        if self.step == 0:
            self._step_welcome()
        elif self.step == 1:
            self._step_books()
        else:
            self._step_read()

    def _step_welcome(self) -> None:
        palette = self.palette
        icon = tk.Canvas(self.body, width=76, height=76, bg=palette.panel,
                         highlightthickness=0, bd=0)
        icon.pack(pady=(28, 8))
        draw_icon(icon, "book", 38, 38, 52, palette.accent, width=1.5)
        tk.Label(self.body, text="Читалка", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 24, "bold")).pack()
        tk.Label(
            self.body,
            text="Простая библиотека для Windows.\nFB2, EPUB, PDF и TXT — без настройки и лишних окон.",
            bg=palette.panel, fg=palette.muted, font=(UI, 10),
            justify="center", wraplength=480,
        ).pack(pady=(8, 0))
        tk.Label(
            self.body,
            text="Три шага: добавить книги → открыть → читать.",
            bg=palette.panel, fg=palette.accent, font=(UI, 9, "bold"),
        ).pack(pady=(18, 0))

    def _step_books(self) -> None:
        palette = self.palette
        tk.Label(self.body, text="Добавьте книги", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 20, "bold")).pack(anchor="w", pady=(18, 4))
        tk.Label(
            self.body,
            text="Можно выбрать папку, отдельные файлы или скачать книгу из каталога.\n"
                 "Файлы и папки также можно просто перетащить в окно библиотеки.",
            bg=palette.panel, fg=palette.muted, font=(UI, 9),
            justify="left", anchor="w", wraplength=550,
        ).pack(fill="x", pady=(0, 16))
        PillButton(self.body, palette, "Добавить папку", self.on_add_folder,
                   icon="folder", kind="primary", height=40).pack(fill="x", pady=4)
        PillButton(self.body, palette, "Добавить файлы", self.on_add_files,
                   icon="plus", kind="soft", height=38).pack(fill="x", pady=4)
        PillButton(self.body, palette, "Скачать из Gutenberg", self.on_catalogs,
                   icon="globe", kind="ghost", height=38).pack(fill="x", pady=4)
        self.book_hint = tk.Label(
            self.body, text="После добавления нажмите «Далее».", bg=palette.panel,
            fg=palette.dim, font=(UI, 8),
        )
        self.book_hint.pack(pady=(10, 0))

    def _step_read(self) -> None:
        palette = self.palette
        tk.Label(self.body, text="Как читать", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 20, "bold")).pack(anchor="w", pady=(18, 4))
        for title, text in (
            ("Двойной клик по обложке", "открывает книгу. Кнопка «Продолжить» возвращает к последней."),
            ("Выделите текст мышью", "появятся словарь, перевод, маркер и заметка."),
            ("F1", "открывает справку; Esc закрывает панели, Ctrl+F ищет по книге."),
        ):
            row = tk.Frame(self.body, bg=palette.panel)
            row.pack(fill="x", pady=5)
            tk.Label(row, text=title, bg=palette.panel, fg=palette.text,
                     font=(UI, 9, "bold"), anchor="w", width=23).pack(side="left")
            tk.Label(row, text=text, bg=palette.panel, fg=palette.muted,
                     font=(UI, 8), anchor="w", justify="left", wraplength=330).pack(
                side="left", fill="x", expand=True
            )
        tk.Frame(self.body, bg=palette.border, height=1).pack(fill="x", pady=(14, 10))
        tk.Checkbutton(
            self.body, text="  Только чтение — скрыть каталоги и статистику",
            variable=self.simple, bg=palette.panel, fg=palette.text,
            activebackground=palette.panel, activeforeground=palette.text,
            selectcolor=palette.panel, font=(UI, 9), anchor="w",
            bd=0, highlightthickness=0, cursor="hand2",
        ).pack(fill="x")
        tk.Label(
            self.body, text="Этот режим можно включить или выключить позже в боковой панели.",
            bg=palette.panel, fg=palette.dim, font=(UI, 7), anchor="w",
        ).pack(fill="x", pady=(4, 0))

    def _back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._render()

    def _next(self) -> None:
        if self.step < 2:
            self.step += 1
            self._render()
            return
        self._finish()

    def _skip(self) -> None:
        self._finish(bool(self.simple.get()) if self.step == 2 else False)

    def _finish(self, simple_mode: bool | None = None) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.on_finish(bool(self.simple.get()) if simple_mode is None else simple_mode)
        finally:
            try:
                self.destroy()
            except tk.TclError:
                pass
