"""Проверка обновлений через GitHub Releases."""

from __future__ import annotations

import json
import re
import urllib.request

REPO = "maksyutoff90-bot/chitalka"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


def _version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", (value or "").lstrip("vV"))
    return tuple(int(part) for part in numbers[:4]) or (0,)


def check_latest(current: str) -> dict | None:
    request = urllib.request.Request(
        API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Chitalka-update-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(f"Не удалось проверить обновления: {exc}") from exc
    tag = str(payload.get("tag_name") or "")
    url = str(payload.get("html_url") or "")
    if not tag or not url:
        return None
    if _version(tag) <= _version(current):
        return None
    return {
        "version": tag,
        "url": url,
        "name": str(payload.get("name") or tag),
        "published_at": str(payload.get("published_at") or ""),
    }
