"""Собирает демонстрационную библиотеку из текстов общественного достояния.

Запуск: python tools/make_samples.py [--clean]
Книги кладутся в data/books, обложки — в data/covers.
"""

from __future__ import annotations

import base64
import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chitalka.config import BOOKS_DIR  # noqa: E402
from chitalka.covers import generate_cover  # noqa: E402

TEXTS = Path(__file__).resolve().parent / "texts"

POEMS = [
    {
        "title": "Зимнее утро",
        "author": "Александр Пушкин",
        "year": "1829",
        "stanzas": [
            [
                "Мороз и солнце; день чудесный!",
                "Ещё ты дремлешь, друг прелестный —",
                "Пора, красавица, проснись:",
                "Открой сомкнуты негой взоры",
                "Навстречу северной Авроры,",
                "Звездою севера явись!",
            ],
            [
                "Вечор, ты помнишь, вьюга злилась,",
                "На мутном небе мгла носилась;",
                "Луна, как бледное пятно,",
                "Сквозь тучи мрачные желтела,",
                "И ты печальная сидела —",
                "А нынче… погляди в окно:",
            ],
            [
                "Под голубыми небесами",
                "Великолепными коврами,",
                "Блестя на солнце, снег лежит;",
                "Прозрачный лес один чернеет,",
                "И ель сквозь иней зеленеет,",
                "И речка подо льдом блестит.",
            ],
            [
                "Вся комната янтарным блеском",
                "Озарена. Весёлым треском",
                "Трещит затопленная печь.",
                "Приятно думать у лежанки.",
                "Но знаешь: не велеть ли в санки",
                "Кобылку бурую запречь?",
            ],
            [
                "Скользя по утреннему снегу,",
                "Друг милый, предадимся бегу",
                "Нетерпеливого коня",
                "И навестим поля пустые,",
                "Леса, недавно столь густые,",
                "И берег, милый для меня.",
            ],
        ],
    },
    {
        "title": "Парус",
        "author": "Михаил Лермонтов",
        "year": "1841",
        "stanzas": [
            [
                "Белеет парус одинокой",
                "В тумане моря голубом!..",
                "Что ищет он в стране далёкой?",
                "Что кинул он в краю родном?..",
            ],
            [
                "Играют волны — ветер свищет,",
                "И мачта гнётся и скрипит…",
                "Увы! он счастия не ищет",
                "И не от счастия бежит!",
            ],
            [
                "Под ним струя светлей лазури,",
                "Над ним луч солнца золотой…",
                "А он, мятежный, просит бури,",
                "Как будто в бурях есть покой!",
            ],
        ],
    },
    {
        "title": "Весенняя гроза",
        "author": "Фёдор Тютчев",
        "year": "1828",
        "stanzas": [
            [
                "Люблю грозу в начале мая,",
                "Когда весенний, первый гром,",
                "Как бы резвяся и играя,",
                "Грохочет в небе голубом.",
            ],
            [
                "Гремят раскаты молодые,",
                "Вот дождик брызнул, пыль летит,",
                "Повисли перлы дождевые,",
                "И солнце нити золотит.",
            ],
            [
                "С горы бежит поток проворный,",
                "В лесу не молкнет птичий гам,",
                "И гам лесной, и шум нагорный —",
                "Всё вторит весело громам.",
            ],
            [
                "Ты скажешь: ветреная Геба,",
                "Кормя Зевесова орла,",
                "Громокипящий кубок с неба,",
                "Смеясь, на землю пролила.",
            ],
        ],
    },
]


def load(key: str) -> dict:
    return json.loads((TEXTS / f"{key}.json").read_text(encoding="utf-8"))


def fb2_author_xml(author: str) -> str:
    parts = author.split()
    if len(parts) >= 2:
        first, last = " ".join(parts[:-1]), parts[-1]
        return f"<author><first-name>{escape(first)}</first-name><last-name>{escape(last)}</last-name></author>"
    return f"<author><nickname>{escape(author)}</nickname></author>"


def fb2_blocks(blocks: list[dict]) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block["kind"]
        text = block["text"]
        if kind == "p":
            out.append(f"<p>{escape(text)}</p>")
        elif kind == "epigraph":
            out.append(f"<epigraph><p>{escape(text)}</p></epigraph>")
        elif kind == "epigraph_author":
            out.append(f"<epigraph><p>{escape(text)}</p></epigraph>")
        elif kind == "verse":
            lines = text.split("\n")
            out.append("<poem><stanza>" + "".join(f"<v>{escape(line)}</v>" for line in lines) + "</stanza></poem>")
    return "\n".join(out)


def build_fb2(data: dict, cover_path: Path, annotation: str) -> bytes:
    cover_data = base64.b64encode(cover_path.read_bytes()).decode("ascii")
    authors = "".join(fb2_author_xml(a.strip()) for a in data["author"].split(","))
    sections: list[str] = []
    for index, chapter in enumerate(data["chapters"]):
        title = escape(chapter["title"])
        bodies = fb2_blocks(chapter["blocks"])
        sections.append(
            f'<section id="ch{index + 1}"><title><p>{title}</p></title>\n{bodies}\n</section>'
        )
    body = "\n".join(sections)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description>
<title-info>
<genre>prose_classic</genre>
{authors}
<book-title>{escape(data["title"])}</book-title>
<annotation><p>{escape(annotation)}</p></annotation>
<date value="{data.get("year", "")}">{data.get("year", "")}</date>
<coverpage><image l:href="#cover.jpg"/></coverpage>
<lang>ru</lang>
<src-lang>ru</src-lang>
</title-info>
<document-info>
<author><nickname>Читалка</nickname></author>
<program-used>Chitalka demo builder</program-used>
<date value="2026-11-07">2026</date>
<id>demo-{escape(data["title"])}</id>
<version>1.0</version>
</document-info>
</description>
<body>
{body}
</body>
<binary id="cover.jpg" content-type="image/jpeg">{cover_data}</binary>
</FictionBook>
"""
    return xml.encode("utf-8")


def build_epub(data: dict, cover_path: Path, annotation: str, target: Path) -> None:
    chapters = data["chapters"]
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        manifest = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="css" href="style.css" media-type="text/css"/>',
            '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
            '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        ]
        spine = ['<itemref idref="cover"/>']
        nav_items = []
        for index, chapter in enumerate(chapters):
            item_id = f"ch{index + 1}"
            manifest.append(
                f'<item id="{item_id}" href="{item_id}.xhtml" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="{item_id}"/>')
            nav_items.append(f'<li><a href="{item_id}.xhtml">{escape(chapter["title"])}</a></li>')

            body: list[str] = [f"<h1>{escape(chapter['title'])}</h1>"]
            for block in chapter["blocks"]:
                text = escape(block["text"])
                if block["kind"] == "p":
                    body.append(f"<p>{text}</p>")
                elif block["kind"] == "epigraph":
                    body.append(f'<blockquote class="epigraph"><p>{text}</p></blockquote>')
                elif block["kind"] == "epigraph_author":
                    body.append(f'<blockquote class="epigraph"><p class="author">{text}</p></blockquote>')
                elif block["kind"] == "verse":
                    lines = "<br/>".join(escape(line) for line in block["text"].split("\n"))
                    body.append(f'<div class="verse"><p>{lines}</p></div>')
            zf.writestr(
                f"OEBPS/{item_id}.xhtml",
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ru">\n'
                f"<head><title>{escape(chapter['title'])}</title>"
                '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
                f"<body>{''.join(body)}</body></html>",
            )

        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="book-id">demo-{escape(data["title"])}</dc:identifier>
<dc:title>{escape(data["title"])}</dc:title>
<dc:creator>{escape(data["author"])}</dc:creator>
<dc:language>ru</dc:language>
<dc:date>{data.get("year", "")}</dc:date>
<dc:subject>{escape(data.get("genre", ""))}</dc:subject>
<dc:description>{escape(annotation)}</dc:description>
<meta name="cover" content="cover-image"/>
</metadata>
<manifest>
{chr(10).join(manifest)}
</manifest>
<spine>
{chr(10).join(spine)}
</spine>
</package>
"""
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/style.css", EPUB_CSS)
        zf.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            "<head><title>Содержание</title></head><body>"
            '<nav epub:type="toc" id="toc"><h1>Содержание</h1><ol>'
            + "".join(nav_items)
            + "</ol></nav></body></html>",
        )
        zf.writestr(
            "OEBPS/cover.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Обложка</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
            '<body class="cover"><img src="images/cover.jpg" alt="Обложка"/></body></html>',
        )
        zf.write(cover_path, "OEBPS/images/cover.jpg")


EPUB_CSS = """
@charset "utf-8";
body { font-family: Georgia, serif; line-height: 1.55; margin: 0 7%; color: #2b2620; }
h1 { font-size: 1.6em; text-align: center; margin: 1.4em 0 1em; font-weight: normal; }
p { text-indent: 1.4em; margin: 0.25em 0; text-align: justify; }
blockquote.epigraph { margin: 1.2em 2em; font-style: italic; color: #5a4d3f; }
blockquote.epigraph p { text-indent: 0; text-align: right; }
blockquote.epigraph p.author { font-style: normal; font-size: 0.9em; }
div.verse p { text-indent: 0; margin-left: 2em; font-style: italic; text-align: left; }
body.cover { margin: 0; padding: 0; text-align: center; }
body.cover img { max-width: 100%; max-height: 100%; }
"""


def build_txt(data: dict, target: Path) -> None:
    lines: list[str] = [data["title"].upper(), data["author"], ""]
    for chapter in data["chapters"]:
        if chapter["title"] and chapter["title"].upper() != data["title"].upper():
            lines.extend([chapter["title"], ""])
        for block in chapter["blocks"]:
            text = block["text"]
            if block["kind"] == "verse":
                lines.extend(text.split("\n"))
                lines.append("")
            else:
                lines.extend([text, ""])
    text = "\r\n".join(lines)
    target.write_bytes(text.encode("cp1251", errors="replace"))


# ------------------------------------------------------------------------ PDF
def make_poetry_art(path: Path) -> None:
    """Простая акварельная иллюстрация для проверки картинок в книге."""
    width, height = 900, 560
    image = Image.new("RGB", (width, height), "#f2dfc0")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        top = (238, 207, 164)
        bottom = (196, 150, 112)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    draw.ellipse((620, 80, 790, 250), fill=(224, 160, 92))
    draw.ellipse((640, 100, 770, 230), fill=(240, 196, 128))
    draw.polygon([(0, 390), (180, 300), (360, 380), (560, 290), (900, 400),
                  (900, 560), (0, 560)], fill=(164, 128, 98))
    draw.polygon([(0, 450), (260, 380), (520, 440), (760, 370), (900, 430),
                  (900, 560), (0, 560)], fill=(112, 92, 80))
    for x in range(0, width, 12):
        draw.line((x, 500 + (x % 40) // 4, x + 6, 500 + (x % 40) // 4),
                  fill=(196, 166, 132), width=2)
    image.save(path, "JPEG", quality=90)


def make_poetry_fb2(cover: Path) -> bytes:
    art = ROOT / "data" / "covers" / "poems_art.jpg"
    make_poetry_art(art)
    sections: list[str] = []
    for index, poem in enumerate(POEMS):
        stanzas = "".join(
            "<stanza>" + "".join(f"<v>{escape(line)}</v>" for line in stanza) + "</stanza>"
            for stanza in poem["stanzas"]
        )
        note = ""
        if index == 1:
            note = ' <a l:href="#n1" type="note">[1]</a>'
        sections.append(
            f'<section id="poem{index + 1}"><title><p>{escape(poem["title"])}</p></title>'
            f"<epigraph><p>{escape(poem['author'])}</p><text-author>{escape(poem['year'])}</text-author></epigraph>"
            f"<poem>{stanzas}</poem>{note}</section>"
        )
    cover_data = base64.b64encode(cover.read_bytes()).decode("ascii")
    art_data = base64.b64encode(art.read_bytes()).decode("ascii")
    body = ''.join(sections)
    if len(sections) > 1:
        body = sections[0] + '<image l:href="#art.jpg"/>' + ''.join(sections[1:])
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description>
<title-info>
<genre>poetry</genre>
<author><first-name>Александр</first-name><last-name>Пушкин</last-name></author>
<author><first-name>Михаил</first-name><last-name>Лермонтов</last-name></author>
<author><first-name>Фёдор</first-name><last-name>Тютчев</last-name></author>
<book-title>Стихи о природе</book-title>
<annotation><p>Три хрестоматийных стихотворения русских поэтов о зиме, море и весенней грозе.</p></annotation>
<date value="1828-1841">1828–1841</date>
<coverpage><image l:href="#cover.jpg"/></coverpage>
<lang>ru</lang>
</title-info>
<document-info><author><nickname>Читалка</nickname></author><id>demo-poems</id><version>1.0</version></document-info>
</description>
<body>
{body}
</body>
<body name="notes">
<section id="n1"><title><p>1</p></title><p>Стихотворение «Парус» написано М. Ю. Лермонтовым в 1841 году.</p></section>
</body>
<binary id="cover.jpg" content-type="image/jpeg">{cover_data}</binary>
<binary id="art.jpg" content-type="image/jpeg">{art_data}</binary>
</FictionBook>
"""
    return xml.encode("utf-8")


def main() -> None:
    clean = "--clean" in sys.argv
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        "Пиковая дама.fb2",
        "Дама с собачкой.epub",
        "После бала.txt",
        "Лев Толстой - После бала.txt",
        "Стихи о природе.fb2.zip",
    ]
    if clean:
        for name in targets:
            (BOOKS_DIR / name).unlink(missing_ok=True)

    pik = load("pik")
    cover = Path(generate_cover("Пиковая дама", "Александр Пушкин", "Классическая проза"))
    (BOOKS_DIR / "Пиковая дама.fb2").write_bytes(
        build_fb2(
            pik,
            cover,
            "Последняя повесть Александра Пушкина: мистика карточной игры, тайна трёх карт и цена исполненного желания.",
        )
    )
    print("FB2 готов")

    dama = load("dama")
    cover = Path(generate_cover("Дама с собачкой", "Антон Чехов", "Классическая проза"))
    build_epub(
        dama,
        cover,
        "История поздней любви, начавшейся на набережной Ялты, — одна из самых тонких повестей Чехова.",
        BOOKS_DIR / "Дама с собачкой.epub",
    )
    print("EPUB готов")

    posle = load("posle")
    build_txt(posle, BOOKS_DIR / "Лев Толстой - После бала.txt")
    print("TXT готов")

    # Ионыч.pdf уже лежит в data/books и не пересобирается: генератор PDF
    # намеренно не тянет PyMuPDF (AGPL). Для новой PDF используйте отдельный
    # инструмент с подходящей лицензией.
    print("PDF оставлен без изменений")

    poetry_cover = Path(generate_cover("Стихи о природе", "Пушкин · Лермонтов · Тютчев", "Поэзия"))
    poetry = make_poetry_fb2(poetry_cover)
    with zipfile.ZipFile(BOOKS_DIR / "Стихи о природе.fb2.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Стихи о природе.fb2", poetry)
    print("FB2.ZIP готов")
    for file in sorted(BOOKS_DIR.iterdir()):
        print(f"  {file.name}: {file.stat().st_size / 1024:.0f} КБ")


if __name__ == "__main__":
    main()
