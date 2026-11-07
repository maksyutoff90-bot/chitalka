from __future__ import annotations

from chitalka import opds

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opds="http://opds-spec.org/2010/catalog">
  <title>Тестовый каталог</title>
  <id>urn:test</id>
  <updated>2026-01-01T00:00:00Z</updated>
  <link rel="search" type="application/atom+xml"
        href="/search?q={searchTerms}"/>
  <entry>
    <title>Книга первая</title>
    <id>urn:book:1</id>
    <author><name>Иван Тестов</name></author>
    <updated>2026-01-01T00:00:00Z</updated>
    <link rel="http://opds-spec.org/acquisition/open-access"
          type="application/fb2+zip" href="/books/one.fb2.zip"/>
    <link rel="http://opds-spec.org/image" type="image/jpeg" href="/covers/one.jpg"/>
    <summary>Описание книги</summary>
  </entry>
  <entry>
    <title>Раздел</title>
    <id>urn:section:1</id>
    <updated>2026-01-01T00:00:00Z</updated>
    <link rel="subsection" type="application/atom+xml;profile=opds-catalog"
          href="/catalog/section"/>
  </entry>
</feed>
""".encode("utf-8")


def test_parse_atom_entries():
    page = opds.parse_feed(ATOM, "https://example.org/catalog/")
    assert page.title == "Тестовый каталог"
    assert len(page.entries) == 2
    book = page.entries[0]
    assert book.title == "Книга первая"
    assert book.author == "Иван Тестов"
    assert book.acquisitions["fb2"] == "https://example.org/books/one.fb2.zip"
    assert book.nav_url == ""
    section = page.entries[1]
    assert section.nav_url == "https://example.org/catalog/section"


def test_resolve_search_and_best_format():
    page = opds.parse_feed(ATOM, "https://example.org/catalog/")
    url = opds.resolve_search(page, "Пушкин")
    assert "search" in url
    assert "q=" in url
    assert isinstance(opds.best_format(page.entries[0]), str)


def test_safe_filename():
    assert "/" not in opds.safe_filename("a/b:c?.fb2")
    assert opds.safe_filename("Книга.fb2", ".fb2").endswith(".fb2")
