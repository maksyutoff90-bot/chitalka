"""Скачивает тексты общественного достояния с Викитеки для демо-библиотеки.

Запуск: python tools/fetch_texts.py
Результат: tools/texts/<key>.json — главы и абзацы, готовые для сборки книг.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from lxml import html

PAGES = {
    "pik": {
        "page": "Пиковая дама (Пушкин)",
        "title": "Пиковая дама",
        "author": "Александр Пушкин",
        "year": "1834",
        "genre": "Классическая проза",
    },
    "dama": {
        "page": "Дама с собачкой (Чехов)",
        "title": "Дама с собачкой",
        "author": "Антон Чехов",
        "year": "1899",
        "genre": "Классическая проза",
    },
    "posle": {
        "page": "После бала (Толстой)",
        "title": "После бала",
        "author": "Лев Толстой",
        "year": "1911",
        "genre": "Классическая проза",
    },
    "ionych": {
        "page": "Ионыч (Чехов)",
        "title": "Ионыч",
        "author": "Антон Чехов",
        "year": "1898",
        "genre": "Классическая проза",
    },
}

OUT = Path(__file__).resolve().parent / "texts"
OUT.mkdir(exist_ok=True)

DROP_CLASSES = {
    "reference", "references", "references-small", "ws-noexport", "navbox",
    "headertemplate", "license", "licensetemplate", "mw-editsection", "notice",
    "metadata", "interwiki-info", "mw-cite-backlink",
}


def clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"\[\s*\d+\s*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def class_tokens(element) -> set[str]:
    return set((element.get("class") or "").split())


def _drop(element) -> bool:
    return bool(class_tokens(element) & DROP_CLASSES)


def _strip_refs(root) -> None:
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue
        if element.tag == "sup" and "reference" in class_tokens(element):
            element.getparent().remove(element)
        elif _drop(element):
            try:
                element.getparent().remove(element)
            except (AttributeError, ValueError):
                pass


def _paragraph_text(element) -> str:
    return clean(element.text_content())


def _poem_lines(element) -> list[str]:
    lines: list[str] = []
    for paragraph in element.iter("p"):
        # <br> внутри p — граница строк.
        chunks = [paragraph.text or ""]
        for child in paragraph:
            if child.tail:
                chunks.append(child.tail)
            if child.tag == "br":
                chunks.append("\n")
        raw = "".join(chunks)
        for line in raw.split("\n"):
            line = clean(line)
            if line:
                lines.append(line)
    if not lines:
        text = clean(element.text_content())
        if text:
            lines = [text]
    return lines


def _epigraph(element) -> list[dict]:
    blocks: list[dict] = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "p":
            text = _paragraph_text(child)
            if text:
                blocks.append({"kind": "epigraph", "text": text})
        elif child.tag == "div":
            cls = class_tokens(child)
            if "poem" in cls:
                for line in _poem_lines(child):
                    blocks.append({"kind": "verse", "text": line})
            elif "align-right" in cls:
                text = _paragraph_text(child)
                if text:
                    blocks.append({"kind": "epigraph_author", "text": text})
            elif child.text and child.text.strip() and not list(child):
                blocks.append({"kind": "epigraph", "text": clean(child.text)})
            else:
                blocks.extend(_epigraph(child))
        elif child.tag == "i":
            text = _paragraph_text(child)
            if text:
                blocks.append({"kind": "epigraph_author", "text": text})
    return blocks


def extract(html_text: str) -> list[dict]:
    root = html.fromstring(html_text)
    content = None
    best = -1
    for div in root.iter("div"):
        if "text" not in class_tokens(div):
            continue
        count = sum(1 for _ in div.iter("p"))
        if count > best:
            best, content = count, div
    if content is None:
        content = root.xpath('//div[@id="mw-content-text"]')
        content = content[0] if content else root

    chapters: list[dict] = []
    current = {"title": "", "blocks": []}
    chapters.append(current)
    stop = False

    def add_block(kind: str, text: str) -> None:
        text = clean(text)
        if not text:
            return
        if kind == "epigraph_author":
            current["blocks"].append({"kind": "epigraph_author", "text": text})
        else:
            current["blocks"].append({"kind": kind, "text": text})

    def start_chapter(title: str) -> None:
        nonlocal current
        title = clean(title)
        if not title:
            return
        last = chapters[-1] if chapters else None
        if last is not None and not last["blocks"]:
            last["title"] = title
            current = last
            return
        if (
            last is not None
            and not last["title"]
            and all(block["kind"] != "p" for block in last["blocks"])
        ):
            last["title"] = title
            current = last
            return
        current = {"title": title, "blocks": []}
        chapters.append(current)

    def walk(element) -> None:
        nonlocal stop
        for child in element:
            if stop or not isinstance(child.tag, str):
                continue
            tag = child.tag.lower()
            cls = class_tokens(child)
            if tag in ("h2", "h3"):
                title = clean(child.text_content())
                if "примечан" in title.lower() or "источник" in title.lower():
                    stop = True
                    continue
                if title:
                    start_chapter(title)
            elif tag == "center":
                title = clean(child.text_content())
                if title and len(title) <= 40:
                    start_chapter(title)
            elif tag == "div" and "epigraph2" in cls:
                for block in _epigraph(child):
                    add_block(block["kind"], block["text"])
            elif tag == "div" and "poem" in cls:
                for line in _poem_lines(child):
                    add_block("verse", line)
            elif tag == "p":
                add_block("p", _paragraph_text(child))
            elif tag == "div":
                if "poem" in cls:
                    for line in _poem_lines(child):
                        add_block("verse", line)
                else:
                    walk(child)

    walk(content)
    chapters = [chapter for chapter in chapters if chapter["blocks"]]
    # Убираем служебные "главы" из одного заголовка.
    return chapters


def merge_verses(blocks: list[dict]) -> list[dict]:
    """Подряд идущие строки стихов склеиваем в один блок с переносами."""
    result: list[dict] = []
    buffer: list[str] = []
    for block in blocks:
        if block["kind"] == "verse":
            buffer.append(block["text"])
            continue
        if buffer:
            result.append({"kind": "verse", "text": "\n".join(buffer)})
            buffer = []
        result.append(block)
    if buffer:
        result.append({"kind": "verse", "text": "\n".join(buffer)})
    return result


def main() -> None:
    for key, info in PAGES.items():
        url = "https://ru.wikisource.org/w/api.php?" + urllib.parse.urlencode(
            {
                "action": "parse",
                "page": info["page"],
                "prop": "text",
                "format": "json",
                "formatversion": "2",
            }
        )
        request = urllib.request.Request(url, headers={"User-Agent": "ChitalkaDemo/1.0"})
        data = json.loads(urllib.request.urlopen(request, timeout=40).read().decode("utf-8"))
        html_text = data["parse"]["text"]
        root = html.fromstring(html_text)
        _strip_refs(root)
        chapters = extract(html.tostring(root, encoding="unicode"))
        for chapter in chapters:
            chapter["blocks"] = merge_verses(chapter["blocks"])
        payload = {
            "title": info["title"],
            "author": info["author"],
            "year": info["year"],
            "genre": info["genre"],
            "source": f"https://ru.wikisource.org/wiki/{urllib.parse.quote(info['page'].replace(' ', '_'))}",
            "chapters": chapters,
        }
        target = OUT / f"{key}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        paragraphs = sum(1 for chapter in chapters for block in chapter["blocks"] if block["kind"] == "p")
        chars = sum(len(block["text"]) for chapter in chapters for block in chapter["blocks"])
        print(f"{key}: глав {len(chapters)}, абзацев {paragraphs}, символов {chars}")


if __name__ == "__main__":
    main()
