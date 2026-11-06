"""Небольшие виджеты в книжном стиле: кнопки, чипы, поиск, обложки, диалоги."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict
from pathlib import Path
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageOps, ImageTk

from ..theme import Palette
from .icons import draw_icon

UI = "Segoe UI"


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str, palette: Palette) -> None:
        self.widget = widget
        self.text = text
        self.palette = palette
        self.tip: tk.Toplevel | None = None
        self._after = None
        if text:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after = self.widget.after(450, self._show)

    def _cancel(self) -> None:
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self) -> None:
        if self.tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=self.palette.border)
        label = tk.Label(
            tip, text=self.text, bg=self.palette.card, fg=self.palette.text,
            font=(UI, 8), padx=8, pady=4,
        )
        label.pack(padx=1, pady=1)
        tip.update_idletasks()
        width = tip.winfo_width()
        x = max(4, min(x - width // 2, self.widget.winfo_screenwidth() - width - 4))
        tip.wm_geometry(f"+{x}+{y}")
        self.tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class IconButton(tk.Canvas):
    def __init__(
        self,
        master,
        palette: Palette,
        icon: str,
        command: Callable | None = None,
        *,
        size: int = 34,
        icon_size: int = 17,
        tooltip: str = "",
        bg: str | None = None,
        fg: str | None = None,
        active: bool = False,
        radius: int = 9,
    ) -> None:
        self.palette = palette
        self._bg = bg or master["bg"]
        super().__init__(
            master, width=size, height=size, bg=self._bg, highlightthickness=0,
            bd=0, cursor="hand2",
        )
        self.icon = icon
        self.command = command
        self.size = size
        self.icon_size = icon_size
        self.radius = radius
        self.fg = fg or palette.muted
        self.active = active
        self._hover = False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()
        if tooltip:
            Tooltip(self, tooltip, palette)

    def set_active(self, active: bool) -> None:
        self.active = active
        self._draw()

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _click(self, event) -> None:
        if 0 <= event.x <= self.size and 0 <= event.y <= self.size and self.command:
            self.command()

    def _draw(self) -> None:
        self.delete("all")
        if self.active:
            round_rect(self, 1, 1, self.size - 1, self.size - 1, self.radius,
                       fill=self.palette.accent_soft, outline="")
        elif self._hover:
            round_rect(self, 1, 1, self.size - 1, self.size - 1, self.radius,
                       fill=self.palette.card_hover, outline="")
        color = self.palette.accent if self.active else (self.palette.text if self._hover else self.fg)
        draw_icon(self, self.icon, self.size / 2, self.size / 2, self.icon_size, color)


class PillButton(tk.Canvas):
    def __init__(
        self,
        master,
        palette: Palette,
        text: str,
        command: Callable | None = None,
        *,
        icon: str = "",
        kind: str = "primary",
        height: int = 36,
        font_size: int = 9,
        padx: int = 15,
        bg: str | None = None,
        tooltip: str = "",
    ) -> None:
        self.palette = palette
        self.text = text
        self.icon = icon
        self.kind = kind
        self.height = height
        self.padx = padx
        self.command = command
        self._bg = bg or master["bg"]
        self._font = tkfont.Font(family=UI, size=font_size, weight="bold")
        icon_size = 15 if icon else 0
        self._text_w = self._font.measure(text) if text else 0
        gap = 7 if icon and text else 0
        width = max(height, padx * 2 + icon_size + gap + self._text_w)
        super().__init__(
            master, width=width, height=height, bg=self._bg, highlightthickness=0,
            bd=0, cursor="hand2",
        )
        self.width = width
        self._hover = False
        self._enabled = True
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", self._on_configure)
        self._draw()
        if tooltip:
            Tooltip(self, tooltip, palette)

    def _on_configure(self, event) -> None:
        if abs(int(event.width) - int(self.width)) > 1:
            self.width = int(event.width)
            self._draw()

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        self.configure(cursor="hand2" if value else "arrow")
        self._draw()

    def set_text(self, text: str) -> None:
        self.text = text
        self._text_w = self._font.measure(text)
        icon_size = 15 if self.icon else 0
        gap = 7 if self.icon and text else 0
        self.width = max(self.height, self.padx * 2 + icon_size + gap + self._text_w)
        self.configure(width=self.width)
        self._draw()

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _click(self, event) -> None:
        if self._enabled and self.command:
            self.command()

    def _colors(self) -> tuple[str, str, str]:
        palette = self.palette
        if not self._enabled:
            return palette.chip, palette.dim, palette.border
        if self.kind == "primary":
            bg = palette.accent if not self._hover else palette.accent_text
            fg = palette.accent_text if not self._hover else palette.accent
            outline = palette.accent
            if self._hover:
                bg, fg, outline = palette.accent_soft, palette.accent, palette.accent
            return bg, fg, outline
        if self.kind == "soft":
            return (palette.accent_soft if self._hover else palette.chip,
                    palette.accent if self._hover else palette.text,
                    palette.accent if self._hover else palette.border)
        return (palette.card_hover if self._hover else self._bg,
                palette.text, palette.border)

    def _draw(self) -> None:
        self.delete("all")
        bg, fg, outline = self._colors()
        round_rect(self, 1, 1, self.width - 1, self.height - 1, self.height / 2,
                   fill=bg, outline=outline, width=1)
        icon_size = 15 if self.icon else 0
        gap = 7 if self.icon and self.text else 0
        total = icon_size + gap + self._text_w
        x = (self.width - total) / 2
        if self.icon:
            draw_icon(self, self.icon, x + icon_size / 2, self.height / 2, icon_size, fg, width=1.5)
            x += icon_size + gap
        if self.text:
            self.create_text(x, self.height / 2, text=self.text, anchor="w", fill=fg,
                             font=self._font)


class Chip(PillButton):
    def __init__(self, master, palette: Palette, text: str, command=None, *,
                 selected: bool = False, bg: str | None = None, count: int | None = None) -> None:
        self._selected = selected
        self._base_text = text
        self._count = count
        label = text if count is None else f"{text}  {count}"
        super().__init__(master, palette, label, command, kind="soft", height=30,
                         font_size=8, padx=12, bg=bg)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._draw()

    def set_count(self, count: int | None) -> None:
        self._count = count
        self.set_text(self._base_text if count is None else f"{self._base_text}  {count}")

    def _colors(self) -> tuple[str, str, str]:
        palette = self.palette
        if self._selected:
            return palette.accent, palette.accent_text, palette.accent
        if self._hover:
            return palette.card_hover, palette.text, palette.border_light
        return palette.chip, palette.chip_text, palette.border


class SearchEntry(tk.Frame):
    def __init__(self, master, palette: Palette, placeholder: str = "Поиск по книгам…",
                 width: int = 320, command: Callable[[str], None] | None = None) -> None:
        super().__init__(master, bg=palette.card, highlightthickness=1,
                         highlightbackground=palette.border, highlightcolor=palette.accent)
        self.palette = palette
        self.command = command
        self.placeholder = placeholder
        self.var = tk.StringVar()
        self._icon = tk.Canvas(self, width=34, height=38, bg=palette.card,
                               highlightthickness=0, bd=0)
        self._icon.pack(side="left")
        draw_icon(self._icon, "search", 17, 19, 16, palette.muted)
        self.entry = tk.Entry(
            self, textvariable=self.var, bg=palette.card, fg=palette.text,
            insertbackground=palette.text, relief="flat", bd=0,
            font=(UI, 10), highlightthickness=0,
        )
        self.entry.pack(side="left", fill="both", expand=True, pady=8)
        self._clear = tk.Canvas(self, width=30, height=38, bg=palette.card,
                                highlightthickness=0, bd=0, cursor="hand2")
        self._clear.pack(side="right")
        draw_icon(self._clear, "close", 15, 19, 11, palette.muted)
        self._clear.bind("<Button-1>", lambda _e: self.set(""))
        self._clear.pack_forget()
        self._placeholder = tk.Label(
            self, text=placeholder, bg=palette.card, fg=palette.dim,
            font=(UI, 10), cursor="xterm",
        )
        self._placeholder.place(x=34, rely=0.5, anchor="w")
        self._placeholder.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.var.trace_add("write", lambda *_: self._changed())
        self.configure(width=width, height=40)
        self.pack_propagate(False)
        self._changed()

    def _focus_in(self, _event=None) -> None:
        self.configure(highlightbackground=self.palette.accent)

    def _focus_out(self, _event=None) -> None:
        self.configure(highlightbackground=self.palette.border)

    def _changed(self) -> None:
        value = self.var.get()
        if value:
            self._placeholder.place_forget()
            self._clear.pack(side="right")
        else:
            self._placeholder.place(x=34, rely=0.5, anchor="w")
            self._clear.pack_forget()
        if self.command:
            self.command(value)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)
        self.entry.focus_set()
        self.entry.icursor("end")

    def focus(self) -> None:
        self.entry.focus_set()


class ScrollFrame(tk.Frame):
    def __init__(self, master, palette: Palette, bg: str | None = None) -> None:
        bg = bg or palette.bg
        super().__init__(master, bg=bg)
        self.palette = palette
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            style="Chitalka.Vertical.TScrollbar",
        )
        self.scrollbar.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_wheel, add="+")
        self._wheel_target = None

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)

    def _inside(self, event) -> bool:
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_wheel(self, event) -> None:
        if not self._inside(event):
            return
        if getattr(event, "num", 0) == 4:
            delta = -1
        elif getattr(event, "num", 0) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)

    def yview(self) -> float:
        return float(self.canvas.yview()[0])

    def restore(self, fraction: float) -> None:
        self.canvas.yview_moveto(max(0.0, min(1.0, fraction)))


class CoverCache:
    def __init__(self) -> None:
        self._cache: "OrderedDict[tuple, ImageTk.PhotoImage]" = OrderedDict()
        self._limit = 220

    def get(self, path: str | Path, size: tuple[int, int], radius: int = 8) -> ImageTk.PhotoImage | None:
        key = (str(path), int(size[0]), int(size[1]), int(radius))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            return None
        image = ImageOps.fit(image, size, Image.LANCZOS)
        image = image.convert("RGBA")
        if radius:
            mask = Image.new("L", size, 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
            image.putalpha(mask)
        photo = ImageTk.PhotoImage(image)
        self._cache[key] = photo
        if len(self._cache) > self._limit:
            self._cache.popitem(last=False)
        return photo


class Slider(tk.Canvas):
    """Аккуратный ползунок без системной темы."""

    def __init__(self, master, palette: Palette, *, minimum: float = 0.0,
                 maximum: float = 100.0, value: float = 0.0, step: float = 1.0,
                 command: Callable[[float], None] | None = None,
                 width: int = 220, height: int = 24, bg: str | None = None) -> None:
        self.palette = palette
        super().__init__(master, width=width, height=height, bg=bg or master["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.step = float(step) if step else 0.0
        self.command = command
        self.width = width
        self.height = height
        self.value = float(value)
        self._drag = False
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._on_configure)
        self._draw()

    def _on_configure(self, event) -> None:
        self.width = event.width
        self._draw()

    def _fraction(self, x: float) -> float:
        pad = 9
        usable = max(1, self.width - pad * 2)
        return max(0.0, min(1.0, (x - pad) / usable))

    def _on_click(self, event) -> None:
        self._drag = True
        self._set_from_x(event.x)

    def _on_drag(self, event) -> None:
        if self._drag:
            self._set_from_x(event.x)

    def _release(self, _event=None) -> None:
        self._drag = False

    def _set_from_x(self, x: float) -> None:
        raw = self.minimum + self._fraction(x) * (self.maximum - self.minimum)
        if self.step:
            raw = round(raw / self.step) * self.step
        self.set(raw, notify=True)

    def set(self, value: float, notify: bool = False) -> None:
        self.value = max(self.minimum, min(self.maximum, float(value)))
        self._draw()
        if notify and self.command:
            self.command(self.value)

    def _draw(self) -> None:
        self.delete("all")
        pad = 9
        y = self.height / 2
        ratio = 0.0
        if self.maximum > self.minimum:
            ratio = (self.value - self.minimum) / (self.maximum - self.minimum)
        x = pad + ratio * max(1, self.width - pad * 2)
        palette = self.palette
        self.create_line(pad, y, self.width - pad, y, fill=palette.border_light,
                         width=3, capstyle="round")
        self.create_line(pad, y, max(pad, x), y, fill=palette.accent,
                         width=3, capstyle="round")
        self.create_oval(x - 6, y - 6, x + 6, y + 6, fill=palette.accent,
                         outline=palette.panel, width=2)


class ProgressBar(tk.Canvas):
    def __init__(self, master, width: int = 160, height: int = 4,
                 palette: Palette | None = None, bg: str | None = None) -> None:
        self.palette = palette
        super().__init__(master, width=width, height=height, bg=bg or master["bg"],
                         highlightthickness=0, bd=0)
        self.width = width
        self.height = height
        self._value = 0.0

    def set(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        palette = self.palette
        track = palette.border if palette else "#333333"
        fill = palette.accent if palette else "#c87941"
        self.create_line(0, self.height / 2, self.width, self.height / 2,
                         fill=track, width=self.height, capstyle="round")
        if self._value > 0:
            end = max(self.height, self.width * self._value / 100)
            self.create_line(0, self.height / 2, end, self.height / 2,
                             fill=fill, width=self.height, capstyle="round")


class Divider(tk.Frame):
    def __init__(self, master, palette: Palette, **kwargs) -> None:
        super().__init__(master, bg=palette.border, height=1, **kwargs)


def configure_ttk(root: tk.Misc, palette: Palette) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    try:
        root.update_idletasks()
    except tk.TclError:
        pass
    style.configure(
        "Chitalka.Vertical.TScrollbar",
        background=palette.scroll,
        troughcolor=palette.bg,
        bordercolor=palette.bg,
        arrowcolor=palette.bg,
        darkcolor=palette.scroll,
        lightcolor=palette.scroll,
        width=9,
        relief="flat",
    )
    style.map("Chitalka.Vertical.TScrollbar", background=[("active", palette.muted)])
    style.configure(
        "Chitalka.TCombobox",
        fieldbackground=palette.card,
        background=palette.card,
        foreground=palette.text,
        arrowcolor=palette.muted,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        padding=(10, 7),
        relief="flat",
    )
    style.map(
        "Chitalka.TCombobox",
        fieldbackground=[("readonly", palette.card)],
        foreground=[("readonly", palette.text)],
        selectbackground=[("readonly", palette.card)],
        selectforeground=[("readonly", palette.text)],
    )
    root.option_add("*TCombobox*Listbox.background", palette.card)
    root.option_add("*TCombobox*Listbox.foreground", palette.text)
    root.option_add("*TCombobox*Listbox.selectBackground", palette.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", palette.accent_text)
    root.option_add("*TCombobox*Listbox.font", (UI, 9))


def ask_text(parent, palette: Palette, title: str, label: str,
             initial: str = "", multiline: bool = False) -> str | None:
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=palette.panel)
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.grab_set()
    frame = tk.Frame(dialog, bg=palette.panel, padx=22, pady=18)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=title, bg=palette.panel, fg=palette.text,
             font=("Georgia", 14, "bold"), anchor="w").pack(fill="x")
    if label:
        tk.Label(frame, text=label, bg=palette.panel, fg=palette.muted,
                 font=(UI, 9), anchor="w", justify="left").pack(fill="x", pady=(6, 10))
    if multiline:
        entry = tk.Text(frame, width=36, height=4, bg=palette.card, fg=palette.text,
                        insertbackground=palette.text, relief="flat", padx=8, pady=6,
                        font=(UI, 10), wrap="word", highlightthickness=1,
                        highlightbackground=palette.border, highlightcolor=palette.accent)
    else:
        entry = tk.Entry(frame, width=38, bg=palette.card, fg=palette.text,
                         insertbackground=palette.text, relief="flat", font=(UI, 10),
                         highlightthickness=1, highlightbackground=palette.border,
                         highlightcolor=palette.accent)
        entry.insert(0, initial)
        entry.select_range(0, "end")
    entry.pack(fill="x", ipady=7)

    result: dict[str, str | None] = {"value": None}
    buttons = tk.Frame(frame, bg=palette.panel)
    buttons.pack(fill="x", pady=(16, 0))

    def close(value: str | None) -> None:
        result["value"] = value
        dialog.destroy()

    PillButton(buttons, palette, "Отмена", lambda: close(None), kind="ghost",
               height=34, bg=palette.panel).pack(side="right", padx=(8, 0))
    PillButton(buttons, palette, "Сохранить", lambda: close(_value()), kind="primary",
               height=34, bg=palette.panel).pack(side="right")

    def _value() -> str:
        if multiline:
            return entry.get("1.0", "end").strip()
        return entry.get().strip()

    dialog.bind("<Escape>", lambda _e: close(None))
    if not multiline:
        entry.bind("<Return>", lambda _e: close(_value()))
    entry.focus_set()
    dialog.update_idletasks()
    width = dialog.winfo_width()
    height = dialog.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
    parent.wait_window(dialog)
    return result["value"]
