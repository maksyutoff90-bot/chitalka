"""О программе, лицензии и правовая информация."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

from ..config import APP_NAME, APP_VERSION, LEGAL_DIR
from ..theme import Palette
from .widgets import PillButton

UI = "Segoe UI"
SERIF = "Georgia"

DOCS = [
    ("EULA.md", "Пользовательское соглашение"),
    ("PRIVACY.md", "Конфиденциальность"),
    ("THIRD_PARTY_NOTICES.md", "Сторонние компоненты"),
    ("LICENSE_AUDIT.md", "Аудит лицензий"),
    ("licenses/README.md", "Тексты лицензий"),
]


class AboutWindow(tk.Toplevel):
    def __init__(self, master, palette: Palette) -> None:
        super().__init__(master)
        self.palette = palette
        self.title("О программе")
        self.configure(bg=palette.panel)
        self.geometry("560x660")
        self.resizable(False, False)
        self.transient(master)
        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _build(self) -> None:
        palette = self.palette
        wrap = tk.Frame(self, bg=palette.panel, padx=28, pady=24)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=APP_NAME, bg=palette.panel, fg=palette.text,
                 font=(SERIF, 24, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text=f"версия {APP_VERSION}", bg=palette.panel, fg=palette.muted,
                 font=(UI, 9), anchor="w").pack(fill="x", pady=(0, 12))
        tk.Label(
            wrap,
            text="Простая библиотека и читалка для Windows.\n"
                 "FB2, EPUB, PDF и TXT, офлайн-словарь, заметки и статистика.",
            bg=palette.panel, fg=palette.muted, font=(UI, 9),
            justify="left", anchor="w", wraplength=490,
        ).pack(fill="x", pady=(0, 14))
        for filename, title in DOCS:
            PillButton(wrap, palette, title, lambda name=filename: self._open_doc(name),
                       kind="soft", height=36, bg=palette.panel).pack(fill="x", pady=3)
        self.update_button = PillButton(
            wrap, palette, "Проверить обновления", self._check_updates,
            kind="ghost", height=36, bg=palette.panel,
        )
        self.update_button.pack(fill="x", pady=(12, 0))
        self.update_status = tk.Label(wrap, text="", bg=palette.panel, fg=palette.muted,
                                      font=(UI, 8), anchor="w")
        self.update_status.pack(fill="x", pady=(2, 0))
        PillButton(wrap, palette, "Закрыть", self.destroy, kind="ghost",
                   height=36, bg=palette.panel).pack(fill="x", pady=(10, 0))

    def _check_updates(self) -> None:
        from ..updater import UpdateError, check_latest

        self.update_button.set_enabled(False)
        self.update_status.configure(text="Проверяю GitHub…")
        self._update_queue = queue.Queue()

        def worker() -> None:
            try:
                self._update_queue.put((check_latest(APP_VERSION), ""))
            except UpdateError as exc:
                self._update_queue.put((None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_update)

    def _poll_update(self) -> None:
        try:
            result, error = self._update_queue.get_nowait()
        except queue.Empty:
            try:
                self.after(100, self._poll_update)
            except tk.TclError:
                pass
            return
        self._update_result(result, error)

    def _update_result(self, result: dict | None, error: str) -> None:
        try:
            self.update_button.set_enabled(True)
        except tk.TclError:
            return
        if error:
            self.update_status.configure(text=error[:120])
            return
        if not result:
            self.update_status.configure(text="У вас последняя версия.")
            return
        self.update_status.configure(text=f"Доступна версия {result['version']}.")
        if messagebox.askyesno(
            "Обновление",
            f"Доступна версия {result['version']}.\nОткрыть страницу загрузки?",
            parent=self,
        ):
            webbrowser.open(result["url"])

    def _open_doc(self, filename: str) -> None:
        path = LEGAL_DIR / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = f"Файл {path} не найден."
        title = dict(DOCS).get(filename, filename)
        LegalWindow(self, self.palette, title, text)


class LegalWindow(tk.Toplevel):
    def __init__(self, master, palette: Palette, title: str, text: str) -> None:
        super().__init__(master)
        self.title(title)
        self.configure(bg=palette.panel)
        self.geometry("720x700")
        self.transient(master)
        header = tk.Frame(self, bg=palette.panel, padx=20, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=title, bg=palette.panel, fg=palette.text,
                 font=(SERIF, 16, "bold"), anchor="w").pack(side="left")
        PillButton(header, palette, "Закрыть", self.destroy, kind="ghost",
                   height=30, font_size=8, bg=palette.panel).pack(side="right")
        body = tk.Frame(self, bg=palette.panel)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        scroll = tk.Scrollbar(body, orient="vertical")
        scroll.pack(side="right", fill="y")
        view = tk.Text(
            body, bg=palette.card, fg=palette.text, insertbackground=palette.text,
            font=(UI, 9), wrap="word", relief="flat", bd=0, padx=14, pady=12,
            yscrollcommand=scroll.set,
        )
        view.pack(side="left", fill="both", expand=True)
        scroll.configure(command=view.yview)
        view.insert("1.0", text)
        view.configure(state="disabled")
        self.bind("<Escape>", lambda _e: self.destroy())


def show_about(master, palette: Palette) -> AboutWindow:
    window = AboutWindow(master, palette)
    window.lift()
    window.focus_set()
    return window
