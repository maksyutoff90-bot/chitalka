"""Точка входа «Читалки».

Запуск:
    python main.py
    python main.py --selftest
    python main.py --shot data/shot.png 5000
    python main.py --shot data/reader.png 6000 --book "Пиковая дама"
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _report_error(exc: BaseException, dialog: bool = True) -> None:
    from datetime import datetime

    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from chitalka.config import DATA_DIR

        log = DATA_DIR / "crash.log"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}\n")
    except Exception:
        pass
    if not dialog:
        print(text, file=sys.stderr)
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Читалка — ошибка запуска",
            f"{exc}\n\nПодробности записаны в data/crash.log",
        )
        root.destroy()
    except Exception:
        print(text, file=sys.stderr)


def _setup_logging() -> None:
    try:
        from chitalka.config import DATA_DIR

        logging.basicConfig(
            filename=str(DATA_DIR / "chitalka.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            encoding="utf-8",
        )
    except Exception:
        pass


def _diagnostics() -> int | None:
    args = sys.argv[1:]
    if "--selftest" in args:
        from chitalka.diagnostics import run_selftest

        return run_selftest()
    if "--repair" in args:
        from chitalka.diagnostics import run_repair

        return run_repair()
    if "--shot" in args:
        from chitalka.diagnostics import screenshot_from_argv

        action = screenshot_from_argv(sys.argv)
        if action:
            return action()
    return None


def main() -> int:
    _setup_logging()
    try:
        result = _diagnostics()
    except Exception as exc:  # noqa: BLE001
        _report_error(exc, dialog=False)
        return 1
    if result is not None:
        return result
    try:
        from chitalka.ui.library import LibraryApp
    except ImportError as exc:
        _report_error(
            ImportError(f"{exc}\nУстановите зависимости: pip install -r requirements.txt")
        )
        return 1
    try:
        app = LibraryApp()
        app.mainloop()
    except Exception as exc:  # noqa: BLE001
        _report_error(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
