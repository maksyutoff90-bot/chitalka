"""Словарь и перевод по выделенному тексту (офлайн + открытые API)."""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request

from . import offline_dict, opds

USER_AGENT = opds.USER_AGENT
_CACHE: dict[tuple, str | dict] = {}


def _cache_key(kind: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{kind}:{digest}"


def _cache_read(cache, key: str) -> str | None:
    if cache is None:
        return None
    try:
        return cache.cache_get(key)
    except Exception:
        return None


def _cache_write(cache, key: str, value: str) -> None:
    if cache is None:
        return
    try:
        cache.cache_set(key, value)
    except Exception:
        pass


def _offline_translation(local: dict, target: str) -> str:
    """Берём из словарной статьи строку на языке перевода."""
    fallback = ""
    for definition in local.get("definitions") or []:
        for line in str(definition).splitlines():
            line = " ".join(line.split())
            if not line or line.startswith("/"):
                continue
            if line.lower() in {
                "noun", "verb", "adjective", "adverb", "pronoun",
                "preposition", "conjunction", "interjection", "numeral",
            }:
                continue
            if not fallback:
                fallback = line
            has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", line))
            has_latin = bool(re.search(r"[A-Za-z]", line))
            if target == "en" and has_latin and not has_cyrillic:
                return line[:300]
            if target == "ru" and has_cyrillic:
                return line[:300]
    return fallback[:300]


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


def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict | list:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(3 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        raise DictionaryError(f"Переводчик недоступен: {exc}") from exc
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DictionaryError(f"Переводчик вернул не JSON: {exc}") from exc


def _post_form(url: str, payload: dict, headers: dict | None = None) -> dict | list:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(3 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        raise DictionaryError(f"Переводчик недоступен: {exc}") from exc
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DictionaryError(f"Переводчик вернул не JSON: {exc}") from exc


def translate(text: str, source: str, target: str, *, cache=None,
              with_source: bool = False, provider: str = "offline",
              endpoint: str = "", api_key: str = "", email: str = ""):
    text = " ".join((text or "").split())
    if not text:
        raise DictionaryError("Нет текста для перевода")
    if source == target:
        return (text, "без перевода") if with_source else text
    query = text[:500]
    provider = (provider or "offline").lower()
    cache_key = _cache_key(
        "translate", f"{provider}|{endpoint}|{source}|{target}|{query.lower()}"
    )
    cached = _cache_read(cache, cache_key)
    if cached:
        return (cached, "кэш") if with_source else cached
    memory_key = ("translate", provider, endpoint, query, source, target)
    memory = _CACHE.get(memory_key)
    if memory:
        return (str(memory), "кэш") if with_source else str(memory)

    # Одно слово переводим по офлайн-словарю сразу, не дожидаясь сети.
    if len(query.split()) == 1:
        local = offline_dict.offline_lookup(normalize_word(query), source)
        if local:
            offline_result = _offline_translation(local, target)
            if offline_result:
                _CACHE[memory_key] = offline_result
                _cache_write(cache, cache_key, offline_result)
                return (offline_result, "офлайн") if with_source else offline_result

    if provider in ("", "offline", "none"):
        raise DictionaryError(
            "Онлайн-перевод не настроен. Одиночные слова переводятся офлайн; "
            "для фраз выберите DeepL или LibreTranslate в настройках перевода."
        )

    result = ""
    origin = "онлайн"
    try:
        if provider == "deepl":
            if not api_key:
                raise DictionaryError("Для DeepL нужен API-ключ")
            url = endpoint or "https://api-free.deepl.com/v2/translate"
            payload = _post_form(
                url,
                {
                    "text": query,
                    "source_lang": source.upper(),
                    "target_lang": target.upper(),
                },
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            )
            translations = payload.get("translations") or []
            result = str(translations[0].get("text") or "").strip() if translations else ""
            origin = "DeepL"
        elif provider == "libre":
            if not endpoint:
                raise DictionaryError("Укажите адрес LibreTranslate")
            url = endpoint.rstrip("/")
            if not url.endswith("/translate"):
                url += "/translate"
            payload = _post_json(
                url,
                {"q": query, "source": source, "target": target, "format": "text",
                 **({"api_key": api_key} if api_key else {})},
            )
            result = str(payload.get("translatedText") or "").strip()
            origin = "LibreTranslate"
        elif provider == "mymemory":
            url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({
                "q": query,
                "langpair": f"{source}|{target}",
                **({"de": email} if email else {}),
            })
            payload = _fetch_json(url)
            result = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
            result = html.unescape(result)
            origin = "MyMemory"
        else:
            raise DictionaryError(f"Неизвестный переводчик: {provider}")
        if not result or "MYMEMORY WARNING" in result.upper():
            raise DictionaryError("Переводчик не вернул результат")
    except Exception as exc:  # noqa: BLE001
        local = None
        if len(query.split()) == 1:
            local = offline_dict.offline_lookup(normalize_word(query), source)
        if local:
            fallback = _offline_translation(local, target)
            if fallback:
                result = fallback
                origin = "офлайн"
        if not result:
            raise DictionaryError(str(exc) if str(exc) else "Не удалось перевести") from exc

    _CACHE[memory_key] = result
    _cache_write(cache, cache_key, result)
    return (result, origin) if with_source else result


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


def lookup(text: str, language: str | None = None, *, cache=None) -> dict:
    word = first_word(normalize_word(text))
    if not word:
        raise DictionaryError("Выделите слово")
    language = language or detect_language(word)
    local = offline_dict.offline_lookup(word, language)
    if local:
        local["source"] = "FreeDict · офлайн"
        return local
    cache_key = _cache_key("lookup", f"{language}|{word.lower()}")
    cached = _cache_read(cache, cache_key)
    if cached:
        try:
            result = json.loads(cached)
            source = str(result.get("source") or "словарь")
            if "кэш" not in source:
                result["source"] = source + " · кэш"
            return result
        except Exception:
            pass
    memory_key = ("lookup", word.lower(), language)
    memory = _CACHE.get(memory_key)
    if isinstance(memory, dict):
        return memory
    result: dict
    if language == "en":
        try:
            result = _english_dictionary(word)
            result["source"] = "dictionaryapi.dev"
        except Exception:
            result = _wiktionary_dictionary(word, "en")
            result["source"] = "Wiktionary"
    else:
        result = _wiktionary_dictionary(word, language)
        result["source"] = "Wiktionary"
    _CACHE[memory_key] = result
    _cache_write(cache, cache_key, json.dumps(result, ensure_ascii=False))
    return result


def source_pair(text: str) -> tuple[str, str]:
    source = detect_language(text)
    target = "en" if source == "ru" else "ru"
    return source, target


def offline_stats() -> dict:
    return offline_dict.offline_stats()


def offline_last_error() -> str:
    return offline_dict.offline_last_error()
