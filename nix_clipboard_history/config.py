"""Small, dependency-free configuration shared by the service and popup."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

APP_NAME = "nix-clipboard-history"


def config_path() -> Path:
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME / "config.json"
    )


def data_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_NAME


@dataclass
class Appearance:
    theme: str = "dark"
    accent_color: str = ""
    font_family: str = "Inter"
    monospace_font_family: str = "JetBrains Mono"
    font_size: int = 13
    density: str = "comfortable"
    border_radius: int = 18
    window_width: int = 880
    window_height: int = 640
    show_preview: bool = True

    @classmethod
    def from_dict(cls, values: dict) -> Appearance:
        if not isinstance(values, dict):
            raise ValueError("appearance must be a JSON object")
        defaults = cls()
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown appearance setting(s): {', '.join(sorted(unknown))}")
        for key, value in values.items():
            default = getattr(defaults, key)
            if type(value) is not type(default):
                raise ValueError(f"appearance.{key} must be a {type(default).__name__}")
        appearance = cls(**values)
        if appearance.theme not in ("dark", "light"):
            raise ValueError("appearance.theme must be dark or light")
        if appearance.density not in ("comfortable", "compact"):
            raise ValueError("appearance.density must be comfortable or compact")
        if appearance.accent_color and not re.fullmatch(
            r"#[0-9a-fA-F]{6}", appearance.accent_color
        ):
            raise ValueError("appearance.accent_color must be empty or a #RRGGBB colour")
        for key in ("font_family", "monospace_font_family"):
            value = getattr(appearance, key)
            if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError(f"appearance.{key} must be a nonempty font name without controls")
        for key, low, high in (
            ("font_size", 10, 24),
            ("border_radius", 0, 32),
            ("window_width", 600, 1600),
            ("window_height", 400, 1200),
        ):
            if not low <= getattr(appearance, key) <= high:
                raise ValueError(f"appearance.{key} must be between {low} and {high}")
        return appearance


@dataclass
class Config:
    max_items: int = 500
    retention_days: int = 30
    max_item_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    auto_paste: bool = True
    paste_delay_ms: int = 160
    capture_images: bool = True
    excluded_apps: list[str] = field(default_factory=list)
    appearance: Appearance = field(default_factory=Appearance)
    terminal_classes: list[str] = field(
        default_factory=lambda: [
            "kitty",
            "Alacritty",
            "foot",
            "footclient",
            "org.wezfurlong.wezterm",
            "com.mitchellh.ghostty",
            "Ghostty",
            "org.gnome.Terminal",
            "org.gnome.Console",
            "konsole",
            "com.raggesilver.BlackBox",
            "xterm",
            "st-256color",
        ]
    )

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        if not path.exists():
            return cls()
        try:
            values = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise ValueError(f"Cannot read {path}: {error}") from error
        if not isinstance(values, dict):
            raise ValueError(f"{path} must contain a JSON object")
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
        defaults = cls()
        for key, value in values.items():
            if key == "appearance":
                values[key] = Appearance.from_dict(value)
                continue
            default = getattr(defaults, key)
            if type(value) is not type(default):
                raise ValueError(f"{key} must be a {type(default).__name__}")
            if isinstance(value, list) and any(not isinstance(v, str) for v in value):
                raise ValueError(f"{key} must contain only strings")
            if type(value) is int and value < (0 if key == "paste_delay_ms" else 1):
                raise ValueError(f"{key} is too small")
        if values.get("paste_delay_ms", 160) > 5000:
            raise ValueError("paste_delay_ms must be at most 5000")
        return cls(**values)
