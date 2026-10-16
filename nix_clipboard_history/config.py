"""Small, dependency-free configuration shared by the service and popup."""

from __future__ import annotations

import json
import os
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
class Config:
    max_items: int = 500
    retention_days: int = 30
    max_item_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    auto_paste: bool = True
    paste_delay_ms: int = 160
    capture_images: bool = True
    excluded_apps: list[str] = field(default_factory=list)
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
        for key, value in values.items():
            default = getattr(cls(), key)
            if type(value) is not type(default):
                raise ValueError(f"{key} must be a {type(default).__name__}")
            if isinstance(value, list) and any(not isinstance(v, str) for v in value):
                raise ValueError(f"{key} must contain only strings")
            if type(value) is int and value < (0 if key == "paste_delay_ms" else 1):
                raise ValueError(f"{key} is too small")
        if values.get("paste_delay_ms", 160) > 5000:
            raise ValueError("paste_delay_ms must be at most 5000")
        return cls(**values)
