"""Окно статистики чтения: время, страницы, серия дней и цель на месяц."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from ..config import APP_NAME, Settings, fit_geometry
from ..db import LibraryDB
from ..theme import Palette
from .icons import draw_icon
from .widgets import (
    CoverCache,
    IconButton,
    PillButton,
    ProgressBar,
    ScrollFrame,
    ask_text,
    round_rect,
)

UI = "Segoe UI"
SERIF = "Georgia"
MONTHS = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def human_time(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    if seconds <= 0:
        return "0 мин"
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def plural(number: int, one: str, few: str, many: str) -> str:
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


class StatsWindow(tk.Toplevel):
    def __init__(self, master, settings: Settings, db: LibraryDB,
                 palette: Palette, cover_cache: CoverCache) -> None:
        super().__init__(master)
        self.settings = settings
        self.db = db
        self.palette = palette
        self.cover_cache = cover_cache
        self._stats: dict = {}
        self._chart_width = 840
        self._resize_job = None
        self.title(f"Статистика чтения — {APP_NAME}")
        self.configure(bg=palette.bg)
        self.minsize(760, 600)
        try:
            fit_geometry(self, "1040x760+160+70", 760, 600)
        except tk.TclError:
            self.geometry("1040x760")
        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(80, self.refresh)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        palette = self.palette
        header = tk.Frame(self, bg=palette.bg)
        header.pack(fill="x", padx=30, pady=(22, 10))
        title_box = tk.Frame(header, bg=palette.bg)
        title_box.pack(side="left")
        tk.Label(title_box, text="Статистика чтения", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 24, "bold"), anchor="w").pack(anchor="w")
        tk.Label(title_box, text="Активное время в читалке, страницы и серия дней",
                 bg=palette.bg, fg=palette.muted, font=(UI, 9), anchor="w").pack(anchor="w")
        IconButton(header, palette, "close", self.destroy, size=34,
                   tooltip="Закрыть").pack(side="right")

        self.scroll = ScrollFrame(self, palette, bg=palette.bg)
        self.scroll.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        body = self.scroll.inner

        cards = tk.Frame(body, bg=palette.bg)
        cards.pack(fill="x", padx=30, pady=(0, 8))
        for column in range(4):
            cards.grid_columnconfigure(column, weight=1, uniform="cards")
        self.today_value, self.today_sub = self._card(cards, 0, "Сегодня", "0 мин")
        self.month_value, self.month_sub = self._card(cards, 1, "За месяц", "0 мин")
        self.total_value, self.total_sub = self._card(cards, 2, "Всего", "0 мин")
        self.streak_value, self.streak_sub = self._card(cards, 3, "Серия", "0 дней")

        goal = tk.Frame(body, bg=palette.panel)
        goal.pack(fill="x", padx=30, pady=(8, 10))
        goal_head = tk.Frame(goal, bg=palette.panel)
        goal_head.pack(fill="x", padx=18, pady=(14, 4))
        self.goal_title = tk.Label(goal_head, text="Цель на месяц", bg=palette.panel,
                                   fg=palette.text, font=(SERIF, 12, "bold"), anchor="w")
        self.goal_title.pack(side="left")
        self.goal_button = PillButton(goal_head, palette, "Изменить", self._edit_goal,
                                      kind="ghost", height=30, font_size=8,
                                      bg=palette.panel)
        self.goal_button.pack(side="right")
        self.goal_value = tk.Label(goal, text="0 из 600 мин", bg=palette.panel,
                                   fg=palette.muted, font=(UI, 9), anchor="w")
        self.goal_value.pack(fill="x", padx=18)
        self.goal_bar = ProgressBar(goal, width=400, height=5, palette=palette,
                                    bg=palette.panel)
        self.goal_bar.pack(fill="x", padx=18, pady=(6, 16))

        chart_box = tk.Frame(body, bg=palette.bg)
        chart_box.pack(fill="x", padx=30, pady=(4, 8))
        chart_head = tk.Frame(chart_box, bg=palette.bg)
        chart_head.pack(fill="x")
        tk.Label(chart_head, text="Последние 30 дней", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 13, "bold"), anchor="w").pack(side="left")
        self.chart_hint = tk.Label(chart_head, text="", bg=palette.bg, fg=palette.muted,
                                   font=(UI, 8), anchor="e")
        self.chart_hint.pack(side="right")
        self.chart = tk.Canvas(chart_box, height=250, bg=palette.bg,
                               highlightthickness=0, bd=0)
        self.chart.pack(fill="x", pady=(8, 0))
        self.chart.bind("<Configure>", self._on_chart_resize)

        top_box = tk.Frame(body, bg=palette.bg)
        top_box.pack(fill="x", padx=30, pady=(10, 24))
        tk.Label(top_box, text="Больше всего времени", bg=palette.bg, fg=palette.text,
                 font=(SERIF, 13, "bold"), anchor="w").pack(fill="x")
        self.top_body = tk.Frame(top_box, bg=palette.bg)
        self.top_body.pack(fill="x", pady=(6, 0))

    def _card(self, parent, column: int, title: str, value: str) -> tuple[tk.Label, tk.Label]:
        palette = self.palette
        card = tk.Frame(parent, bg=palette.card)
        card.grid(row=0, column=column, sticky="nsew",
                  padx=(0 if column == 0 else 8, 0), pady=2)
        tk.Label(card, text=title.upper(), bg=palette.card, fg=palette.dim,
                 font=(UI, 7, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        value_label = tk.Label(card, text=value, bg=palette.card, fg=palette.text,
                               font=(SERIF, 20, "bold"), anchor="w")
        value_label.pack(fill="x", padx=16)
        sub = tk.Label(card, text="", bg=palette.card, fg=palette.muted,
                       font=(UI, 8), anchor="w")
        sub.pack(fill="x", padx=16, pady=(2, 14))
        return value_label, sub

    # ------------------------------------------------------------------ данные
    def refresh(self) -> None:
        self._stats = self.db.stats_overview(self.settings.monthly_goal_minutes)
        stats = self._stats
        self.today_value.configure(text=human_time(stats["today_seconds"]))
        pages = stats["today_pages"]
        self.today_sub.configure(
            text=f"{pages} {plural(pages, 'страница', 'страницы', 'страниц')}"
        )
        self.month_value.configure(text=human_time(stats["month_seconds"]))
        pages = stats["month_pages"]
        self.month_sub.configure(
            text=f"{pages} {plural(pages, 'страница', 'страницы', 'страниц')}"
        )
        self.total_value.configure(text=human_time(stats["total_seconds"]))
        days = stats["reading_days"]
        self.total_sub.configure(
            text=f"{days} {plural(days, 'день', 'дня', 'дней')} чтения"
        )
        streak = stats["streak"]
        self.streak_value.configure(text=f"{streak}")
        self.streak_sub.configure(
            text=plural(streak, "день подряд", "дня подряд", "дней подряд")
        )
        goal = stats["goal_minutes"]
        month_number = date.today().month
        self.goal_title.configure(text=f"Цель на {MONTHS[month_number]}")
        minutes = stats["month_seconds"] // 60
        self.goal_value.configure(
            text=f"{minutes} из {goal} мин  ·  {stats['goal_percent']:.0f}%"
        )
        self.goal_bar.set(stats["goal_percent"])
        if not stats["total_seconds"]:
            self.chart_hint.configure(text="Пока нет данных — откройте книгу и читайте")
        else:
            self.chart_hint.configure(text=f"Всего: {human_time(stats['total_seconds'])}")
        self._draw_chart()
        self._draw_top()

    def _on_chart_resize(self, event) -> None:
        self._chart_width = max(300, event.width)
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(80, self._draw_chart)

    def _draw_chart(self) -> None:
        if not self._stats:
            return
        canvas = self.chart
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(180, canvas.winfo_height())
        palette = self.palette
        left, right = 38, 14
        top, bottom = 16, 26
        plot_w = width - left - right
        plot_h = height - top - bottom

        daily = self._stats["daily"]
        minutes = [item["seconds"] / 60.0 for item in daily]
        max_value = max(30.0, max(minutes) * 1.15 if minutes else 30.0)
        steps = 3
        for step in range(steps + 1):
            value = max_value * step / steps
            y = top + plot_h - plot_h * (step / steps)
            if step:
                canvas.create_line(left, y, width - right, y,
                                   fill=palette.border, dash=(2, 4))
            else:
                canvas.create_line(left, y, width - right, y, fill=palette.border)
            canvas.create_text(left - 8, y, text=f"{value:.0f}",
                               anchor="e", fill=palette.dim, font=(UI, 7))

        gap = 3
        bar_w = max(3.0, (plot_w - gap * (len(daily) - 1)) / max(1, len(daily)))
        for index, item in enumerate(daily):
            value = item["seconds"] / 60.0
            x = left + index * (bar_w + gap)
            bar_h = 0 if value <= 0 else max(2.0, plot_h * value / max_value)
            y = top + plot_h - bar_h
            is_today = index == len(daily) - 1
            canvas.create_rectangle(
                x, y, x + bar_w, top + plot_h,
                fill=palette.accent if is_today else palette.accent_soft,
                outline="",
            )
        for index in range(0, len(daily), 5):
            x = left + index * (bar_w + gap) + bar_w / 2
            day = daily[index]["date"][8:]
            canvas.create_text(x, top + plot_h + 10, text=day,
                               fill=palette.dim, font=(UI, 7))
        canvas.create_text(width - right, height - 2, text="минуты",
                           anchor="se", fill=palette.dim, font=(UI, 7))

    def _draw_top(self) -> None:
        for child in self.top_body.winfo_children():
            child.destroy()
        rows = self._stats.get("top", [])
        if not rows:
            tk.Label(self.top_body, text="Здесь появятся книги, которые вы читаете.",
                     bg=self.palette.bg, fg=self.palette.muted,
                     font=(UI, 9), anchor="w").pack(fill="x", pady=8)
            return
        for row in rows:
            item = tk.Frame(self.top_body, bg=self.palette.card)
            item.pack(fill="x", pady=3)
            cover = tk.Label(item, bg=self.palette.card, bd=0)
            cover.pack(side="left", padx=10, pady=8)
            photo = self.cover_cache.get(row["cover"], (34, 50), radius=4)
            if photo:
                cover.configure(image=photo)
                cover._photo = photo  # type: ignore[attr-defined]
            else:
                cover.configure(text="", width=3, height=2)
            text = tk.Frame(item, bg=self.palette.card)
            text.pack(side="left", fill="x", expand=True, pady=8)
            tk.Label(text, text=row["title"], bg=self.palette.card, fg=self.palette.text,
                     font=(SERIF, 10, "bold"), anchor="w").pack(fill="x")
            tk.Label(text, text=row["author"] or "Автор неизвестен", bg=self.palette.card,
                     fg=self.palette.muted, font=(UI, 8), anchor="w").pack(fill="x")
            tk.Label(item, text=human_time(row["seconds"]), bg=self.palette.card,
                     fg=self.palette.accent, font=(UI, 9, "bold"), anchor="e").pack(
                side="right", padx=(8, 16)
            )
            tk.Label(item, text=f"{row['pages']} стр.", bg=self.palette.card,
                     fg=self.palette.dim, font=(UI, 7), anchor="e").pack(
                side="right", padx=4
            )

    def _edit_goal(self) -> None:
        value = ask_text(
            self, self.palette, "Цель на месяц",
            "Сколько минут в месяц вы хотите читать?",
            initial=str(self.settings.monthly_goal_minutes),
        )
        if value is None:
            return
        try:
            minutes = int(value.strip())
        except ValueError:
            return
        minutes = max(30, min(30000, minutes))
        self.settings.monthly_goal_minutes = minutes
        self.settings.save()
        self.refresh()
