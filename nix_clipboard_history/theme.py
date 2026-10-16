"""Build GTK CSS without importing GTK in the service or capture helper."""

from __future__ import annotations

from pathlib import Path
from string import Template

from .config import Appearance, config_path

PALETTES = {
    "dark": {
        "bg": "#17191f",
        "preview_bg": "#14171d",
        "fg": "#e7e9ef",
        "muted": "#8f95a6",
        "subtle": "#7e8aa3",
        "border": "#353842",
        "divider": "#2c303a",
        "input_bg": "#20232b",
        "hover_bg": "#222630",
        "icon_bg": "#252b38",
        "scrollbar": "#3b4150",
        "accent": "#b8c8ff",
        "danger": "#ff9aab",
        "danger_bg": "#492735",
    },
    "light": {
        "bg": "#f8f9fc",
        "preview_bg": "#f0f2f7",
        "fg": "#222838",
        "muted": "#596479",
        "subtle": "#647087",
        "border": "#cbd1dd",
        "divider": "#dce0e9",
        "input_bg": "#ffffff",
        "hover_bg": "#e8ecf4",
        "icon_bg": "#e3e8f2",
        "scrollbar": "#b3bdcf",
        "accent": "#365ad6",
        "danger": "#a32142",
        "danger_bg": "#fbe4ea",
    },
}


def custom_css_path() -> Path:
    return config_path().with_name("style.css")


def css_font(name: str) -> str:
    # Treat a font name as one CSS string, including quotes and backslashes.
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def accent_foreground(colour: str) -> str:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else "#ffffff"


def stylesheet(appearance: Appearance) -> str:
    palette = {**PALETTES[appearance.theme]}
    if appearance.accent_color:
        palette["accent"] = appearance.accent_color
    palette["accent_fg"] = accent_foreground(palette["accent"])
    colours = "\n".join(f"@define-color clipboard_{key} {value};" for key, value in palette.items())
    sizes = {
        f"font_{size}": f"{size * appearance.font_size / 13:g}px"
        for size in (9, 10, 11, 12, 13, 14, 15, 19)
    }
    template = Template(Path(__file__).with_name("style.css").read_text())
    css = template.substitute(
        sizes,
        font_family=css_font(appearance.font_family),
        monospace_font_family=css_font(appearance.monospace_font_family),
        border_radius=f"{appearance.border_radius}px",
    )
    return colours + "\n" + css
