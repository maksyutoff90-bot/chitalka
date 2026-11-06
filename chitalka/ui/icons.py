"""Векторные иконки, нарисованные на Canvas (без внешних файлов)."""

from __future__ import annotations

import tkinter as tk


def _line(canvas, *points, color, width=1.6, tags=()):
    return canvas.create_line(*points, fill=color, width=width, capstyle="round", joinstyle="round", tags=tags)


def draw_icon(canvas: tk.Canvas, name: str, cx: float, cy: float, size: float,
              color: str, width: float = 1.6, tags=()) -> None:
    s = size / 2.0
    left, right = cx - s, cx + s
    top, bottom = cy - s, cy + s
    if name == "book":
        canvas.create_polygon(
            left, top + 2, cx - 1, top + 4, cx - 1, bottom - 1, left, bottom - 3,
            outline=color, fill="", width=width, joinstyle="round", tags=tags,
        )
        canvas.create_polygon(
            right, top + 2, cx + 1, top + 4, cx + 1, bottom - 1, right, bottom - 3,
            outline=color, fill="", width=width, joinstyle="round", tags=tags,
        )
        _line(canvas, cx, top + 4, cx, bottom - 1, color=color, width=width, tags=tags)
    elif name == "library":
        _line(canvas, left + 1, bottom, left + 1, top + 3, color=color, width=width, tags=tags)
        _line(canvas, cx - 2, bottom, cx - 2, top, color=color, width=width, tags=tags)
        _line(canvas, right - 1, bottom, right - 1, top + 4, color=color, width=width, tags=tags)
        _line(canvas, left - 1, bottom, right + 1, bottom, color=color, width=width, tags=tags)
    elif name == "bookmark":
        canvas.create_polygon(
            left + 4, top + 1, right - 4, top + 1, right - 4, bottom,
            cx, bottom - 5, left + 4, bottom,
            outline=color, fill="", width=width, joinstyle="round", tags=tags,
        )
    elif name == "search":
        canvas.create_oval(left + 1, top + 1, cx + 3, cy + 3, outline=color, width=width, tags=tags)
        _line(canvas, cx + 2, cy + 2, right, bottom, color=color, width=width, tags=tags)
    elif name == "settings":
        for offset, knob in ((-4, -3), (0, 3), (4, 0)):
            yy = cy + offset
            _line(canvas, left, yy, right, yy, color=color, width=width, tags=tags)
            canvas.create_oval(cx + knob - 2, yy - 2, cx + knob + 2, yy + 2,
                               fill=color, outline=color, tags=tags)
    elif name == "grid":
        cell = size * 0.36
        gap = size * 0.12
        for dx in (-1, 1):
            for dy in (-1, 1):
                x = cx + dx * (cell / 2 + gap / 2)
                y = cy + dy * (cell / 2 + gap / 2)
                canvas.create_rectangle(x - cell / 2, y - cell / 2, x + cell / 2, y + cell / 2,
                                        fill=color, outline=color, tags=tags)
    elif name == "list":
        for offset in (-5, 0, 5):
            yy = cy + offset
            canvas.create_oval(left + 1, yy - 1, left + 3, yy + 1, fill=color, outline=color, tags=tags)
            _line(canvas, left + 6, yy, right, yy, color=color, width=width, tags=tags)
    elif name == "plus":
        _line(canvas, cx, top + 2, cx, bottom - 2, color=color, width=width + 0.4, tags=tags)
        _line(canvas, left + 2, cy, right - 2, cy, color=color, width=width + 0.4, tags=tags)
    elif name == "folder":
        canvas.create_polygon(
            left + 1, top + 5, cx - 2, top + 5, cx + 1, top + 8, right - 1, top + 8,
            right - 1, bottom - 1, left + 1, bottom - 1,
            outline=color, fill="", width=width, joinstyle="round", tags=tags,
        )
    elif name == "heart":
        canvas.create_text(cx, cy + 1, text="♥", fill=color,
                           font=("Segoe UI Symbol", -int(size), "bold"), tags=tags)
    elif name == "star":
        canvas.create_text(cx, cy, text="★", fill=color,
                           font=("Segoe UI Symbol", -int(size), "bold"), tags=tags)
    elif name == "clock":
        canvas.create_oval(left + 1, top + 1, right - 1, bottom - 1, outline=color, width=width, tags=tags)
        _line(canvas, cx, cy - 4, cx, cy + 1, color=color, width=width, tags=tags)
        _line(canvas, cx, cy + 1, cx + 4, cy + 3, color=color, width=width, tags=tags)
    elif name == "check":
        _line(canvas, left + 2, cy, cx - 1, bottom - 3, color=color, width=width + 0.3, tags=tags)
        _line(canvas, cx - 1, bottom - 3, right - 1, top + 3, color=color, width=width + 0.3, tags=tags)
    elif name == "chevron_left":
        _line(canvas, cx + 3, top + 3, cx - 3, cy, color=color, width=width, tags=tags)
        _line(canvas, cx - 3, cy, cx + 3, bottom - 3, color=color, width=width, tags=tags)
    elif name == "chevron_right":
        _line(canvas, cx - 3, top + 3, cx + 3, cy, color=color, width=width, tags=tags)
        _line(canvas, cx + 3, cy, cx - 3, bottom - 3, color=color, width=width, tags=tags)
    elif name == "chevron_down":
        _line(canvas, left + 3, cy - 2, cx, cy + 3, color=color, width=width, tags=tags)
        _line(canvas, cx, cy + 3, right - 3, cy - 2, color=color, width=width, tags=tags)
    elif name == "more":
        for offset in (-5, 0, 5):
            canvas.create_oval(cx + offset - 1.4, cy - 1.4, cx + offset + 1.4, cy + 1.4,
                               fill=color, outline=color, tags=tags)
    elif name == "close":
        _line(canvas, left + 4, top + 4, right - 4, bottom - 4, color=color, width=width, tags=tags)
        _line(canvas, right - 4, top + 4, left + 4, bottom - 4, color=color, width=width, tags=tags)
    elif name == "arrow_left":
        _line(canvas, right - 2, cy, left + 3, cy, color=color, width=width, tags=tags)
        _line(canvas, left + 3, cy, left + 9, cy - 6, color=color, width=width, tags=tags)
        _line(canvas, left + 3, cy, left + 9, cy + 6, color=color, width=width, tags=tags)
    elif name == "arrow_right":
        _line(canvas, left + 2, cy, right - 3, cy, color=color, width=width, tags=tags)
        _line(canvas, right - 3, cy, right - 9, cy - 6, color=color, width=width, tags=tags)
        _line(canvas, right - 3, cy, right - 9, cy + 6, color=color, width=width, tags=tags)
    elif name == "fullscreen":
        for x1, y1, dx, dy in ((left + 1, top + 1, 1, 1), (right - 1, top + 1, -1, 1),
                               (left + 1, bottom - 1, 1, -1), (right - 1, bottom - 1, -1, -1)):
            _line(canvas, x1, y1, x1 + dx * 5, y1, color=color, width=width, tags=tags)
            _line(canvas, x1, y1, x1, y1 + dy * 5, color=color, width=width, tags=tags)
    elif name == "type":
        canvas.create_text(cx, cy + 1, text="Aa", fill=color,
                           font=("Georgia", -int(size * 0.95), "bold"), tags=tags)
    elif name == "trash":
        _line(canvas, left + 3, top + 3, right - 3, top + 3, color=color, width=width, tags=tags)
        _line(canvas, cx - 4, top + 1, cx + 4, top + 1, color=color, width=width, tags=tags)
        canvas.create_polygon(left + 4, top + 3, right - 4, top + 3, right - 6, bottom - 1,
                              left + 6, bottom - 1, outline=color, fill="", width=width,
                              joinstyle="round", tags=tags)
        _line(canvas, cx - 2, top + 6, cx - 2, bottom - 3, color=color, width=1, tags=tags)
        _line(canvas, cx + 2, top + 6, cx + 2, bottom - 3, color=color, width=1, tags=tags)
    elif name == "info":
        canvas.create_oval(left + 1, top + 1, right - 1, bottom - 1, outline=color, width=width, tags=tags)
        canvas.create_oval(cx - 1, top + 4, cx + 1, top + 6, fill=color, outline=color, tags=tags)
        _line(canvas, cx, top + 8, cx, bottom - 4, color=color, width=width, tags=tags)
    elif name == "external":
        _line(canvas, left + 2, bottom - 2, left + 2, top + 2, color=color, width=width, tags=tags)
        _line(canvas, left + 2, top + 2, cx + 2, top + 2, color=color, width=width, tags=tags)
        _line(canvas, cx - 1, cy - 1, right - 1, top + 1, color=color, width=width, tags=tags)
        _line(canvas, right - 6, top + 1, right - 1, top + 1, color=color, width=width, tags=tags)
        _line(canvas, right - 1, top + 1, right - 1, top + 6, color=color, width=width, tags=tags)
    elif name == "sun":
        canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, outline=color, width=width, tags=tags)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            _line(canvas, cx + dx * 7, cy + dy * 7, cx + dx * 9, cy + dy * 9, color=color, width=width, tags=tags)
    elif name == "moon":
        canvas.create_oval(left + 2, top + 1, right - 2, bottom - 1, outline=color, width=width, tags=tags)
        canvas.create_oval(left + 6, top - 2, right + 3, bottom - 6, fill=canvas["bg"], outline=canvas["bg"], tags=tags)
    elif name == "note":
        canvas.create_polygon(
            left + 3, top + 1, right - 7, top + 1, right - 1, top + 7,
            right - 1, bottom - 1, left + 3, bottom - 1,
            outline=color, fill="", width=width, joinstyle="round", tags=tags,
        )
        _line(canvas, right - 7, top + 1, right - 7, top + 7, color=color, width=width, tags=tags)
        _line(canvas, right - 7, top + 7, right - 1, top + 7, color=color, width=width, tags=tags)
        for y in (top + 11, top + 14, top + 17):
            _line(canvas, left + 6, y, right - 5, y, color=color, width=1, tags=tags)
    elif name == "globe":
        canvas.create_oval(left + 1, top + 1, right - 1, bottom - 1,
                           outline=color, width=width, tags=tags)
        canvas.create_oval(cx - size * 0.18, top + 1, cx + size * 0.18, bottom - 1,
                           outline=color, width=width * 0.8, tags=tags)
        _line(canvas, left + 3, cy, right - 3, cy, color=color, width=width * 0.8, tags=tags)
        _line(canvas, left + 2, cy - size * 0.27, right - 2, cy - size * 0.27,
              color=color, width=width * 0.7, tags=tags)
        _line(canvas, left + 2, cy + size * 0.27, right - 2, cy + size * 0.27,
              color=color, width=width * 0.7, tags=tags)
    elif name == "chart":
        base = bottom - 2
        for offset, height in ((-7, 5), (-2, 9), (3, 7), (8, 12)):
            left_x = cx + offset - 2
            canvas.create_rectangle(left_x, base - height, left_x + 4, base,
                                    fill=color, outline=color, tags=tags)
        _line(canvas, left - 1, base + 2, right + 1, base + 2,
              color=color, width=width, tags=tags)
    elif name == "refresh":
        canvas.create_arc(left + 2, top + 2, right - 2, bottom - 2, start=35, extent=285,
                          style="arc", outline=color, width=width, tags=tags)
        _line(canvas, right - 2, top + 4, right - 2, top + 9, color=color, width=width, tags=tags)
        _line(canvas, right - 2, top + 9, right - 7, top + 9, color=color, width=width, tags=tags)
    elif name == "toc":
        for offset, indent in ((-5, 0), (0, 5), (5, 2)):
            yy = cy + offset
            _line(canvas, left + 1, yy, left + 1 + 4 + indent, yy, color=color, width=width, tags=tags)
            _line(canvas, left + 9 + indent, yy, right, yy, color=color, width=1, tags=tags)
    else:
        canvas.create_oval(left + 2, top + 2, right - 2, bottom - 2, outline=color, width=width, tags=tags)
