"""Палитры интерфейса и темы чтения."""

from __future__ import annotations

from dataclasses import dataclass

UI_FONT = "Segoe UI"
SERIF_FONT = "Georgia"


@dataclass(frozen=True)
class Palette:
    bg: str
    panel: str
    card: str
    card_hover: str
    border: str
    border_light: str
    text: str
    muted: str
    dim: str
    accent: str
    accent_soft: str
    accent_text: str
    header: str
    chip: str
    chip_active: str
    chip_text: str
    shadow: str
    success: str
    warning: str
    danger: str
    scroll: str


DARK = Palette(
    bg="#12100e",
    panel="#191613",
    card="#211d19",
    card_hover="#2a241f",
    border="#302a24",
    border_light="#3d352d",
    text="#f2ece3",
    muted="#a2978a",
    dim="#6f665c",
    accent="#c87941",
    accent_soft="#3a2a1e",
    accent_text="#fff6ec",
    header="#161311",
    chip="#241f1a",
    chip_active="#c87941",
    chip_text="#e7dfd4",
    shadow="#000000",
    success="#7fa37a",
    warning="#d6a35c",
    danger="#c96a5b",
    scroll="#4a4036",
)

LIGHT = Palette(
    bg="#f4efe6",
    panel="#fbf8f2",
    card="#ffffff",
    card_hover="#fffaf1",
    border="#e4dbcd",
    border_light="#d6caba",
    text="#2b2620",
    muted="#7b7062",
    dim="#a49785",
    accent="#a9522a",
    accent_soft="#f6e3d5",
    accent_text="#ffffff",
    header="#f8f3ea",
    chip="#ece4d6",
    chip_active="#a9522a",
    chip_text="#3a332b",
    shadow="#c9bfae",
    success="#4d7a47",
    warning="#a8762c",
    danger="#a94a3c",
    scroll="#c3b7a5",
)


@dataclass(frozen=True)
class ReadingTheme:
    key: str
    name: str
    page: str
    text: str
    muted: str
    accent: str
    desk: str
    rule: str
    shadow: str
    is_dark: bool


READING_THEMES: dict[str, ReadingTheme] = {
    "paper": ReadingTheme(
        key="paper",
        name="Бумага",
        page="#fcf8f0",
        text="#2b2620",
        muted="#8a7f70",
        accent="#a9522a",
        desk="#e8dfd1",
        rule="#e6dccb",
        shadow="#c9bdaa",
        is_dark=False,
    ),
    "sepia": ReadingTheme(
        key="sepia",
        name="Сепия",
        page="#f3e5c6",
        text="#4b3a26",
        muted="#94805f",
        accent="#9a5c2f",
        desk="#ddcdab",
        rule="#e2d0ad",
        shadow="#bda986",
        is_dark=False,
    ),
    "graphite": ReadingTheme(
        key="graphite",
        name="Графит",
        page="#1b1e22",
        text="#cbc7bf",
        muted="#7f858d",
        accent="#d69a63",
        desk="#0d0f11",
        rule="#2b3037",
        shadow="#000000",
        is_dark=True,
    ),
    "night": ReadingTheme(
        key="night",
        name="Ночь",
        page="#0e1218",
        text="#94a3b5",
        muted="#5e6b7c",
        accent="#b98a5e",
        desk="#05070a",
        rule="#1a212b",
        shadow="#000000",
        is_dark=True,
    ),
}


def reading_theme(key: str) -> ReadingTheme:
    return READING_THEMES.get(key, READING_THEMES["paper"])


def palette(ui_theme: str) -> Palette:
    return LIGHT if ui_theme == "light" else DARK
