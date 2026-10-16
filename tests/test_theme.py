import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nix_clipboard_history.config import Appearance, Config
from nix_clipboard_history.theme import accent_foreground, css_font, custom_css_path


class AppearanceTests(unittest.TestCase):
    def load(self, appearance):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"appearance": appearance}))
            return Config.load(path).appearance

    def test_existing_config_keeps_default_appearance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"max_items": 50}')
            config = Config.load(path)
            self.assertEqual(config.max_items, 50)
            self.assertEqual(config.appearance, Appearance())

    def test_partial_appearance_inherits_defaults(self):
        appearance = self.load({"theme": "light", "accent_color": "#a6E3a1"})
        self.assertEqual(appearance.theme, "light")
        self.assertEqual(appearance.accent_color, "#a6E3a1")
        self.assertEqual(appearance.window_width, 880)
        self.assertTrue(appearance.show_preview)

    def test_loads_layout_and_typography(self):
        values = {
            "density": "compact",
            "font_family": 'A "quoted" font',
            "monospace_font_family": "Fira Code",
            "font_size": 16,
            "border_radius": 0,
            "window_width": 1000,
            "window_height": 720,
            "show_preview": False,
        }
        appearance = self.load(values)
        for name, value in values.items():
            self.assertEqual(getattr(appearance, name), value)

    def test_rejects_invalid_values_before_opening_gtk(self):
        for values in (
            [],
            None,
            "dark",
            {"typo": 1},
            {"theme": "unknown"},
            {"theme": 1},
            {"density": "tiny"},
            {"show_preview": "false"},
            {"accent_color": "red"},
            {"accent_color": "#12345g"},
            {"accent_color": "#123456; color: red"},
            {"font_family": " "},
            {"monospace_font_family": "font\nname"},
            {"font_size": True},
            {"font_size": 13.5},
            {"font_size": 9},
            {"font_size": 25},
            {"border_radius": -1},
            {"border_radius": 33},
            {"window_width": 599},
            {"window_width": 1601},
            {"window_height": 399},
            {"window_height": 1201},
        ):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "appearance"):
                self.load(values)

    def test_accent_button_text_uses_contrasting_colour(self):
        self.assertEqual(accent_foreground("#ffffff"), "#000000")
        self.assertEqual(accent_foreground("#a6e3a1"), "#000000")
        self.assertEqual(accent_foreground("#000000"), "#ffffff")
        self.assertEqual(accent_foreground("#365ad6"), "#ffffff")

    def test_font_names_are_quoted_as_one_css_string(self):
        self.assertEqual(css_font('A "font"\\name'), '"A \\"font\\"\\\\name"')

    def test_custom_styles_follow_xdg_config_home(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/clipboard-config"}):
            self.assertEqual(
                custom_css_path(), Path("/tmp/clipboard-config/nix-clipboard-history/style.css")
            )
