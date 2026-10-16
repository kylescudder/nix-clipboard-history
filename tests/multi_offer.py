"""Own one real multi-format clipboard offer for wayland_smoke.py."""

# ruff: noqa: E402
import base64
import json
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

specification, ready_name = sys.argv[1:]
offers = json.loads(specification)
application = Gtk.Application(
    application_id="io.github.clipboard.MultiOfferTest", flags=Gio.ApplicationFlags.NON_UNIQUE
)


def publish(window):
    providers = [
        Gdk.ContentProvider.new_for_bytes(mime, GLib.Bytes.new(base64.b64decode(data)))
        for mime, data in offers
    ]
    provider = Gdk.ContentProvider.new_union(providers)
    assert window.get_display().get_clipboard().set_content(provider)
    window.get_display().flush()
    Path(ready_name).touch()
    return False


def activate(app):
    window = Gtk.ApplicationWindow(application=app, title="Multi-format clipboard source")
    window.set_child(Gtk.Label(label="Clipboard capture test"))
    keys = Gtk.EventControllerKey.new()
    keys.connect("key-released", lambda *_: publish(window))
    window.add_controller(keys)
    window.present()
    GLib.timeout_add(300, lambda: (Path(ready_name + ".mapped").touch(), False)[1])


application.connect("activate", activate)
raise SystemExit(application.run([]))
