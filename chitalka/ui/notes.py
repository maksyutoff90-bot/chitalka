"""Заметки, цветные маркеры и панель действий над выделением."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..theme import Palette
from .widgets import PillButton, round_rect

UI = "Segoe UI"
SERIF = "Georgia"

NOTE_COLORS = [
    ("yellow", "Жёлтый", "#f2cf5b"),
    ("green", "Зелёный", "#8fc98a"),
    ("blue", "Голубой", "#8bb8dc"),
    ("pink", "Розовый", "#e7a0b4"),
]
NOTE_COLOR_LABELS = {key: label for key, label, _ in NOTE_COLORS}

_COLOR_FILLS = {
    "yellow": {"light": "#f7e4a1", "dark": "#4a4124"},
    "green": {"light": "#cfe7c4", "dark": "#2d4530"},
    "blue": {"light": "#cfe0f1", "dark": "#2b3d4d"},
    "pink": {"light": "#f2d0dc", "dark": "#4a2e39"},
}


def note_color(name: str, dark: bool = False) -> str:
    return _COLOR_FILLS.get(name, _COLOR_FILLS["yellow"])["dark" if dark else "light"]


class SelectionToolbar(tk.Frame):
    def __init__(self, master, palette: Palette,
                 callback: Callable[[str], None]) -> None:
        super().__init__(master, bg=palette.border)
        self.palette = palette
        self.callback = callback
        self.master_window = master
        frame = tk.Frame(self, bg=palette.panel)
        frame.pack(padx=1, pady=1)
        buttons = [
            ("Словарь", "dict"),
            ("Перевод", "translate"),
            ("Выделить", "highlight"),
            ("Заметка", "note"),
            ("Копировать", "copy"),
        ]
        for text, action in buttons:
            button = tk.Button(
                frame, text=text, command=lambda a=action: self._click(a),
                bg=palette.panel, fg=palette.text, activebackground=palette.accent_soft,
                activeforeground=palette.accent, relief="flat", bd=0,
                font=(UI, 8), padx=9, pady=5, cursor="hand2",
            )
            button.pack(side="left", padx=1, pady=1)
        tk.Button(
            frame, text="×", command=self.close, bg=palette.panel, fg=palette.muted,
            activebackground=palette.card, activeforeground=palette.text,
            relief="flat", bd=0, font=(UI, 9), padx=6, pady=5,
        ).pack(side="left", padx=(2, 1), pady=1)
        self.update_idletasks()

    def _click(self, action: str) -> None:
        self.close()
        self.callback(action)

    def show_at(self, x_root: int, y_root: int) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        parent = self.master_window
        x = int(x_root) - parent.winfo_rootx() - width // 2
        y = int(y_root) - parent.winfo_rooty() - height - 10
        if y < 56:
            y = int(y_root) - parent.winfo_rooty() + 14
        max_x = max(8, parent.winfo_width() - width - 8)
        max_y = max(8, parent.winfo_height() - height - 8)
        self.place(x=max(8, min(x, max_x)), y=max(8, min(y, max_y)))
        self.lift()

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


class ColorPopup(tk.Toplevel):
    def __init__(self, master, palette: Palette, x_root: int, y_root: int) -> None:
        super().__init__(master)
        self.palette = palette
        self.result: str | None = None
        self.overrideredirect(True)
        self.configure(bg=palette.border)
        frame = tk.Frame(self, bg=palette.panel)
        frame.pack(padx=1, pady=1)
        for key, label, color in NOTE_COLORS:
            cell = tk.Frame(frame, bg=palette.panel, cursor="hand2")
            cell.pack(side="left", padx=6, pady=6)
            swatch = tk.Canvas(cell, width=32, height=24, bg=palette.panel,
                               highlightthickness=0, bd=0, cursor="hand2")
            swatch.pack()
            round_rect(swatch, 1, 1, 31, 23, 5, fill=color, outline=palette.border)
            tk.Label(cell, text=label, bg=palette.panel, fg=palette.muted,
                     font=(UI, 6)).pack(pady=(2, 0))
            for widget in (cell, swatch):
                widget.bind("<Button-1>", lambda _e, k=key: self._choose(k))
        self.update_idletasks()
        width = self.winfo_width()
        x = max(8, min(int(x_root) - width // 2, self.winfo_screenwidth() - width - 8))
        y = max(8, int(y_root) - self.winfo_height() - 8)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        self.bind("<FocusOut>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            pass

    def _choose(self, key: str) -> None:
        self.result = key
        self.destroy()

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


class NoteDialog(tk.Toplevel):
    def __init__(self, master, palette: Palette, quote: str, *,
                 color: str = "yellow", comment: str = "",
                 title: str = "Новая заметка") -> None:
        super().__init__(master)
        self.palette = palette
        self.quote = quote
        self.color = color
        self.result: tuple[str, str] | None = None
        self.title(title)
        self.configure(bg=palette.panel)
        self.transient(master)
        self.resizable(False, False)
        self.grab_set()
        frame = tk.Frame(self, bg=palette.panel, padx=22, pady=18)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=title, bg=palette.panel, fg=palette.text,
                 font=(SERIF, 15, "bold"), anchor="w").pack(fill="x")

        quote_box = tk.Text(frame, height=4, bg=palette.card, fg=palette.muted,
                            font=(SERIF, 10), relief="flat", wrap="word", bd=0,
                            padx=10, pady=8, highlightthickness=0)
        quote_box.insert("1.0", quote[:1200])
        quote_box.configure(state="disabled")
        quote_box.pack(fill="x", pady=(8, 12))

        tk.Label(frame, text="ЦВЕТ МАРКЕРА", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", pady=(0, 5))
        colors = tk.Frame(frame, bg=palette.panel)
        colors.pack(fill="x", pady=(0, 12))
        self.swatches: dict[str, tk.Canvas] = {}
        for key, label, color_hex in NOTE_COLORS:
            cell = tk.Frame(colors, bg=palette.panel, cursor="hand2")
            cell.pack(side="left", padx=(0, 9))
            swatch = tk.Canvas(cell, width=44, height=30, bg=palette.panel,
                               highlightthickness=0, bd=0, cursor="hand2")
            swatch.pack()
            swatch.bind("<Button-1>", lambda _e, k=key: self._select_color(k))
            label_widget = tk.Label(cell, text=label, bg=palette.panel, fg=palette.muted,
                                    font=(UI, 6), cursor="hand2")
            label_widget.pack(pady=(2, 0))
            label_widget.bind("<Button-1>", lambda _e, k=key: self._select_color(k))
            self.swatches[key] = swatch

        tk.Label(frame, text="КОММЕНТАРИЙ", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", pady=(0, 5))
        self.comment = tk.Text(frame, height=5, bg=palette.card, fg=palette.text,
                               insertbackground=palette.text, font=(UI, 9),
                               relief="flat", wrap="word", bd=0, padx=10, pady=8,
                               highlightthickness=1, highlightbackground=palette.border,
                               highlightcolor=palette.accent)
        self.comment.insert("1.0", comment)
        self.comment.pack(fill="x")

        buttons = tk.Frame(frame, bg=palette.panel)
        buttons.pack(fill="x", pady=(14, 0))
        PillButton(buttons, palette, "Отмена", self._cancel, kind="ghost",
                   height=34, bg=palette.panel).pack(side="right", padx=(8, 0))
        PillButton(buttons, palette, "Сохранить", self._save, kind="primary",
                   height=34, bg=palette.panel).pack(side="right")
        self.bind("<Escape>", lambda _e: self._cancel())
        self._select_color(self.color)
        self.update_idletasks()
        width, height = 540, self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + max(20, (master.winfo_height() - height) // 3)
        self.geometry(f"540x{height}+{max(0, x)}+{max(0, y)}")
        self.comment.focus_set()

    def _select_color(self, key: str) -> None:
        self.color = key
        for color_key, canvas in self.swatches.items():
            canvas.delete("all")
            _key, _label, color_hex = next(
                (k, l, c) for k, l, c in NOTE_COLORS if k == color_key
            )
            selected = color_key == key
            round_rect(canvas, 1, 1, 43, 29, 6, fill=color_hex,
                       outline=self.palette.accent if selected else self.palette.border,
                       width=2 if selected else 1)

    def _save(self) -> None:
        self.result = (self.color, self.comment.get("1.0", "end").strip())
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()
