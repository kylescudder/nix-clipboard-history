"""Exercise the real GTK widget tree on Linux; run with tests/run-gtk-smoke.sh.

The clipboard transfer is stubbed here; Wayland integration is checked separately.
Screenshots are captured from the real X server, not a browser recreation.
"""

# GI versions must be selected before importing its namespaces.
# ruff: noqa: E402

import base64
import os
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from nix_clipboard_history.config import Appearance, Config
from nix_clipboard_history.gui import run
from nix_clipboard_history.store import Store
from nix_clipboard_history.theme import custom_css_path, stylesheet

case = os.environ.get("GTK_SMOKE_APPEARANCE", "default")
appearance = {
    "default": Appearance(),
    "light": Appearance(theme="light", accent_color="#0f766e", font_size=15, window_width=960),
    "compact": Appearance(
        accent_color="#a6e3a1",
        density="compact",
        font_size=12,
        border_radius=0,
        window_width=720,
        window_height=500,
        show_preview=False,
    ),
    "custom": Appearance(),
    "invalid": Appearance(),
}[case]
config = Config(appearance=appearance)
if case in ("custom", "invalid"):
    path = custom_css_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@define-color clipboard_fg #a6e3a1;\n.clipboard-window .heading { color: #ffe08a; }"
        if case == "custom"
        else ".shell { color: definitely-not-a-colour; }"
    )
snippet = b"""programs.nix-clipboard-history = {
  enable = true;
  settings = {
    max_items = 500;
    auto_paste = true;
  };
};"""
with Store(config=config) as store:
    pinned = store.add(snippet, "text", "kitty")
    store.pin(pinned)
    store.add(b"https://search.nixos.org/packages", "text", "firefox")
    store.add(b"nix develop --command python -m unittest discover -s tests", "text", "kitty")
    store.add(
        b"Design notes\n\nKeep it fast. Keep it quiet. Make the keyboard feel at home.",
        "text",
        "obsidian",
    )
    store.add(b"hello@example.com", "text", "firefox")
    store.add(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
        ),
        "image",
        "firefox",
    )

errors = []
copies = []


def window():
    return Gio.Application.get_default().get_active_window()


def initial():
    popup = window()
    assert popup.preview.get_visible() == appearance.show_preview
    assert popup.panel.has_css_class(appearance.density)
    assert Gtk.Settings.get_default().get_property("gtk-application-prefer-dark-theme") == (
        appearance.theme == "dark"
    )
    foreground = popup.get_color()
    expected = Gdk.RGBA()
    expected.parse("#a6e3a1" if case == "custom" else "#222838" if case == "light" else "#e7e9ef")
    assert foreground.equal(expected), (case, foreground.to_string(), expected.to_string())
    found, accent = popup.get_style_context().lookup_color("clipboard_accent")
    assert found
    if appearance.accent_color:
        expected.parse(appearance.accent_color)
        assert accent.equal(expected)
    # Every generated variant must be accepted by the real GTK CSS parser,
    # including font names containing CSS punctuation.
    for settings in (
        Appearance(),
        Appearance(theme="light"),
        Appearance(font_family='A "quoted" \\ font', font_size=24, border_radius=32),
    ):
        provider = Gtk.CssProvider()
        parse_errors = []
        provider.connect(
            "parsing-error", lambda _p, _s, error, errors=parse_errors: errors.append(str(error))
        )
        provider.load_from_data(stylesheet(settings).encode())
        assert not parse_errors, parse_errors
    assert len(popup.entries) == 6
    assert popup.current().pinned
    assert popup.text_view.get_buffer().get_char_count() == len(snippet)
    popup.key_pressed(None, Gdk.KEY_Down, 0, 0)
    assert not popup.current().pinned
    popup.key_pressed(None, Gdk.KEY_p, 0, Gdk.ModifierType.CONTROL_MASK)
    assert popup.current().pinned
    popup.pin()
    popup.tabs[2].set_active(True)
    assert len(popup.entries) == 1
    assert popup.preview_stack.get_visible_child_name() == "image"
    assert popup.picture.get_paintable() is not None
    popup.tabs[0].set_active(True)
    popup.search.set_text("keyboard home")


def search_found():
    popup = window()
    assert len(popup.entries) == 1
    assert popup.entries[0].source == "obsidian"
    popup.search.set_text("there-is-no-such-item")


def search_empty():
    popup = window()
    assert not popup.entries
    assert popup.stack.get_visible_child_name() == "empty"
    assert not popup.paste_button.get_sensitive()
    popup.search.set_text("")


def capture():
    popup = window()
    assert len(popup.entries) == 6
    popup.listbox.select_row(popup.rows[0])
    directory = Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "magick",
            "import",
            "-window",
            "Clipboard History",
            str(directory / ("clipboard.png" if case == "default" else f"clipboard-{case}.png")),
        ],
        check=True,
        timeout=10,
    )
    popup.pause()
    assert popup.store.paused
    popup.pause()
    assert not popup.store.paused
    popup.clear_history()
    assert popup.clear_armed
    assert len(popup.entries) == 6
    popup.clear_history()
    assert len(popup.entries) == 1 and popup.current().pinned
    popup.activate(copy_only=True)


steps = iter([initial, search_found, search_empty, capture])


def advance():
    try:
        next(steps)()
    except StopIteration:
        return False
    except BaseException:
        errors.append(traceback.format_exc())
        Gio.Application.get_default().quit()
        return False
    return True


GLib.timeout_add(500, advance)
GLib.timeout_add_seconds(
    20,
    lambda: (
        errors.append("GTK smoke test timed out"),
        Gio.Application.get_default().quit(),
        False,
    )[-1],
)
with patch(
    "nix_clipboard_history.gui.copy", side_effect=lambda data, mime: copies.append((data, mime))
):
    result = run(config, windowed=True)
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
assert result == 0
assert copies == [(snippet, "text/plain;charset=utf-8")]
print(f"GTK smoke passed ({case}): styles, navigation, search, filters, preview, pins, copy.")
