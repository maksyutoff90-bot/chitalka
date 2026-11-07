"""Экран принятия EULA и политики конфиденциальности."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..config import LEGAL_DIR
from ..theme import Palette
from .about import LegalWindow
from .widgets import PillButton

UI = "Segoe UI"
SERIF = "Georgia"


class LegalGate(tk.Toplevel):
    def __init__(self, master, palette: Palette, *,
                 on_accept: Callable[[], None],
                 on_decline: Callable[[], None]) -> None:
        super().__init__(master)
        self.palette = palette
        self.on_accept = on_accept
        self.on_decline = on_decline
        self.accepted = tk.BooleanVar(value=False)
        self.title("Перед началом")
        self.configure(bg=palette.panel)
        self.geometry("660x600")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._decline)
        self.bind("<Escape>", lambda _e: self._decline())
        self._build()
        self._update_button()

    def _build(self) -> None:
        palette = self.palette
        wrap = tk.Frame(self, bg=palette.panel, padx=28, pady=22)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="Перед началом", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 22, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            wrap,
            text="Читалка хранит библиотеку и заметки локально. "
                 "Перед использованием примите условия.",
            bg=palette.panel, fg=palette.muted, font=(UI, 9),
            justify="left", anchor="w", wraplength=590,
        ).pack(fill="x", pady=(4, 12))

        text = tk.Text(
            wrap, height=13, bg=palette.card, fg=palette.text,
            insertbackground=palette.text, relief="flat", bd=0, wrap="word",
            padx=14, pady=12, font=(UI, 9), highlightthickness=1,
            highlightbackground=palette.border,
        )
        text.pack(fill="both", expand=True)
        text.insert(
            "1.0",
            "Коротко:\n\n"
            "• Вы получаете лицензию на использование одной копии программы.\n"
            "• Коммерческая версия распространяется как проприетарное приложение.\n"
            "• Библиотека, настройки и заметки хранятся на вашем компьютере.\n"
            "• Онлайн-функции отправляют данные только выбранному сервису.\n"
            "• Программа предоставляется «как есть»; делайте резервные копии.\n\n"
            "Полные тексты: пользовательское соглашение (EULA) и политика "
            "конфиденциальности. Они доступны по кнопкам ниже и в разделе "
            "«О программе».",
        )
        text.configure(state="disabled")
        text.tag_configure("h", font=(UI, 10, "bold"))

        links = tk.Frame(wrap, bg=palette.panel)
        links.pack(fill="x", pady=(12, 6))
        PillButton(links, palette, "Пользовательское соглашение",
                   lambda: self._open("EULA.md", "Пользовательское соглашение"),
                   kind="soft", height=32, font_size=8, bg=palette.panel).pack(
            side="left", padx=(0, 8)
        )
        PillButton(links, palette, "Политика конфиденциальности",
                   lambda: self._open("PRIVACY.md", "Конфиденциальность"),
                   kind="soft", height=32, font_size=8, bg=palette.panel).pack(side="left")

        tk.Checkbutton(
            wrap, text="  Я прочитал(а) и принимаю EULA и политику конфиденциальности",
            variable=self.accepted, command=self._update_button,
            bg=palette.panel, fg=palette.text, activebackground=palette.panel,
            activeforeground=palette.text, selectcolor=palette.panel,
            font=(UI, 9), anchor="w", bd=0, highlightthickness=0, cursor="hand2",
        ).pack(fill="x", pady=(8, 0))

        actions = tk.Frame(wrap, bg=palette.panel)
        actions.pack(fill="x", pady=(12, 0))
        PillButton(actions, palette, "Выйти", self._decline, kind="ghost",
                   height=38, bg=palette.panel).pack(side="left")
        self.accept_button = PillButton(
            actions, palette, "Принять и продолжить", self._accept,
            kind="primary", height=38, bg=palette.panel,
        )
        self.accept_button.pack(side="right")

    def _update_button(self) -> None:
        try:
            self.accept_button.set_enabled(bool(self.accepted.get()))
        except tk.TclError:
            pass

    def _open(self, filename: str, title: str) -> None:
        try:
            text = (LEGAL_DIR / filename).read_text(encoding="utf-8")
        except OSError:
            text = f"Файл {filename} не найден."
        LegalWindow(self, self.palette, title, text)

    def _accept(self) -> None:
        if not self.accepted.get():
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_accept()

    def _decline(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_decline()
