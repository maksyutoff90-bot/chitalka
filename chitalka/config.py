"""Пути, настройки и небольшие утилиты приложения «Читалка».

Данные хранятся рядом с программой (папка data). Если программа установлена в
защищённую папку и запись невозможна, используется %APPDATA%\\Chitalka.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Any

APP_NAME = "Читалка"
APP_TAGLINE = "библиотека и чтение"
APP_VERSION = "1.0.0"


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _fallback_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Chitalka"
    return Path.home() / ".chitalka"


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


ROOT_DIR = _base_dir()
BUNDLED_DICT_ARCHIVE = ROOT_DIR / "data" / "dictionaries" / "freedict.sqlite.xz"
DATA_DIR = ROOT_DIR / "data"
if not _is_writable(DATA_DIR):
    DATA_DIR = _fallback_dir()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

BOOKS_DIR = DATA_DIR / "books"
COVERS_DIR = DATA_DIR / "covers"
IMAGES_DIR = DATA_DIR / "images"
OPDS_CACHE_DIR = DATA_DIR / "opds_covers"
DICT_DIR = DATA_DIR / "dictionaries"
OFFLINE_DICT_PATH = DICT_DIR / "freedict.sqlite"
OFFLINE_DICT_ARCHIVE = DICT_DIR / "freedict.sqlite.xz"
DB_PATH = DATA_DIR / "library.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
CRASH_LOG = DATA_DIR / "crash.log"

for _folder in (BOOKS_DIR, COVERS_DIR, IMAGES_DIR, OPDS_CACHE_DIR, DICT_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

APP_ICON = DATA_DIR / "app.ico"


# ------------------------------------------------------------------ настройки
@dataclass
class Settings:
    """Пользовательские настройки. Все поля сериализуются в settings.json."""

    ui_theme: str = "dark"          # dark | light
    view: str = "grid"              # grid | list
    sort: str = "recent"            # recent | added | title | author | year | progress
    filter_format: str = "all"      # all | fb2 | epub | pdf | txt | ...
    reader_theme: str = "paper"     # paper | sepia | graphite | night
    font_family: str = "Georgia"
    font_size: int = 19             # в пикселях
    line_spacing: float = 1.55
    page_margin: int = 54
    justify: bool = True
    show_header: bool = True
    show_footer: bool = True
    chapter_page_break: bool = True
    monthly_goal_minutes: int = 600
    window_geometry: str = "1440x900+40+30"
    reader_geometry: str = "1140x850+80+20"
    folders: list[str] = None       # type: ignore[assignment]
    last_book_id: int = 0
    recent_books: list[int] = None  # type: ignore[assignment]
    library_scroll: float = 0.0
    details_open: bool = True

    def __post_init__(self) -> None:
        if self.folders is None:
            self.folders = [str(BOOKS_DIR)]
        if self.recent_books is None:
            self.recent_books = []

    def save(self) -> None:
        payload = asdict(self)
        payload["folders"] = [str(f) for f in self.folders]
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(SETTINGS_PATH)
        except OSError:
            pass


def load_settings() -> Settings:
    data: dict[str, Any] = {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    known = {f.name for f in fields(Settings)}
    clean = {k: v for k, v in data.items() if k in known}
    settings = Settings()
    for key, value in clean.items():
        try:
            setattr(settings, key, value)
        except (TypeError, ValueError):
            continue
    if not isinstance(settings.folders, list) or not settings.folders:
        settings.folders = [str(BOOKS_DIR)]
    if not isinstance(settings.recent_books, list):
        settings.recent_books = []
    return settings


def human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def fit_geometry(window, geometry: str, min_width: int = 1000, min_height: int = 640) -> str:
    """Не даёт окну оказаться больше экрана или за его пределами."""
    import re

    match = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geometry or "")
    screen_w = int(window.winfo_screenwidth())
    screen_h = int(window.winfo_screenheight())
    if not match:
        width = min(1440, screen_w - 40)
        height = min(900, screen_h - 70)
        x = max(10, (screen_w - width) // 2)
        y = max(10, (screen_h - height) // 2)
    else:
        width = min(int(match.group(1)), max(min_width, screen_w - 40))
        height = min(int(match.group(2)), max(min_height, screen_h - 70))
        x = int(match.group(3))
        y = int(match.group(4))
        if x < -width + 80 or x > screen_w - 80:
            x = max(10, (screen_w - width) // 2)
        if y < 0 or y > screen_h - 60:
            y = max(10, (screen_h - height) // 2)
        x = max(-width + 120, min(x, screen_w - 120))
        y = max(0, min(y, screen_h - 80))
    result = f"{width}x{height}+{x}+{y}"
    try:
        window.geometry(result)
    except Exception:
        pass
    return result


def app_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "chitalka"
    path.mkdir(parents=True, exist_ok=True)
    return path
