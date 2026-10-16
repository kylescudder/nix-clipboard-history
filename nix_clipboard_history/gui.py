"""GTK4 popup. Import GI only when opening the UI, keeping capture helpers lightweight."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import Config
from .store import Entry, Store
from .wayland import active_window, copy, focused_monitor, paste, restore_focus


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def relative_time(timestamp: float) -> str:
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def run(config: Config, copy_only: bool = False, windowed: bool = False) -> int:
    if not windowed:
        try:
            ctypes.CDLL(
                os.environ.get("NIX_CLIPBOARD_LAYER_SHELL", "libgtk4-layer-shell.so.0"),
                mode=ctypes.RTLD_GLOBAL,
            )
        except OSError as error:
            raise RuntimeError(
                "gtk4-layer-shell is missing. Launch through the Nix package."
            ) from error

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

    layer = None
    if not windowed:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell

        layer = Gtk4LayerShell

    target = active_window()

    def label(text: str = "", css: str = "", **kwargs):
        widget = Gtk.Label(label=text, xalign=0, **kwargs)
        if css:
            widget.add_css_class(css)
        return widget

    def button(icon: str, tooltip: str, callback, css: str = "icon-button"):
        widget = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
        widget.add_css_class(css)
        widget.connect("clicked", callback)
        return widget

    def brand_mark(size: int):
        file = Gio.File.new_for_path(str(Path(__file__).with_name("logo.svg")))
        widget = Gtk.Image.new_from_gicon(Gio.FileIcon.new(file))
        widget.set_pixel_size(size)
        widget.set_accessible_role(Gtk.AccessibleRole.IMG)
        widget.update_property([Gtk.AccessibleProperty.LABEL], ["Clipboard History"])
        return widget

    class Popup(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Clipboard History")
            self.store = Store(config=config)
            self.store.prune()
            self.kind = "all"
            self.entries = []
            self.rows = []
            self.busy = False
            self.closed = False
            self.shields = []
            self.pending_activation = None
            self.selection_timeout = 0
            self.clear_armed = False
            self.clear_timeout = 0
            self.search_timeout = 0
            self.paste_on_select = config.auto_paste and not copy_only
            self.set_decorated(False)
            self.add_css_class("clipboard-window")
            display = Gdk.Display.get_default()
            if display is None:
                raise RuntimeError("No graphical display is available")
            provider = Gtk.CssProvider()
            provider.load_from_path(str(Path(__file__).with_name("style.css")))
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            settings = Gtk.Settings.get_default()
            settings.set_property("gtk-application-prefer-dark-theme", True)
            width, height = 880, 640
            monitors = display.get_monitors()
            monitor = monitors.get_item(0) if monitors.get_n_items() else None
            if layer and monitors.get_n_items() > 1:
                connector = focused_monitor()
                monitor = next((m for m in monitors if m.get_connector() == connector), monitor)
            if monitor:
                geometry = monitor.get_geometry()
                width, height = min(width, geometry.width - 48), min(height, geometry.height - 64)
            if layer:
                if not layer.is_supported():
                    raise RuntimeError("This compositor does not support layer-shell; use Hyprland")
                self.configure_layer(self, monitor)
                layer.set_keyboard_mode(self, layer.KeyboardMode.EXCLUSIVE)
            else:
                self.set_default_size(width, height)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.panel = root
            root.add_css_class("shell")
            if layer:
                # A layer surface owns no input outside its bounds. Fill the output
                # transparently so clicks around the centered panel can dismiss it.
                backdrop = Gtk.Overlay()
                backdrop.set_child(self.click_shield())
                root.set_size_request(width, height)
                root.set_halign(Gtk.Align.CENTER)
                root.set_valign(Gtk.Align.CENTER)
                backdrop.add_overlay(root)
                self.set_child(backdrop)
                for other in monitors:
                    if other == monitor:
                        continue
                    shield = Gtk.ApplicationWindow(application=app, decorated=False)
                    shield.add_css_class("clipboard-window")
                    self.configure_layer(shield, other)
                    layer.set_keyboard_mode(shield, layer.KeyboardMode.NONE)
                    shield.set_child(self.click_shield())
                    self.shields.append(shield)
                    shield.present()
            else:
                self.set_child(root)
            header = Gtk.Box(spacing=12)
            header.add_css_class("header")
            logo = brand_mark(44)
            logo.add_css_class("brand-icon")
            header.append(logo)
            heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            heading.append(label("Clipboard", "heading"))
            heading.append(label("A little memory for everything you copy.", "muted"))
            heading.set_hexpand(True)
            header.append(heading)
            self.pause_button = button("media-playback-pause-symbolic", "Pause capture", self.pause)
            header.append(self.pause_button)
            header.append(button("window-close-symbolic", "Close · Esc", lambda *_: self.close()))
            root.append(header)

            search_box = Gtk.Box(spacing=10)
            search_box.add_css_class("search-box")
            search_box.append(Gtk.Image.new_from_icon_name("system-search-symbolic"))
            self.search = Gtk.Entry(placeholder_text="Search your clipboard…", hexpand=True)
            self.search.add_css_class("search-entry")
            self.search.connect("changed", self.search_changed)
            search_box.append(self.search)
            search_box.append(label("ESC", "keycap"))
            root.append(search_box)

            toolbar = Gtk.Box(spacing=5)
            toolbar.add_css_class("toolbar")
            self.tabs = []
            for text, kind in [
                ("All", "all"),
                ("Text & links", "text"),
                ("Images", "image"),
                ("Pinned", "pinned"),
            ]:
                tab = Gtk.ToggleButton(label=text)
                tab.add_css_class("filter")
                if self.tabs:
                    tab.set_group(self.tabs[0])
                else:
                    tab.set_active(True)
                tab.connect("toggled", self.change_filter, kind)
                self.tabs.append(tab)
                toolbar.append(tab)
            spacer = Gtk.Box(hexpand=True)
            toolbar.append(spacer)
            self.count = label(css="muted")
            toolbar.append(self.count)
            root.append(toolbar)

            content = Gtk.Box(vexpand=True, homogeneous=True)
            content.add_css_class("content")
            root.append(content)
            self.stack = Gtk.Stack()
            self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            self.listbox.set_activate_on_single_click(False)
            self.listbox.add_css_class("history-list")
            self.listbox.connect("row-selected", self.selected)
            self.listbox.connect("row-activated", lambda *_: self.activate())
            self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            self.scroll.set_child(self.listbox)
            self.stack.add_named(self.scroll, "list")
            empty = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=12,
                valign=Gtk.Align.CENTER,
                halign=Gtk.Align.CENTER,
            )
            empty_icon = brand_mark(64)
            empty_icon.add_css_class("empty-logo")
            empty.append(empty_icon)
            self.empty_title = label("Your clipboard starts here", "empty-title")
            self.empty_hint = label(
                "Copy some text or an image to get started.", "muted", wrap=True
            )
            self.empty_hint.set_max_width_chars(30)
            self.empty_hint.set_justify(Gtk.Justification.CENTER)
            empty.append(self.empty_title)
            empty.append(self.empty_hint)
            self.stack.add_named(empty, "empty")
            content.append(self.stack)

            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            preview.add_css_class("preview")
            content.append(preview)
            preview.append(label("PREVIEW", "eyebrow"))
            self.preview_stack = Gtk.Stack(vexpand=True)
            self.text_view = Gtk.TextView(
                editable=False,
                cursor_visible=False,
                wrap_mode=Gtk.WrapMode.WORD_CHAR,
                monospace=True,
            )
            self.text_view.add_css_class("text-preview")
            text_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            text_scroll.set_child(self.text_view)
            self.preview_stack.add_named(text_scroll, "text")
            self.picture = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True)
            self.preview_stack.add_named(self.picture, "image")
            self.preview_stack.add_named(
                label("Select something to take a closer look.", "muted", wrap=True), "empty"
            )
            preview.append(self.preview_stack)
            self.preview_note = label(css="muted", wrap=True)
            preview.append(self.preview_note)
            self.details = Gtk.Grid(column_spacing=16, row_spacing=9)
            self.detail_values = {}
            for row, name in enumerate(["Type", "Source", "Copied", "Size"]):
                self.details.attach(label(name, "muted"), 0, row, 1, 1)
                value = label(ellipsize=Pango.EllipsizeMode.END, hexpand=True)
                value.set_max_width_chars(25)
                self.details.attach(value, 1, row, 1, 1)
                self.detail_values[name] = value
            preview.append(self.details)

            self.message = label(css="message", wrap=True)
            self.message.set_visible(False)
            root.append(self.message)
            footer = Gtk.Box(spacing=6)
            footer.add_css_class("footer")
            self.status = label(css="muted", hexpand=True)
            footer.append(self.status)
            self.clear_button = button(
                "edit-clear-all-symbolic", "Clear unpinned history", self.clear_history
            )
            footer.append(self.clear_button)
            self.pin_button = button("view-pin-symbolic", "Pin / unpin · Ctrl+P", self.pin)
            footer.append(self.pin_button)
            self.delete_button = button(
                "user-trash-symbolic", "Delete item · Ctrl+Backspace", self.delete
            )
            footer.append(self.delete_button)
            self.copy_button = button(
                "edit-copy-symbolic",
                "Copy only · Ctrl+Enter",
                lambda *_: self.activate(copy_only=True),
            )
            footer.append(self.copy_button)
            self.paste_button = Gtk.Button(label="Paste  ↵" if self.paste_on_select else "Copy  ↵")
            self.paste_button.add_css_class("primary")
            self.paste_button.connect("clicked", lambda *_: self.activate())
            footer.append(self.paste_button)
            root.append(footer)
            action = "Paste" if self.paste_on_select else "Copy"
            hints = label(
                f"↑ ↓  Navigate     ↵  {action}     Ctrl ↵  Copy     "
                "Ctrl P  Pin     Alt 1–9  Quick select",
                "shortcuts",
            )
            root.append(hints)

            keys = Gtk.EventControllerKey.new()
            keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            keys.connect("key-pressed", self.key_pressed)
            keys.connect("key-released", self.key_released)
            self.add_controller(keys)
            self.connect("close-request", self.closing)
            self.refresh()
            self.poll_id = GLib.timeout_add(750, self.poll)
            self.present()
            self.search.grab_focus()

        def configure_layer(self, window, monitor):
            layer.init_for_window(window)
            layer.set_namespace(window, "nix-clipboard-history")
            layer.set_layer(window, layer.Layer.OVERLAY)
            layer.set_exclusive_zone(window, -1)
            if monitor:
                layer.set_monitor(window, monitor)
            for edge in (layer.Edge.TOP, layer.Edge.BOTTOM, layer.Edge.LEFT, layer.Edge.RIGHT):
                layer.set_anchor(window, edge, True)

        def click_shield(self):
            background = Gtk.Box(hexpand=True, vexpand=True)
            background.add_css_class("dismiss-backdrop")
            click = Gtk.GestureClick.new()
            click.set_button(0)

            def dismiss(gesture, *_args):
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self.close()

            click.connect("pressed", dismiss)
            background.add_controller(click)
            return background

        def closing(self, *_args):
            if self.closed:
                return False
            self.closed = True
            GLib.source_remove(self.poll_id)
            for timer in (self.search_timeout, self.clear_timeout, self.selection_timeout):
                if timer:
                    GLib.source_remove(timer)
            for shield in self.shields:
                shield.destroy()
            self.store.close()
            return False

        def current(self) -> Entry | None:
            row = self.listbox.get_selected_row()
            return (
                self.entries[row.get_index()]
                if row and row.get_index() < len(self.entries)
                else None
            )

        def refresh(self, keep_id=None):
            selected = self.current()
            if keep_id is None and selected:
                keep_id = selected.id
            self.entries = []
            while child := self.listbox.get_first_child():
                self.listbox.remove(child)
            self.entries = self.store.list(self.search.get_text(), self.kind, limit=1000)
            self.rows = []
            for index, entry in enumerate(self.entries):
                row = Gtk.ListBoxRow()
                row.add_css_class("history-row")
                box = Gtk.Box(spacing=12)
                icon_name = (
                    "image-x-generic-symbolic"
                    if entry.kind == "image"
                    else (
                        "insert-link-symbolic"
                        if entry.title.startswith(("https://", "http://"))
                        else "text-x-generic-symbolic"
                    )
                )
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.add_css_class("item-icon")
                icon.set_pixel_size(19)
                box.append(icon)
                words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
                title = label(entry.title, "item-title", ellipsize=Pango.EllipsizeMode.END)
                title.set_max_width_chars(32)
                words.append(title)
                source = entry.source or ("Image" if entry.kind == "image" else "Text")
                words.append(label(f"{source}  ·  {relative_time(entry.updated_at)}", "item-meta"))
                box.append(words)
                if entry.pinned:
                    box.append(Gtk.Image.new_from_icon_name("view-pin-symbolic"))
                elif index < 9:
                    box.append(label(str(index + 1), "row-number"))
                row.set_child(box)
                self.listbox.append(row)
                self.rows.append(row)
            self.count.set_text(f"{len(self.entries)} items")
            self.stack.set_visible_child_name("list" if self.entries else "empty")
            if not self.entries:
                searching = bool(self.search.get_text()) or self.kind != "all"
                self.empty_title.set_text(
                    "Nothing found" if searching else "Your clipboard starts here"
                )
                self.empty_hint.set_text(
                    "Try another search or filter."
                    if searching
                    else "Copy some text or an image to get started."
                )
                self.selected(None, None)
            else:
                index = next((i for i, e in enumerate(self.entries) if e.id == keep_id), 0)
                self.listbox.select_row(self.rows[index])
            paused = self.store.paused
            self.running = self.store.daemon_running()
            self.status.set_text(
                "●  Capture paused"
                if paused
                else ("●  History active" if self.running else "●  Capture offline")
            )
            self.status.set_tooltip_text(
                "Run nix-clipboard-history daemon to capture new copies."
                if not self.running
                else "Clipboard capture is running."
            )
            self.pause_button.set_icon_name(
                "media-playback-start-symbolic" if paused else "media-playback-pause-symbolic"
            )
            self.pause_button.set_tooltip_text("Resume capture" if paused else "Pause capture")
            self.last_revision = self.store.revision

        def poll(self):
            if (
                self.store.revision != self.last_revision
                or self.store.daemon_running() != self.running
            ):
                self.refresh()
            return True

        def search_changed(self, *_args):
            if self.search_timeout:
                GLib.source_remove(self.search_timeout)
            self.search_timeout = GLib.timeout_add(80, self.finish_search)

        def finish_search(self):
            self.search_timeout = 0
            self.refresh()
            return False

        def change_filter(self, tab, kind):
            if tab.get_active():
                self.kind = kind
                self.refresh()

        def selected(self, _listbox, row):
            entry = self.current() if row else None
            for widget in (
                self.pin_button,
                self.delete_button,
                self.copy_button,
                self.paste_button,
            ):
                widget.set_sensitive(entry is not None and not self.busy)
            self.details.set_visible(entry is not None)
            self.preview_note.set_text("")
            self.picture.set_paintable(None)
            self.text_view.get_buffer().set_text("")
            if entry is None:
                self.preview_stack.set_visible_child_name("empty")
                return
            try:
                data, _mime = self.store.get(entry.id)
            except ValueError:
                self.preview_stack.set_visible_child_name("empty")
                return
            if entry.kind == "text":
                text = data.decode("utf-8")
                self.text_view.get_buffer().set_text(text[:24000])
                self.preview_stack.set_visible_child_name("text")
                if len(text) > 24000:
                    self.preview_note.set_text("Preview shortened. Pasting uses the complete text.")
            else:
                try:
                    # Decode at preview size instead of allocating a full-resolution texture.
                    loader = GdkPixbuf.PixbufLoader.new()

                    def resize(decoder, width, height):
                        scale = min(640 / max(width, 1), 400 / max(height, 1), 1)
                        decoder.set_size(max(1, int(width * scale)), max(1, int(height * scale)))

                    loader.connect("size-prepared", resize)
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                    self.preview_stack.set_visible_child_name("image")
                except (GLib.Error, TypeError):
                    self.preview_stack.set_visible_child_name("empty")
                    self.preview_note.set_text(
                        "Preview unavailable. The original image can still be pasted."
                    )
            values = {
                "Type": entry.mime_type.split(";")[0],
                "Source": entry.source or "Unknown",
                "Copied": datetime.fromtimestamp(entry.updated_at).strftime("%d %b, %H:%M"),
                "Size": human_size(entry.byte_count),
            }
            for name, value in values.items():
                self.detail_values[name].set_text(value)
                self.detail_values[name].set_tooltip_text(value)
            self.pin_button.set_tooltip_text("Unpin · Ctrl+P" if entry.pinned else "Pin · Ctrl+P")

        def inform(self, message):
            self.message.set_text(message)
            self.message.set_visible(True)

        def pause(self, *_args):
            self.store.set_paused()
            self.refresh()

        def pin(self, *_args):
            if entry := self.current():
                self.store.pin(entry.id)
                self.refresh(keep_id=entry.id)

        def delete(self, *_args):
            if entry := self.current():
                index = self.listbox.get_selected_row().get_index()
                self.store.delete(entry.id)
                next_id = self.entries[min(index + 1, len(self.entries) - 1)].id
                self.refresh(keep_id=next_id)

        def clear_history(self, *_args):
            if self.clear_armed:
                self.store.clear()
                self.disarm_clear()
                self.inform("History cleared. Pinned items and the current clipboard are kept.")
                self.refresh()
            else:
                self.clear_armed = True
                self.clear_button.add_css_class("danger")
                self.inform("Clear unpinned history? Click the clear button again to confirm.")
                self.clear_timeout = GLib.timeout_add(5000, self.disarm_clear)

        def disarm_clear(self):
            self.clear_armed = False
            self.clear_button.remove_css_class("danger")
            if self.clear_timeout:
                GLib.source_remove(self.clear_timeout)
                self.clear_timeout = 0
            self.message.set_visible(False)
            return False

        def activate(self, copy_only=False):
            if self.closed:
                return
            entry = self.current()
            if entry is None or self.busy:
                return
            try:
                data, mime = self.store.get(entry.id)
            except ValueError as error:
                self.inform(str(error))
                self.refresh()
                return
            self.busy = True
            self.panel.set_sensitive(False)

            def worker():
                try:
                    copy(data, mime)
                except (OSError, RuntimeError) as error:
                    GLib.idle_add(self.copy_failed, str(error))
                else:
                    GLib.idle_add(self.copied, copy_only)

            threading.Thread(target=worker, daemon=True).start()

        def copy_failed(self, message):
            if self.closed:
                return False
            self.busy = False
            self.panel.set_sensitive(True)
            self.inform(message)
            return False

        def copied(self, copy_only):
            if not self.closed:
                self.selection_timeout = GLib.timeout_add(15, self.finish_selection, copy_only)
            return False

        def finish_selection(self, copy_only):
            should_paste = self.paste_on_select and not copy_only
            if should_paste:
                keyboard = self.get_display().get_default_seat().get_keyboard()
                modifiers = (
                    Gdk.ModifierType.SHIFT_MASK
                    | Gdk.ModifierType.CONTROL_MASK
                    | Gdk.ModifierType.ALT_MASK
                    | Gdk.ModifierType.SUPER_MASK
                    | Gdk.ModifierType.META_MASK
                    | Gdk.ModifierType.HYPER_MASK
                )
                # Quick-select may still have Alt held. Keep the grab until its
                # release so the original application receives a clean Ctrl+V.
                if keyboard and keyboard.get_modifier_state() & modifiers:
                    return True
            self.selection_timeout = 0
            self.get_application().paste_requested = should_paste
            self.close()
            return False

        def key_pressed(self, _controller, key, _code, state):
            if key == Gdk.KEY_Escape and (self.busy or not self.clear_armed):
                self.close()
                return True
            if self.busy:
                return True
            ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
            alt = bool(state & Gdk.ModifierType.ALT_MASK)
            if key == Gdk.KEY_Escape:
                if self.clear_armed:
                    self.disarm_clear()
                else:
                    self.close()
            elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.pending_activation = (key, ctrl)
            elif key in (Gdk.KEY_Down, Gdk.KEY_Up):
                if self.rows:
                    row = self.listbox.get_selected_row()
                    index = row.get_index() if row else 0
                    index = max(
                        0, min(len(self.rows) - 1, index + (1 if key == Gdk.KEY_Down else -1))
                    )
                    self.listbox.select_row(self.rows[index])
                    bounds = self.rows[index].compute_bounds(self.listbox)
                    if bounds[0]:
                        adjustment = self.scroll.get_vadjustment()
                        top = bounds[1].get_y()
                        adjustment.clamp_page(top, top + bounds[1].get_height())
            elif ctrl and key in (Gdk.KEY_p, Gdk.KEY_P):
                self.pin()
            elif ctrl and key in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
                self.delete()
            elif ctrl and key in (Gdk.KEY_f, Gdk.KEY_F):
                self.search.grab_focus()
            elif ctrl and key in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3, Gdk.KEY_4):
                self.tabs[key - Gdk.KEY_1].set_active(True)
            elif alt and Gdk.KEY_1 <= key <= Gdk.KEY_9:
                index = key - Gdk.KEY_1
                if index < len(self.rows):
                    self.listbox.select_row(self.rows[index])
                    self.pending_activation = (key, False)
            else:
                return False
            return True

        def key_released(self, _controller, key, _code, _state):
            if self.pending_activation and self.pending_activation[0] == key:
                _, copy_only = self.pending_activation
                self.pending_activation = None
                self.activate(copy_only=copy_only)

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(
                application_id="io.github.kylescudder.NixClipboardHistory",
                flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            )
            self.window = None
            self.error = None
            self.paste_requested = False

        def do_activate(self):
            if self.window:
                if not self.window.busy:
                    self.window.close()
            else:
                try:
                    self.window = Popup(self)
                except (RuntimeError, OSError) as error:
                    self.error = error
                    self.quit()

    app = App()
    result = app.run([])
    if app.error:
        raise app.error
    if app.paste_requested:
        # Closing the application destroys every layer surface and releases the
        # exclusive keyboard grab before the compositor restores client focus.
        Gdk.Display.get_default().sync()
        time.sleep(config.paste_delay_ms / 1000)
        restore_focus(target)
        paste(target, config)
    return result
