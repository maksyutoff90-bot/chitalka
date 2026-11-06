"""Викитека: поиск произведений и сохранение страницы в FB2."""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import html as lxml_html

from . import opds
from .opds import CatalogEntry, CatalogPage

API = "https://ru.wikisource.org/w/api.php"
AUTHORS = [
    ("Александр Пушкин", "Пушкин"),
    ("Антон Чехов", "Чехов"),
    ("Лев Толстой", "Толстой"),
    ("Михаил Лермонтов", "Лермонтов"),
    ("Николай Гоголь", "Гоголь"),
    ("Иван Тургенев", "Тургенев"),
    ("Фёдор Достоевский", "Достоевский"),
    ("Иван Крылов", "Крылов"),
]


def _api(params: dict) -> dict:
    params = dict(params)
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    url = API + "?" + urllib.parse.urlencode(params)
    data, content_type, _ = opds.fetch(
        url, max_bytes=20 * 1024 * 1024,
        accept="application/json, */*;q=0.5",
    )
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise opds.OPDSFeedError(f"Викитека вернула не JSON: {exc}") from exc


def _strip_html(value: str) -> str:
    try:
        root = lxml_html.fragment_fromstring(value or "", create_parent="div")
        text = root.text_content()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value or "")
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    return " ".join(text.split())


def featured() -> CatalogPage:
    page = CatalogPage(
        title="Викитека",
        subtitle="Русская литература в общественном достоянии",
        source="wikisource",
    )
    for name, query in AUTHORS:
        page.entries.append(
            CatalogEntry(
                title=name,
                author="Викитека",
                summary=f"Произведения: {name}",
                nav_url=f"ws-search:{urllib.parse.quote(query)}",
                source="wikisource",
                extra={"ws_query": query},
            )
        )
    page.entries.append(
        CatalogEntry(
            title="Случайные произведения",
            author="Викитека",
            summary="Открыть случайную подборку текстов",
            nav_url="ws-random",
            source="wikisource",
            extra={"ws_random": True},
        )
    )
    return page


def search(query: str) -> CatalogPage:
    query = (query or "").strip()
    if not query:
        return featured()
    payload = _api({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "0",
        "srlimit": "30",
        "srprop": "snippet|timestamp|size",
    })
    page = CatalogPage(
        title=f"Викитека · {query}",
        subtitle="Результаты поиска",
        source="wikisource",
    )
    raw = (payload.get("query") or {}).get("search") or []
    titles = [item.get("title") or "" for item in raw if item.get("title")]
    disambiguation: set[str] = set()
    if titles:
        try:
            props = _api({
                "action": "query",
                "prop": "pageprops",
                "ppprop": "disambiguation",
                "titles": "|".join(titles[:50]),
            })
            for item in (props.get("query") or {}).get("pages") or []:
                if "disambiguation" in (item.get("pageprops") or {}):
                    disambiguation.add((item.get("title") or "").lower())
        except Exception:
            pass
    for item in raw:
        title = item.get("title") or ""
        if not title or title.lower() in disambiguation:
            continue
        page.entries.append(
            CatalogEntry(
                title=title,
                summary=_strip_html(item.get("snippet") or ""),
                updated=item.get("timestamp") or "",
                source="wikisource",
                extra={"ws_title": title, "size": item.get("size") or 0},
            )
        )
    def rank(entry: CatalogEntry) -> tuple:
        title = entry.title.lower()
        penalty = title.count("/") * 8 + len(title) * 0.05
        if "издание" in title or "версия" in title:
            penalty += 10
        if "дополнительные материалы" in title or "примечания" in title:
            penalty += 12
        if title.startswith("сборник") or title.startswith("категория"):
            penalty += 15
        return (penalty, len(title))

    page.entries.sort(key=rank)
    return page


def random_works() -> CatalogPage:
    payload = _api({
        "action": "query",
        "list": "random",
        "rnnamespace": "0",
        "rnlimit": "30",
    })
    page = CatalogPage(
        title="Викитека · случайные произведения",
        subtitle="Общественное достояние",
        source="wikisource",
    )
    for item in (payload.get("query") or {}).get("random") or []:
        title = item.get("title") or ""
        if title:
            page.entries.append(
                CatalogEntry(
                    title=title,
                    author="Викитека",
                    source="wikisource",
                    extra={"ws_title": title},
                )
            )
    return page


def _metadata(root) -> tuple[str, str, str, str]:
    def by_id(ident: str) -> str:
        nodes = root.xpath(f'//*[@id="{ident}"]')
        if not nodes:
            return ""
        return " ".join(nodes[0].text_content().split())

    title = by_id("ws-title")
    author = by_id("ws-author")
    created = by_id("ws-created")
    published = by_id("ws-published")
    author = re.sub(r"^(автор|author)\s*[:—-]?\s*", "", author, flags=re.I).strip()
    return title, author, created, published


def _poem_lines(element) -> list[str]:
    lines: list[str] = []
    for paragraph in element.iter("p"):
        # itertext() не знает про <br>, поэтому собираем строки по <br>.
        chunks: list[str] = [paragraph.text or ""]
        for child in paragraph:
            if child.tail:
                chunks.append(child.tail)
            if child.tag == "br":
                chunks.append("\n")
        raw = "".join(chunks)
        for line in raw.split("\n"):
            line = " ".join(line.split())
            if line:
                lines.append(line)
    if not lines:
        text = " ".join(element.text_content().split())
        if text:
            lines = [text]
    return lines


def _walk_content(content) -> list[dict]:
    sections: list[dict] = [{"title": "", "blocks": []}]
    stop = False
    drop_classes = {
        "reference", "references", "references-small", "ws-noexport", "navbox",
        "headertemplate", "license", "licensetemplate", "mw-editsection",
        "notice", "metadata", "hatnote", "mw-cite-backlink", "toc",
    }

    def clean(text: str) -> str:
        text = text.replace("\xa0", " ").replace("\u00ad", "")
        text = re.sub(r"\[\s*\d+\s*\]", "", text)
        return " ".join(text.split())

    def add(kind: str, text: str) -> None:
        text = clean(text)
        if text:
            sections[-1]["blocks"].append({"kind": kind, "text": text})

    def heading(text: str) -> None:
        text = clean(text)
        if not text:
            return
        if any(word in text.lower() for word in ("примечан", "ссылк", "литератур", "источник")):
            nonlocal stop
            stop = True
            return
        if sections[-1]["title"] and not sections[-1]["blocks"]:
            sections[-1]["title"] = text
        else:
            sections.append({"title": text, "blocks": []})

    def walk(element) -> None:
        nonlocal stop
        for child in element:
            if stop or not isinstance(child.tag, str):
                continue
            tag = child.tag.lower()
            classes = set((child.get("class") or "").split())
            if classes & drop_classes:
                continue
            if tag in ("script", "style", "link", "table"):
                continue
            if tag in ("h2", "h3", "h4"):
                heading(child.text_content())
            elif tag == "center":
                text = clean(child.text_content())
                if text and len(text) <= 40:
                    heading(text)
                else:
                    add("p", text)
            elif tag == "p":
                if "epigraph2" in classes:
                    add("epigraph", child.text_content())
                else:
                    add("p", child.text_content())
            elif tag == "div" and "poem" in classes:
                lines = _poem_lines(child)
                if lines:
                    sections[-1]["blocks"].append(
                        {"kind": "verse", "text": "\n".join(lines)}
                    )
            elif tag == "div" and "epigraph2" in classes:
                for paragraph in child.iter("p"):
                    add("epigraph", paragraph.text_content())
                for author in child.iter("div"):
                    if "align-right" in (author.get("class") or ""):
                        add("epigraph_author", author.text_content())
            elif tag == "div":
                walk(child)
            elif tag == "blockquote":
                add("cite", child.text_content())
            elif tag in ("ul", "ol"):
                for item in child.iter("li"):
                    add("p", "• " + item.text_content())

    walk(content)
    return [section for section in sections if section["title"] or section["blocks"]]


def _xml_author(author: str) -> str:
    author = (author or "").strip()
    if not author:
        return ""
    parts = author.split()
    if len(parts) == 1:
        return f"<author><nickname>{escape(author)}</nickname></author>"
    last = parts[-1]
    first = " ".join(parts[:-1])
    return (
        "<author>"
        f"<first-name>{escape(first)}</first-name>"
        f"<last-name>{escape(last)}</last-name>"
        "</author>"
    )


def _build_fb2(title: str, author: str, year: str, sections: list[dict],
               annotation: str) -> bytes:
    body_parts: list[str] = []
    first = True
    for section in sections:
        title_text = section.get("title") or ""
        blocks = section.get("blocks") or []
        if not title_text and not blocks:
            continue
        part = ["<section>"]
        if title_text:
            part.append(f"<title><p>{escape(title_text)}</p></title>")
        for block in blocks:
            kind = block.get("kind")
            text = block.get("text") or ""
            if kind == "verse":
                lines = [line for line in text.split("\n") if line.strip()]
                if lines:
                    part.append("<poem><stanza>" + "".join(
                        f"<v>{escape(line)}</v>" for line in lines
                    ) + "</stanza></poem>")
            elif kind == "epigraph":
                part.append(f"<epigraph><p>{escape(text)}</p></epigraph>")
            elif kind == "epigraph_author":
                part.append(f"<epigraph><p>{escape(text)}</p></epigraph>")
            else:
                part.append(f"<p>{escape(text)}</p>")
        part.append("</section>")
        body_parts.append("\n".join(part))
        first = False
    if not body_parts:
        body_parts.append(f"<section><p>{escape(title)}</p></section>")
    annotation_xml = f"<annotation><p>{escape(annotation)}</p></annotation>" if annotation else ""
    date_xml = f'<date value="{escape(year)}">{escape(year)}</date>' if year else ""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description>
<title-info>
<genre>prose_classic</genre>
{_xml_author(author)}
<book-title>{escape(title)}</book-title>
{annotation_xml}
{date_xml}
<lang>ru</lang>
<src-lang>ru</src-lang>
</title-info>
<document-info>
<author><nickname>Читалка</nickname></author>
<program-used>Chitalka Wikisource</program-used>
<id>wikisource-{escape(title)}</id>
<version>1.0</version>
</document-info>
</description>
<body>
{chr(10).join(body_parts)}
</body>
</FictionBook>
"""
    return xml.encode("utf-8")


def download(title: str, folder: Path) -> Path:
    payload = _api({
        "action": "parse",
        "page": title,
        "prop": "text|displaytitle",
        "disableeditsection": "1",
        "disabletoc": "1",
    })
    parse = payload.get("parse") or {}
    html_text = parse.get("text") or ""
    if not html_text:
        raise opds.OPDSFeedError("Викитека не вернула текст страницы")
    root = lxml_html.fromstring(html_text)
    meta_title, author, created, published = _metadata(root)
    display = _strip_html(parse.get("displaytitle") or "")
    book_title = meta_title or display or title

    candidates = []
    for div in root.iter("div"):
        classes = set((div.get("class") or "").split())
        if "text" not in classes:
            continue
        count = sum(1 for _ in div.iter("p"))
        candidates.append((count, div))
    content = max(candidates, key=lambda pair: pair[0])[1] if candidates else root
    if root.xpath('//*[@id="disambig" or contains(@class,"disambig")]'):
        raise opds.OPDSFeedError(
            "Это страница значений. Выберите конкретное произведение "
            "с уточнением в названии, например «Пиковая дама (Пушкин)»."
        )
    sections = _walk_content(content)
    if not any(section["blocks"] for section in sections):
        raise opds.OPDSFeedError("На странице не нашлось текста для книги")

    annotation = ""
    for section in sections:
        for block in section["blocks"]:
            if block["kind"] == "p" and len(block["text"]) > 80:
                annotation = block["text"][:350]
                break
        if annotation:
            break
    year = (created or published or "")[:20]
    data = _build_fb2(book_title, author, year, sections, annotation)
    folder.mkdir(parents=True, exist_ok=True)
    target = opds.unique_path(folder, opds.safe_filename(book_title, ".fb2"))
    target.write_bytes(data)
    return target
