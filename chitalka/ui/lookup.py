"""Окно словаря и перевода для выделенного фрагмента."""

from __future__ import annotations

import queue
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .. import dictionary
from ..config import Settings, load_settings
from ..theme import Palette
from .icons import draw_icon
from .widgets import IconButton, PillButton, round_rect

UI = "Segoe UI"
SERIF = "Georgia"


class LookupWindow(tk.Toplevel):
    def __init__(self, master, palette: Palette, text: str, *,
                 mode: str = "both", on_close: Callable | None = None,
                 cache=None, settings: Settings | None = None) -> None:
        super().__init__(master)
        self.palette = palette
        self.text = " ".join((text or "").split())
        self.source, self.target = dictionary.source_pair(self.text)
        self.mode = mode
        self.cache = cache
        self.settings = settings or load_settings()
        self.queue: queue.Queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.closed = False
        self._poll_job = None
        self._request_id = 0
        self._result: dict = {}
        self._translation = ""
        self.on_close_cb = on_close
        self.title("Словарь и перевод")
        self.configure(bg=palette.panel)
        self.minsize(520, 560)
        self.geometry("620x680")
        self.transient(master)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.after(80, self._start)
        self._poll_job = self.after(120, self._poll)

    def _build(self) -> None:
        palette = self.palette
        header = tk.Frame(self, bg=palette.panel)
        header.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(header, text="Словарь и перевод", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 17, "bold"), anchor="w").pack(side="left")
        IconButton(header, palette, "close", self.close, size=30,
                   bg=palette.panel, tooltip="Закрыть").pack(side="right")

        quote = tk.Label(self, text=self.text[:500], bg=palette.card, fg=palette.text,
                         font=(SERIF, 12), wraplength=560, justify="left", anchor="w",
                         padx=14, pady=10)
        quote.pack(fill="x", padx=20, pady=(0, 8))

        lang = tk.Frame(self, bg=palette.panel)
        lang.pack(fill="x", padx=20, pady=(0, 6))
        self.lang_label = tk.Label(lang, text="", bg=palette.panel, fg=palette.muted,
                                   font=(UI, 8), anchor="w")
        self.lang_label.pack(side="left")
        self.swap_button = PillButton(lang, palette, "Поменять язык", self._swap,
                                      kind="ghost", height=30, font_size=8,
                                      bg=palette.panel)
        self.swap_button.pack(side="right")
        self._update_lang()

        trans_box = tk.Frame(self, bg=palette.panel)
        trans_box.pack(fill="x", padx=20, pady=(4, 8))
        head = tk.Frame(trans_box, bg=palette.panel)
        head.pack(fill="x")
        tk.Label(head, text="ПЕРЕВОД", bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(side="left")
        self.trans_status = tk.Label(head, text="…", bg=palette.panel, fg=palette.muted,
                                     font=(UI, 8), anchor="e")
        self.trans_status.pack(side="right")
        self.trans_text = tk.Text(trans_box, height=4, bg=palette.card, fg=palette.text,
                                  font=(SERIF, 12), relief="flat", wrap="word", bd=0,
                                  padx=12, pady=10, highlightthickness=0)
        self.trans_text.pack(fill="x")
        self.trans_text.configure(state="disabled")
        actions = tk.Frame(trans_box, bg=palette.panel)
        actions.pack(fill="x", pady=(4, 0))
        PillButton(actions, palette, "Скопировать перевод", self._copy_translation,
                   kind="ghost", height=30, font_size=8, bg=palette.panel).pack(side="left")
        PillButton(actions, palette, "Открыть в браузере", self._open_browser,
                   kind="ghost", height=30, font_size=8, bg=palette.panel).pack(side="right")

        self.footer = tk.Frame(self, bg=palette.panel)
        self.footer.pack(side="bottom", fill="x", padx=20, pady=(0, 10))
        self.footer_label = tk.Label(self.footer, text="Офлайн-словарь FreeDict",
                                     bg=palette.panel, fg=palette.dim,
                                     font=(UI, 7), anchor="w")
        self.footer_label.pack(side="left", fill="x", expand=True)
        link = tk.Label(self.footer, text="Настроить перевод", bg=palette.panel,
                        fg=palette.accent, font=(UI, 7, "bold"), cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: self._open_translation_settings())
        if self.cache is not None:
            try:
                self.footer_label.configure(
                    text=f"Офлайн-словарь FreeDict · кэш: {self.cache.cache_count()}"
                )
            except Exception:
                pass

        dict_box = tk.Frame(self, bg=palette.panel)
        dict_box.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        head = tk.Frame(dict_box, bg=palette.panel)
        head.pack(fill="x")
        self.dict_title = tk.Label(head, text="СЛОВАРЬ", bg=palette.panel,
                                   fg=palette.dim, font=(UI, 7, "bold"), anchor="w")
        self.dict_title.pack(side="left")
        self.dict_status = tk.Label(head, text="…", bg=palette.panel, fg=palette.muted,
                                    font=(UI, 8), anchor="e")
        self.dict_status.pack(side="right")
        body = tk.Frame(dict_box, bg=palette.panel)
        body.pack(fill="both", expand=True)
        self.dict_text = tk.Text(body, bg=palette.card, fg=palette.text, font=(UI, 9),
                                 relief="flat", wrap="word", bd=0, padx=12, pady=10,
                                 highlightthickness=0, spacing3=4)
        scroll = tk.Scrollbar(body, orient="vertical", command=self.dict_text.yview,
                              bg=palette.card, troughcolor=palette.panel,
                              activebackground=palette.accent_soft, relief="flat",
                              bd=0, width=10)
        self.dict_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.dict_text.pack(side="left", fill="both", expand=True)
        self.dict_text.configure(state="disabled")

    def _update_lang(self) -> None:
        self.lang_label.configure(
            text=f"{dictionary.language_name(self.source)} → "
                 f"{dictionary.language_name(self.target)}"
        )

    def _start(self) -> None:
        if self.closed:
            return
        self._set_translation("…", "Перевод…")
        word = dictionary.first_word(self.text)
        self.dict_title.configure(text=f"СЛОВАРЬ · {word}".upper() if word else "СЛОВАРЬ")
        self._set_dictionary([], "Ищу слово…")
        source, target = self.source, self.target
        text = self.text
        config = self._translation_kwargs()
        self._request_id += 1
        request = self._request_id

        def translation_worker() -> None:
            try:
                value = dictionary.translate(
                    text, source, target, cache=self.cache, with_source=True, **config
                )
                self.queue.put(("translation", value, "", request))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("translation", "", str(exc), request))

        def dictionary_worker() -> None:
            try:
                value = dictionary.lookup(text, source, cache=self.cache)
                self.queue.put(("dictionary", value, "", request))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("dictionary", None, str(exc), request))

        self.executor.submit(translation_worker)
        self.executor.submit(dictionary_worker)

    def _translation_kwargs(self) -> dict:
        return {
            "provider": str(getattr(self.settings, "translation_provider", "offline") or "offline"),
            "endpoint": str(getattr(self.settings, "translation_endpoint", "") or ""),
            "api_key": str(getattr(self.settings, "translation_key", "") or ""),
            "email": str(getattr(self.settings, "translation_email", "") or ""),
        }

    def _open_translation_settings(self) -> None:
        dialog = TranslationSettingsDialog(self, self.palette, self.settings)
        self.wait_window(dialog)
        if dialog.saved:
            self._start()

    def _swap(self) -> None:
        self.source, self.target = self.target, self.source
        self._update_lang()
        self._start()

    def _set_translation(self, value: str, status: str) -> None:
        self._translation = value
        self.trans_text.configure(state="normal")
        self.trans_text.delete("1.0", "end")
        self.trans_text.insert("1.0", value)
        self.trans_text.configure(state="disabled")
        self.trans_status.configure(text=status)

    def _set_dictionary(self, definitions: list[str], status: str) -> None:
        self.dict_text.configure(state="normal")
        self.dict_text.delete("1.0", "end")
        if definitions:
            for line in definitions:
                self.dict_text.insert("end", line + "\n\n")
        self.dict_text.configure(state="disabled")
        if status:
            self.dict_status.configure(text=status)

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                kind, value, error, request = self.queue.get_nowait()
                if request != self._request_id:
                    continue
                if kind == "translation":
                    if error:
                        status = "не настроен" if "не настроен" in error.lower() else "ошибка"
                        self._set_translation(error, status)
                    else:
                        if isinstance(value, tuple):
                            translation, origin = value
                        else:
                            translation, origin = value, "готово"
                        self._set_translation(translation, origin)
                elif kind == "dictionary":
                    if error or not value:
                        self._set_dictionary([
                            "В словаре нет отдельной статьи для этого слова.",
                            "",
                            "Перевод уже показан выше. Можно открыть Викисловарь "
                            "кнопкой «Открыть в браузере».",
                        ], "Не найдено")
                    else:
                        self._result = value
                        self.dict_title.configure(
                            text=f"СЛОВАРЬ · {value.get('word', '')}".upper()
                        )
                        source = str(value.get("source") or "словарь")
                        phonetic = str(value.get("phonetic") or "")
                        self.dict_status.configure(
                            text=f"{phonetic} · {source}" if phonetic else source
                        )
                        self._set_dictionary(value.get("definitions") or [], "")
                        if self.cache is not None:
                            try:
                                self.footer_label.configure(
                                    text=f"Офлайн-словарь FreeDict · кэш: {self.cache.cache_count()}"
                                )
                            except Exception:
                                pass
        except queue.Empty:
            pass
        self._poll_job = self.after(120, self._poll)

    def _copy_translation(self) -> None:
        if not self._translation:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._translation)
            self.footer_label.configure(text="Перевод скопирован")
        except tk.TclError:
            pass

    def _open_browser(self) -> None:
        url = (self._result or {}).get("url")
        if not url:
            word = dictionary.first_word(self.text)
            if word:
                url = ("https://ru.wiktionary.org/wiki/" if self.source == "ru"
                       else "https://en.wiktionary.org/wiki/") + word
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        if self.on_close_cb:
            try:
                self.on_close_cb()
            except Exception:
                pass
        try:
            self.destroy()
        except tk.TclError:
            pass


class TranslationSettingsDialog(tk.Toplevel):
    PROVIDERS = [
        ("offline", "Только офлайн-словарь"),
        ("deepl", "DeepL API"),
        ("libre", "LibreTranslate"),
        ("mymemory", "MyMemory (ограниченный тариф)"),
    ]

    def __init__(self, master, palette: Palette, settings) -> None:
        super().__init__(master)
        self.palette = palette
        self.settings = settings
        self.saved = False
        self.title("Настройки перевода")
        self.configure(bg=palette.panel)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.geometry("560x470")
        self._build()

    def _build(self) -> None:
        palette = self.palette
        wrap = tk.Frame(self, bg=palette.panel, padx=24, pady=20)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="Онлайн-перевод", bg=palette.panel, fg=palette.text,
                 font=(SERIF, 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            wrap,
            text="Офлайн-словарь работает всегда. Для перевода фраз выберите сервис, "
                 "условия которого подходят для продажи: DeepL API или собственный "
                 "LibreTranslate. MyMemory — только для небольших объёмов.",
            bg=palette.panel, fg=palette.muted, font=(UI, 8), justify="left",
            wraplength=500, anchor="w",
        ).pack(fill="x", pady=(4, 12))

        current = str(getattr(self.settings, "translation_provider", "offline") or "offline")
        labels = [label for _, label in self.PROVIDERS]
        values = [key for key, _ in self.PROVIDERS]
        self.provider = ttk.Combobox(
            wrap, values=labels, state="readonly", style="Chitalka.TCombobox",
            font=(UI, 9),
        )
        self.provider.set(labels[values.index(current)] if current in values else labels[0])
        self.provider.pack(fill="x", pady=(0, 10))

        self.endpoint = self._entry(wrap, "Адрес API",
                                    str(getattr(self.settings, "translation_endpoint", "") or ""),
                                    "Для DeepL можно оставить пустым (free endpoint). "
                                    "Для LibreTranslate: https://ваш-сервер")
        self.api_key = self._entry(wrap, "API-ключ",
                                   str(getattr(self.settings, "translation_key", "") or ""),
                                   "Ключ DeepL или LibreTranslate. Хранится локально.")
        self.email = self._entry(wrap, "Email для MyMemory",
                                 str(getattr(self.settings, "translation_email", "") or ""),
                                 "Необязательно. Нужен только для увеличения лимита MyMemory.")

        actions = tk.Frame(wrap, bg=palette.panel)
        actions.pack(fill="x", pady=(16, 0))
        PillButton(actions, palette, "Отмена", self._cancel, kind="ghost",
                   height=36, bg=palette.panel).pack(side="right", padx=(8, 0))
        PillButton(actions, palette, "Сохранить", self._save, kind="primary",
                   height=36, bg=palette.panel).pack(side="right")

    def _entry(self, master, label: str, value: str, hint: str):
        palette = self.palette
        tk.Label(master, text=label.upper(), bg=palette.panel, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", pady=(2, 3))
        entry = tk.Entry(
            master, bg=palette.card, fg=palette.text, insertbackground=palette.text,
            relief="flat", bd=0, font=(UI, 9), highlightthickness=1,
            highlightbackground=palette.border, highlightcolor=palette.accent,
        )
        entry.insert(0, value)
        entry.pack(fill="x", ipady=7)
        tk.Label(master, text=hint, bg=palette.panel, fg=palette.dim,
                 font=(UI, 7), anchor="w", justify="left", wraplength=500).pack(
            fill="x", pady=(2, 5)
        )
        return entry

    def _save(self) -> None:
        labels = [label for _, label in self.PROVIDERS]
        values = [key for key, _ in self.PROVIDERS]
        index = labels.index(self.provider.get()) if self.provider.get() in labels else 0
        provider = values[index]
        endpoint = self.endpoint.get().strip()
        key = self.api_key.get().strip()
        if provider == "deepl" and not key:
            messagebox.showerror("Перевод", "Для DeepL укажите API-ключ.", parent=self)
            return
        if provider == "libre" and not endpoint:
            messagebox.showerror("Перевод", "Укажите адрес вашего LibreTranslate.",
                                 parent=self)
            return
        self.settings.translation_provider = provider
        self.settings.translation_endpoint = endpoint
        self.settings.translation_key = key
        self.settings.translation_email = self.email.get().strip()
        self.settings.save()
        self.saved = True
        self.destroy()

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
