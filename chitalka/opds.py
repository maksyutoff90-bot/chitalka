"""OPDS 1/2: загрузка каталогов, разбор лент и скачивание книг."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from .config import OPDS_CACHE_DIR

USER_AGENT = "Chitalka/1.0 (+https://github.com/maksyutoff90-bot/chitalka)"
ATOM = "{http://www.w3.org/2005/Atom}"
OPDS = "{http://opds-spec.org/2010/catalog}"
MAX_FEED = 20 * 1024 * 1024
MAX_COVER = 8 * 1024 * 1024
MAX_BOOK = 300 * 1024 * 1024


class OPDSFeedError(Exception):
    pass


@dataclass
class CatalogEntry:
    title: str
    author: str = ""
    summary: str = ""
    image_url: str = ""
    nav_url: str = ""
    acquisitions: dict[str, str] = field(default_factory=dict)
    entry_id: str = ""
    updated: str = ""
    source: str = "opds"
    extra: dict = field(default_factory=dict)

    @property
    def is_navigation(self) -> bool:
        return bool(self.nav_url) and not self.acquisitions


@dataclass
class CatalogPage:
    title: str
    entries: list[CatalogEntry] = field(default_factory=list)
    url: str = ""
    subtitle: str = ""
    next_url: str = ""
    search_url: str = ""
    opensearch_url: str = ""
    source: str = "opds"


@dataclass(frozen=True)
class CatalogSource:
    key: str
    name: str
    url: str
    search: str = ""
    kind: str = "opds"
    description: str = ""


BUILTIN_CATALOGS = [
    CatalogSource(
        "gutenberg",
        "Project Gutenberg",
        "https://www.gutenberg.org/ebooks/search.opds/?sort_order=downloads",
        "https://www.gutenberg.org/ebooks/search.opds/?query={query}",
        "opds",
        "70 000 книг на разных языках",
    ),
    CatalogSource(
        "wikisource",
        "Викитека",
        "",
        "",
        "wikisource",
        "Русская классика",
    ),
]


def format_for_type(content_type: str) -> str:
    content_type = (content_type or "").lower().split(";")[0].strip()
    mapping = {
        "application/epub+zip": "epub",
        "application/pdf": "pdf",
        "application/x-fictionbook+xml": "fb2",
        "application/fb2+xml": "fb2",
        "application/fb2+zip": "fb2",
        "application/fb2": "fb2",
        "text/plain": "txt",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/x-mobipocket-ebook": "mobi",
        "application/vnd.amazon.ebook": "azw3",
    }
    return mapping.get(content_type, "")


EXTENSIONS = {
    "epub": ".epub", "pdf": ".pdf", "fb2": ".fb2", "txt": ".txt",
    "html": ".html", "mobi": ".mobi", "azw3": ".azw3",
}

READABLE = {"epub", "fb2", "pdf", "txt"}
PREFERENCE = ["epub", "fb2", "pdf", "txt"]


def safe_filename(value: str, extension: str = "", limit: int = 110) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value[:limit].rstrip(" .") or "book"
    if extension and not value.lower().endswith(extension.lower()):
        value += extension
    return value


def unique_path(folder: Path, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for index in range(2, 1000):
        candidate = folder / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return folder / f"{stem}-{hashlib.sha1(filename.encode()).hexdigest()[:6]}{suffix}"


def _text(element, path: str) -> str:
    found = element.find(path)
    if found is None:
        return ""
    return " ".join("".join(found.itertext()).split())


def _link_href(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href or "")


def _is_http(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not _is_http(url):
        raise OPDSFeedError("Нужен адрес http:// или https://")
    return url


def fetch(url: str, *, max_bytes: int = MAX_FEED, timeout: int = 25,
          accept: str = "application/atom+xml, application/opds+json;q=0.9, "
                        "application/json;q=0.8, */*;q=0.5"):
    """Скачивает URL и возвращает (данные, content-type, итоговый URL)."""
    url = validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            total = int(response.headers.get("Content-Length") or 0)
            if total and total > max_bytes:
                raise OPDSFeedError("Файл слишком большой")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise OPDSFeedError("Файл слишком большой")
                chunks.append(chunk)
            data = b"".join(chunks)
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                data = gzip.decompress(data)
            return data, content_type, response.geturl()
    except urllib.error.HTTPError as exc:
        raise OPDSFeedError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise OPDSFeedError(f"Нет связи: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OPDSFeedError("Сервер не ответил вовремя") from exc


def download(url: str, target: Path, *,
             progress: Callable[[int, int], None] | None = None,
             max_bytes: int = MAX_BOOK) -> Path:
    url = validate_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            total = int(response.headers.get("Content-Length") or 0)
            if total and total > max_bytes:
                raise OPDSFeedError("Книга слишком большая")
            done = 0
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > max_bytes:
                        raise OPDSFeedError("Книга слишком большая")
                    handle.write(chunk)
                    if progress:
                        progress(done, total)
        part.replace(target)
        return target
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise OPDSFeedError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        part.unlink(missing_ok=True)
        raise OPDSFeedError(f"Нет связи: {exc.reason}") from exc
    except Exception:
        part.unlink(missing_ok=True)
        raise


def parse_feed(data: bytes, base_url: str) -> CatalogPage:
    stripped = data.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return _parse_opds2(stripped, base_url)
    try:
        root = etree.fromstring(
            data,
            parser=etree.XMLParser(recover=True, huge_tree=True, no_network=True),
        )
    except Exception as exc:  # noqa: BLE001
        raise OPDSFeedError(f"Это не OPDS/Atom: {exc}") from exc
    if root is None or root.tag != ATOM + "feed":
        raise OPDSFeedError("Это не OPDS-лента")
    page = CatalogPage(
        title=_text(root, ATOM + "title") or "Каталог",
        url=base_url,
        subtitle=_text(root, ATOM + "subtitle"),
    )
    for link in root.findall(ATOM + "link"):
        rel = (link.get("rel") or "").strip().lower()
        href = _link_href(base_url, link.get("href") or "")
        if rel == "next" and href:
            page.next_url = href
        elif rel == "search" and href:
            if "opensearchdescription" in (link.get("type") or ""):
                page.opensearch_url = href
            else:
                page.search_url = href
    for entry in root.findall(ATOM + "entry"):
        parsed = _parse_entry(entry, base_url)
        if parsed is not None:
            page.entries.append(parsed)
    return page


def _parse_entry(entry, base_url: str) -> CatalogEntry | None:
    title = _text(entry, ATOM + "title")
    if not title:
        return None
    author = ""
    author_node = entry.find(ATOM + "author")
    if author_node is not None:
        author = _text(author_node, ATOM + "name")
    summary = _text(entry, ATOM + "summary") or _text(entry, ATOM + "content")
    summary = re.sub(r"\s+", " ", summary).strip()
    item = CatalogEntry(
        title=title,
        author=author,
        summary=summary[:1200],
        entry_id=_text(entry, ATOM + "id"),
        updated=_text(entry, ATOM + "updated"),
    )
    navigation = ""
    images: list[tuple[str, str]] = []
    for link in entry.findall(ATOM + "link"):
        href = _link_href(base_url, link.get("href") or "")
        if not href:
            continue
        rel = (link.get("rel") or "").strip().lower()
        ctype = (link.get("type") or "").strip().lower()
        if "opds-spec.org/image" in rel or rel in ("image", "thumbnail"):
            images.append((rel, href))
        elif "acquisition" in rel or rel in ("enclosure",):
            fmt = format_for_type(ctype)
            if fmt:
                item.acquisitions.setdefault(fmt, href)
        elif "atom+xml" in ctype or "opds-catalog" in ctype:
            if rel in ("subsection", "start", "up", "crawlable", "") or "crawlable" in rel:
                navigation = navigation or href
    if images:
        images.sort(key=lambda pair: 0 if "thumbnail" in pair[0] else 1)
        item.image_url = images[0][1]
    item.nav_url = navigation
    if not item.acquisitions and not item.nav_url:
        for link in entry.findall(ATOM + "link"):
            rel = (link.get("rel") or "").lower()
            if rel in ("subsection", "start") and link.get("href"):
                item.nav_url = _link_href(base_url, link.get("href"))
                break
    if not item.acquisitions and not item.nav_url:
        return None
    return item


def _parse_opds2(data: bytes, base_url: str) -> CatalogPage:
    try:
        feed = json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise OPDSFeedError(f"Некорректный OPDS 2 JSON: {exc}") from exc
    metadata = feed.get("metadata") or {}
    page = CatalogPage(
        title=str(metadata.get("title") or "Каталог"),
        url=base_url,
        subtitle=str(metadata.get("description") or ""),
        source="opds2",
    )
    for link in feed.get("links") or []:
        rel = str(link.get("rel") or "").lower()
        href = _link_href(base_url, link.get("href") or "")
        if rel == "search":
            page.search_url = href
        elif rel == "next" and href:
            page.next_url = href
    for nav in feed.get("navigation") or []:
        title = str(nav.get("title") or "").strip()
        href = _link_href(base_url, nav.get("href") or "")
        if title and href:
            page.entries.append(
                CatalogEntry(title=title, nav_url=href, source="opds2")
            )
    for publication in feed.get("publications") or []:
        meta = publication.get("metadata") or {}
        title = str(meta.get("title") or "").strip()
        if not title:
            continue
        authors = meta.get("author")
        if isinstance(authors, list):
            author = ", ".join(str(a.get("name") or "") for a in authors if isinstance(a, dict))
        elif isinstance(authors, dict):
            author = str(authors.get("name") or "")
        else:
            author = ""
        item = CatalogEntry(
            title=title,
            author=author,
            summary=str(meta.get("description") or "")[:1200],
            source="opds2",
        )
        for link in publication.get("links") or []:
            rel = str(link.get("rel") or "").lower()
            href = _link_href(base_url, link.get("href") or "")
            ctype = str(link.get("type") or "").lower()
            if "image" in rel:
                item.image_url = item.image_url or href
            elif "acquisition" in rel:
                fmt = format_for_type(ctype)
                if fmt:
                    item.acquisitions.setdefault(fmt, href)
        if item.acquisitions or item.nav_url:
            page.entries.append(item)
    return page


def resolve_search(page: CatalogPage, query: str) -> str:
    query = (query or "").strip()
    if not query:
        return ""
    encoded = urllib.parse.quote_plus(query)
    template = page.search_url
    if not template and page.opensearch_url:
        try:
            data, _, _ = fetch(page.opensearch_url, max_bytes=2 * 1024 * 1024)
            root = etree.fromstring(data, parser=etree.XMLParser(recover=True))
            for url_node in root.iter():
                if str(url_node.tag).rsplit("}", 1)[-1].lower() != "url":
                    continue
                if "atom" not in (url_node.get("type") or ""):
                    continue
                candidate = url_node.get("template") or ""
                if candidate:
                    template = candidate
                    break
        except Exception:
            template = ""
    if not template:
        return ""
    if "{searchTerms}" in template:
        return template.replace("{searchTerms}", encoded)
    if "{query}" in template:
        return template.replace("{query}", encoded)
    if "?" in template:
        return template + ("&" if not template.endswith(("?", "&")) else "") + "query=" + encoded
    return template + "?query=" + encoded


def best_format(entry: CatalogEntry) -> str:
    for fmt in PREFERENCE:
        if fmt in entry.acquisitions:
            return fmt
    return ""


def cover_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return OPDS_CACHE_DIR / f"{digest}.img"


def cache_cover(url: str) -> Path:
    target = cover_path(url)
    if target.exists() and target.stat().st_size > 0:
        return target
    if not _is_http(url) or url.startswith("data:"):
        raise OPDSFeedError("Нет обложки")
    data, _, _ = fetch(url, max_bytes=MAX_COVER, accept="image/*")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def xml_escape_text(value: str) -> str:
    return xml_escape(value or "")
