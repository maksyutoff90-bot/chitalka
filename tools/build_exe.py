"""Сборка автономной сборки «Читалка» через PyInstaller.

Запуск: python tools/build_exe.py
Результат: dist/Chitalka/Chitalka.exe + data/ с демо-книгами рядом.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Chitalka"
BUILD = ROOT / "build"


def main() -> int:
    if not (ROOT / "main.py").exists():
        print("Не найден main.py")
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Установите PyInstaller:  python -m pip install pyinstaller")
        return 1

    icon = ROOT / "data" / "app.ico"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "Chitalka",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--collect-all", "pymupdf",
        "--collect-all", "lxml",
        "--collect-all", "tkinterdnd2",
        "--add-data", f"{icon};data",
        "--add-data", f"{ROOT / 'legal'};legal",
        str(ROOT / "main.py"),
    ]
    if icon.exists():
        command[5:5] = ["--icon", str(icon)]
    print("Сборка...")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("PyInstaller завершился с ошибкой")
        return result.returncode

    data = DIST / "data"
    for folder in (data / "books", data / "covers"):
        folder.mkdir(parents=True, exist_ok=True)
    for name in ("app.ico", "app.png"):
        if (ROOT / "data" / name).exists():
            shutil.copy2(ROOT / "data" / name, data / name)
    for book in (ROOT / "data" / "books").iterdir():
        if book.is_file():
            shutil.copy2(book, data / "books" / book.name)
    for cover in (ROOT / "data" / "covers").glob("*.jpg"):
        shutil.copy2(cover, data / "covers" / cover.name)
    shots = ROOT / "data" / "screenshots"
    if shots.exists():
        target_shots = data / "screenshots"
        target_shots.mkdir(parents=True, exist_ok=True)
        for shot in shots.glob("*.png"):
            shutil.copy2(shot, target_shots / shot.name)
    dictionaries = ROOT / "data" / "dictionaries"
    if dictionaries.exists():
        target_dict = data / "dictionaries"
        target_dict.mkdir(parents=True, exist_ok=True)
        for name in ("freedict.sqlite.xz", "README.txt", "COPYING",
                     "LICENSE-CC-BY-SA.txt"):
            source = dictionaries / name
            if source.exists():
                shutil.copy2(source, target_dict / name)
    if (ROOT / "README.md").exists():
        shutil.copy2(ROOT / "README.md", DIST / "README.md")
    legal = ROOT / "legal"
    if legal.exists():
        shutil.copytree(legal, DIST / "legal", dirs_exist_ok=True)
    print(f"Готово: {DIST / 'Chitalka.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
