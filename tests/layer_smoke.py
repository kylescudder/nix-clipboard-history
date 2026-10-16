"""Open an actual Wayland layer surface and copy through wl-copy; called by wayland_smoke."""

# GI versions and library interposition must be selected before importing GTK.
# ruff: noqa: E402

import ctypes
import os
import traceback

ctypes.CDLL(os.environ["NIX_CLIPBOARD_LAYER_SHELL"], mode=ctypes.RTLD_GLOBAL)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gio, GLib, Gtk4LayerShell

from nix_clipboard_history.config import Config
from nix_clipboard_history.gui import run

errors = []


def check_popup():
    app = Gio.Application.get_default()
    try:
        popup = app.window
        assert Gtk4LayerShell.is_layer_window(popup)
        assert Gtk4LayerShell.get_namespace(popup) == "nix-clipboard-history"
        assert Gtk4LayerShell.get_keyboard_mode(popup) == Gtk4LayerShell.KeyboardMode.EXCLUSIVE
        assert popup.current().title == "resumed"
        popup.activate(copy_only=True)
    except BaseException:
        errors.append(traceback.format_exc())
        app.quit()
    return False


GLib.timeout_add(750, check_popup)
result = run(Config(), copy_only=True)
assert result == 0 and not errors, "\n".join(errors)
print("Layer-shell smoke passed: real overlay, keyboard focus, and copy from the popup.")
