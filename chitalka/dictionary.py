"""Словарь и перевод по выделенному тексту (открытые API)."""

from __future__ import annotations

import html
import json
import re
import urllib.parse

from . import opds

USER_AGENT = opds.USER_AGENT
_CACHE: dict[tuple, dict] = {}


class DictionaryError(Exception):
    pass


def detect_language(text: str) -> str:
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    return "ru" if cyrillic >= latin else "en"


def language_name(code: str) -> str:
    return {"ru": "русский", "en": "английский"}.get(code, code)


def normalize_word(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^[^\wА-Яа-яЁё-]+|[^\wА-Яа-яЁё-]+$", "", text, flags=re.UNICODE)
    return text


def first_word(text: str) -> str:
    match = re.search(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё-]*", text or "")
    return match.group(0) if match else ""


def _fetch_json(url: str, max_bytes: int = 3 * 1024 * 1024) -> dict | list:
    data, _, _ = opds.fetch(
        url, max_bytes=max_bytes, accept="application/json, */*;q=0.5", timeout=20,
    )
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DictionaryError(f"Сервис вернул не JSON: {exc}") from exc


def translate(text: str, source: str, target: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise DictionaryError("Нет текста для перевода")
    if source == target:
        return text
    query = text[:500]
    key = ("translate", query, source, target)
    if key in _CACHE:
        return _CACHE[key]["text"]
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({
        "q": query,
        "langpair": f"{source}|{target}",
    })
    try:
        payload = _fetch_json(url)
        result = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
        result = html.unescape(result)
        if not result or "MYMEMORY WARNING" in result.upper():
            raise DictionaryError("Переводчик не вернул результат")
    except Exception:
        # Резервный открытый endpoint Google Translate.
        try:
            url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
                "client": "gtx", "sl": source, "tl": target, "dt": "t", "q": query,
            })
            payload = _fetch_json(url)
            result = "".join(
                str(piece[0]) for piece in (payload[0] or []) if piece and piece[0]
            ).strip()
        except Exception as exc:  # noqa: BLE001
            raise DictionaryError(f"Не удалось перевести: {exc}") from exc
        if not result:
            raise DictionaryError("Переводчик не вернул результат")
    _CACHE[key] = {"text": result}
    return result


def _english_dictionary(word: str) -> dict:
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    payload = _fetch_json(url)
    definitions: list[str] = []
    phonetic = ""
    if isinstance(payload, list):
        for entry in payload[:2]:
            if not phonetic:
                phonetic = str(entry.get("phonetic") or "")
            for meaning in entry.get("meanings") or []:
                part = meaning.get("partOfSpeech") or ""
                for item in (meaning.get("definitions") or [])[:5]:
                    definition = " ".join(str(item.get("definition") or "").split())
                    example = " ".join(str(item.get("example") or "").split())
                    if definition:
                        line = (f"{part}. " if part else "") + definition
                        if example:
                            line += f"  — {example}"
                        definitions.append(line)
            if definitions:
                break
    if not definitions:
        raise DictionaryError("Слово не найдено")
    return {
        "word": word,
        "language": "en",
        "phonetic": phonetic,
        "definitions": definitions[:8],
        "url": "https://en.wiktionary.org/wiki/" + urllib.parse.quote(word),
    }


def _wiktionary_search_title(word: str, language: str) -> str:
    host = "ru.wiktionary.org" if language == "ru" else "en.wiktionary.org"
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": word,
        "srlimit": "5",
        "format": "json",
        "formatversion": "2",
    })
    payload = _fetch_json(url)
    results = ((payload.get("query") or {}).get("search") or [])
    for item in results:
        title = str(item.get("title") or "")
        if title.lower() == word.lower():
            return title
    for item in results:
        title = str(item.get("title") or "")
        if title and not title.lower().startswith("категория:"):
            return title
    return ""


def _wiktionary_dictionary(word: str, language: str, title: str | None = None) -> dict:
    host = "ru.wiktionary.org" if language == "ru" else "en.wiktionary.org"
    page_title = title or word
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "prop": "extracts",
        "explaintext": "1",
        "titles": page_title,
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    })
    payload = _fetch_json(url)
    pages = ((payload.get("query") or {}).get("pages") or [])
    if not pages:
        raise DictionaryError("Статья не найдена")
    page = pages[0]
    extract = str(page.get("extract") or "").strip()
    if page.get("missing") or not extract:
        if title is None:
            found = _wiktionary_search_title(word, language)
            if found and found.lower() != word.lower():
                return _wiktionary_dictionary(word, language, title=found)
        raise DictionaryError("В словаре нет статьи")
    lines = []
    for line in extract.splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        if re.match(r"^=+.*=+$", line) or line.startswith("--"):
            continue
        if line.startswith("Материал из Викисловаря"):
            continue
        lines.append(line)
        if sum(len(item) for item in lines) > 2400:
            break
    if not lines:
        raise DictionaryError("Не удалось прочитать статью")
    return {
        "word": page.get("title") or word,
        "language": language,
        "phonetic": "",
        "definitions": lines,
        "url": f"https://{host}/wiki/" + urllib.parse.quote(word),
    }


def lookup(text: str, language: str | None = None) -> dict:
    word = first_word(normalize_word(text))
    if not word:
        raise DictionaryError("Выделите слово")
    language = language or detect_language(word)
    key = ("lookup", word.lower(), language)
    if key in _CACHE:
        return _CACHE[key]
    result: dict
    if language == "en":
        try:
            result = _english_dictionary(word)
        except Exception:
            result = _wiktionary_dictionary(word, "en")
    else:
        result = _wiktionary_dictionary(word, language)
    _CACHE[key] = result
    return result


def source_pair(text: str) -> tuple[str, str]:
    source = detect_language(text)
    target = "en" if source == "ru" else "ru"
    return source, target
