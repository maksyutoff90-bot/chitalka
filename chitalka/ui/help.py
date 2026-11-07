"""Короткая справка и быстрый старт."""

from __future__ import annotations

import tkinter as tk

from ..theme import Palette
from .icons import draw_icon
from .widgets import IconButton, PillButton, ScrollFrame

UI = "Segoe UI"
SERIF = "Georgia"


class HelpWindow(tk.Toplevel):
    def __init__(self, master, palette: Palette) -> None:
        super().__init__(master)
        self.palette = palette
        self.title("Как пользоваться")
        self.configure(bg=palette.bg)
        self.geometry("720x700")
        self.minsize(560, 520)
        self.transient(master)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())

    def _build(self) -> None:
        palette = self.palette
        header = tk.Frame(self, bg=palette.bg)
        header.pack(fill="x", padx=24, pady=(18, 4))
        tk.Label(header, text="Быстрый старт", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 22, "bold"), anchor="w").pack(side="left")
        IconButton(header, palette, "close", self.close, size=32,
                   bg=palette.bg, tooltip="Закрыть").pack(side="right")
        tk.Label(
            self, text="Три шага — и можно читать. Всё остальное необязательно.",
            bg=palette.bg, fg=palette.muted, font=(UI, 9), anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 12))

        scroll = ScrollFrame(self, palette, bg=palette.bg)
        scroll.pack(fill="both", expand=True, padx=24)
        wrap = scroll.inner

        steps = [
            ("1", "Добавьте книги",
             "«Добавить» → «Папка» или «Файлы». Подойдут FB2, EPUB, PDF и TXT.\n"
             "Или откройте «Каталоги» и скачайте книгу из Gutenberg / Викитеки."),
            ("2", "Откройте книгу",
             "Двойной клик по обложке — и вы в читалке. Или выделите книгу и нажмите «Читать».\n"
             "Кнопка «Продолжить» на главной возвращает к последней книге."),
            ("3", "Читайте с удобствами",
             "Выделите текст мышью — появятся «Словарь», «Перевод», «Выделить» и «Заметка».\n"
             "Заметки и цитаты собраны в разделе «Заметки», статистика — в «Статистике»."),
        ]
        for number, title, text in steps:
            card = tk.Frame(wrap, bg=palette.panel)
            card.pack(fill="x", pady=5)
            badge = tk.Canvas(card, width=38, height=38, bg=palette.panel,
                              highlightthickness=0, bd=0)
            badge.pack(side="left", padx=(14, 10), pady=12)
            badge.create_oval(3, 3, 35, 35, fill=palette.accent_soft, outline="")
            badge.create_text(19, 19, text=number, fill=palette.accent,
                              font=(SERIF, 14, "bold"))
            box = tk.Frame(card, bg=palette.panel)
            box.pack(side="left", fill="x", expand=True, pady=10)
            tk.Label(box, text=title, bg=palette.panel, fg=palette.text,
                     font=(SERIF, 12, "bold"), anchor="w").pack(fill="x")
            tk.Label(box, text=text, bg=palette.panel, fg=palette.muted,
                     font=(UI, 8), justify="left", anchor="w", wraplength=570).pack(
                fill="x", pady=(3, 0)
            )

        self._section(wrap, "ГДЕ ЧТО ЛЕЖИТ")
        for name, text in (
            ("Все книги", "вся библиотека и поиск"),
            ("Читаю", "книги, которые вы начали"),
            ("Избранное", "отмеченные книги"),
            ("Заметки", "все цитаты и комментарии по всем книгам"),
            ("Статистика", "время, страницы и серия дней"),
            ("Каталоги", "Gutenberg, Викитека и другие OPDS-каталоги"),
        ):
            row = tk.Frame(wrap, bg=palette.bg)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, bg=palette.bg, fg=palette.text,
                     font=(UI, 9, "bold"), width=14, anchor="w").pack(side="left")
            tk.Label(row, text=text, bg=palette.bg, fg=palette.muted,
                     font=(UI, 8), anchor="w").pack(side="left", fill="x", expand=True)

        self._section(wrap, "ГОРЯЧИЕ КЛАВИШИ")
        keys = [
            ("Ctrl+O", "добавить папку"),
            ("Ctrl+F", "поиск по библиотеке"),
            ("Enter", "открыть выбранную книгу"),
            ("F1", "эта справка"),
            ("Пробел / ← →", "листать в читалке"),
            ("Ctrl+B", "закладки в читалке"),
            ("Ctrl+T", "содержание"),
            ("Esc", "закрыть панель / снять выделение"),
            ("F11", "полный экран"),
        ]
        grid = tk.Frame(wrap, bg=palette.bg)
        grid.pack(fill="x", pady=(0, 14))
        for index, (key, text) in enumerate(keys):
            tk.Label(grid, text=key, bg=palette.bg, fg=palette.accent,
                     font=("Consolas", 8, "bold"), anchor="w").grid(
                row=index // 2, column=(index % 2) * 2, sticky="w", padx=(0, 8), pady=3
            )
            tk.Label(grid, text=text, bg=palette.bg, fg=palette.muted,
                     font=(UI, 8), anchor="w").grid(
                row=index // 2, column=(index % 2) * 2 + 1, sticky="w", padx=(0, 24), pady=3
            )

        footer = tk.Frame(self, bg=palette.bg)
        footer.pack(fill="x", padx=24, pady=14)
        PillButton(footer, palette, "О программе и лицензиях", self._about,
                   kind="ghost", height=38, bg=palette.bg).pack(side="left")
        PillButton(footer, palette, "Понятно", self.close, kind="primary",
                   height=38, bg=palette.bg).pack(side="right")

    def _about(self) -> None:
        from .about import show_about

        window = getattr(self, "_about_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.lift()
                    return
            except tk.TclError:
                pass
        self._about_window = show_about(self, self.palette)

    def _section(self, parent, text: str) -> None:
        tk.Label(parent, text=text, bg=self.palette.bg, fg=self.palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", pady=(16, 5))

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


def show_help(master, palette: Palette) -> HelpWindow:
    window = HelpWindow(master, palette)
    window.lift()
    window.focus_set()
    return window
