from __future__ import annotations

import pytest

from chitalka import dictionary


def test_single_word_translates_offline():
    value, origin = dictionary.translate("дама", "ru", "en", with_source=True)
    assert value
    assert origin in {"офлайн", "кэш"}


def test_phrases_are_blocked_without_provider():
    with pytest.raises(dictionary.DictionaryError) as exc:
        dictionary.translate("Пиковая дама означает", "ru", "en")
    assert "не настроен" in str(exc.value).lower()


def test_provider_validation_does_not_touch_network():
    with pytest.raises(dictionary.DictionaryError) as exc:
        dictionary.translate("hello world", "en", "ru", provider="deepl")
    assert "ключ" in str(exc.value).lower()

    with pytest.raises(dictionary.DictionaryError) as exc:
        dictionary.translate("hello world", "en", "ru", provider="libre")
    assert "libre" in str(exc.value).lower()


def test_language_detection():
    assert dictionary.detect_language("Привет") == "ru"
    assert dictionary.detect_language("hello") == "en"
