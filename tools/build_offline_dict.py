"""Собирает офлайн-словарь FreeDict/WikDict в SQLite.

Запуск:
    python tools/build_offline_dict.py

Скачивает StarDict-архивы FreeDict (ru-en, en-ru), разбирает их и кладёт
data/dictionaries/freedict.sqlite. Данные — CC BY-SA 3.0, см. README.txt.
"""

from __future__ import annotations

import gzip
import html
import lzma
import re
import sqlite3
import struct
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "dictionaries"
VERSION = "2025.11.23"
URLS = {
    "ru": f"https://download.freedict.org/dictionaries/rus-eng/{VERSION}/"
          f"freedict-rus-eng-{VERSION}.stardict.tar.xz",
    "en": f"https://download.freedict.org/dictionaries/eng-rus/{VERSION}/"
          f"freedict-eng-rus-{VERSION}.stardict.tar.xz",
}


def clean_definition(raw: str) -> str:
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:div|p|li|tr|h\d|ol|ul)>", "\n", raw, flags=re.I)
    raw = re.sub(r"<(?:div|p|li|tr|h\d|ol|ul)[^>]*>", "\n", raw, flags=re.I)
    try:
        text = lxml_html.fromstring("<div>" + raw + "</div>").text_content()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def build(direction: str, url: str, conn: sqlite3.Connection) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "dict.tar.xz"
        print("download", direction, url)
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            prefix = names[0].split("/")[0]
            ifo = tar.extractfile(f"{prefix}/{prefix}.ifo").read().decode("utf-8", "replace")
            idx = gzip.decompress(tar.extractfile(f"{prefix}/{prefix}.idx.gz").read())
            body = tar.extractfile(f"{prefix}/{prefix}.dict").read()
            copying = tar.extractfile(f"{prefix}/COPYING")
            if copying is not None:
                (OUT / "COPYING").write_bytes(copying.read())
    wordcount = 0
    position = 0
    rows = []
    while position < len(idx):
        end = idx.index(b"\0", position)
        word = idx[position:end].decode("utf-8", "replace").strip()
        offset, size = struct.unpack(">II", idx[end + 1:end + 9])
        position = end + 9
        if not word:
            continue
        raw = body[offset:offset + size].decode("utf-8", "replace")
        definition = clean_definition(raw)[:8000]
        if not definition:
            continue
        rows.append((word, word.lower(), direction, definition))
        wordcount += 1
        if len(rows) >= 2000:
            conn.executemany(
                "INSERT INTO entries(word, word_lower, lang, definition) VALUES(?,?,?,?)",
                rows,
            )
            rows.clear()
    if rows:
        conn.executemany(
            "INSERT INTO entries(word, word_lower, lang, definition) VALUES(?,?,?,?)",
            rows,
        )
    print("entries", direction, wordcount, "sametype", "h")
    return wordcount


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "freedict.sqlite"
    target.unlink(missing_ok=True)
    conn = sqlite3.connect(target)
    conn.executescript("""
    PRAGMA journal_mode=OFF;
    PRAGMA synchronous=OFF;
    CREATE TABLE entries(
        id INTEGER PRIMARY KEY,
        word TEXT NOT NULL,
        word_lower TEXT NOT NULL,
        lang TEXT NOT NULL,
        definition TEXT NOT NULL
    );
    CREATE INDEX idx_entries_word ON entries(word_lower, lang);
    """)
    total = 0
    for direction, url in URLS.items():
        total += build(direction, url, conn)
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    (OUT / "README.txt").write_text(
        "Офлайн-словарь Chitalka\n"
        "=====================\n\n"
        "Источник: FreeDict / WikDict, издание 2025.11.23.\n"
        "Русско-английский и англо-русский словари.\n"
        "Данные распространяются по лицензии CC BY-SA 3.0:\n"
        "https://creativecommons.org/licenses/by-sa/3.0/\n\n"
        "Страницы:\n"
        "https://freedict.org/\n"
        "https://www.wikdict.com/\n\n"
        "Файл freedict.sqlite собран из StarDict-версий FreeDict.\n"
        f"Всего статей: {total}.\n",
        encoding="utf-8",
    )
    print("done", target, target.stat().st_size, "entries", total)
    archive = OUT / "freedict.sqlite.xz"
    archive.write_bytes(lzma.compress(target.read_bytes(), preset=6))
    print("compressed", archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
