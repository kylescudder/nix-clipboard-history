"""Real layer-shell pointer/keyboard regressions, invoked by wayland_smoke.py.

Only the Hyprland IPC adapter is replaced with Sway IPC and wtype. GTK focus,
pointer events, keyboard events, wl-copy and the receiving text input are real.
"""

# ruff: noqa: E402
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import patch

ctypes.CDLL(os.environ["NIX_CLIPBOARD_LAYER_SHELL"], mode=ctypes.RTLD_GLOBAL)
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gio, GLib, Gtk

from nix_clipboard_history.config import Config
from nix_clipboard_history.gui import run
from nix_clipboard_history.wayland import copy

mode, state_name = sys.argv[1:]
state = Path(state_name)
if mode == "target":
    app = Gtk.Application(application_id="io.github.clipboard.PasteTest")

    def show(application):
        window = Gtk.ApplicationWindow(application=application, title="Clipboard paste target")
        window.set_default_size(720, 220)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(24)
        content.append(Gtk.Label(label="Clipboard paste regression: previous app's text input"))
        entry = Gtk.Entry()
        entry.connect("changed", lambda widget: state.write_text(widget.get_text()))
        content.append(entry)
        window.set_child(content)
        window.present()
        entry.grab_focus()
        state.write_text("")

    app.connect("activate", show)
    raise SystemExit(app.run([]))

original_run = subprocess.run
target = subprocess.Popen([sys.executable, __file__, "target", str(state)])
errors = []
commands = []
popup = None
ready = threading.Event()
done = threading.Event()
copy_started = threading.Event()
copy_finished = threading.Event()


def transfer(data, mime):
    if mode == "cancel-copy":
        copy_started.set()
        time.sleep(0.3)
    copy(data, mime)
    copy_finished.set()


def wait_for(check, description):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {description}")


def sway(command):
    return original_run(["swaymsg", command], capture_output=True, check=True, timeout=3)


def ipc(args, **kwargs):
    if args[0] != "hyprctl":
        return original_run(args, **kwargs)
    if args[1:] == ["-j", "monitors"]:
        return subprocess.CompletedProcess(args, 0, b'[{"name":"HEADLESS-1","focused":true}]')
    if args[1:] == ["-j", "activewindow"]:
        tree = json.loads(
            original_run(
                ["swaymsg", "-t", "get_tree"], capture_output=True, check=True, timeout=3
            ).stdout
        )

        def focused(node):
            return (
                node.get("focused")
                and node.get("name") == "Clipboard paste target"
                or any(
                    focused(child)
                    for child in node.get("nodes", []) + node.get("floating_nodes", [])
                )
            )

        value = {"address": "0xabc", "class": "paste-test"} if focused(tree) else {}
        return subprocess.CompletedProcess(args, 0, json.dumps(value).encode())
    assert args[1] == "dispatch", args
    assert popup.closed and popup.get_surface() is None, (
        "Paste dispatched before surface destruction"
    )
    commands.append(args[-1])
    if "hl.dsp.focus(" in args[-1]:
        sway('[title="Clipboard paste target"] focus')
    else:
        assert "hl.dsp.send_shortcut(" in args[-1], args
        if mode == "paste-error":
            return subprocess.CompletedProcess(args, 1, b"test dispatch failure")
        original_run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=True, timeout=3)
    return subprocess.CompletedProcess(args, 0, b"ok\n")


def inspect():
    global popup
    popup = Gio.Application.get_default().window
    assert popup.get_width() == 1280 and popup.get_height() == 800
    bounds = popup.panel.compute_bounds(popup)[1]
    assert bounds.get_width() == 880 and bounds.get_height() == 640
    assert len(popup.entries) == 2
    ready.set()
    return False


def screenshot(name):
    if os.environ.get("ARTIFACT_DIR"):
        original_run(
            ["grim", "-o", "HEADLESS-1", str(Path(os.environ["ARTIFACT_DIR"]) / name)],
            check=True,
            timeout=3,
        )


def controller():
    try:
        assert ready.wait(5), "Popup never mapped"
        if mode == "outside-button1":
            screenshot("01-popup.png")
        if mode.startswith("outside"):
            # Clicking inside the panel must leave it open.
            sway("seat seat0 cursor set 1000 200")
            original_run(["wlrctl", "pointer", "move", "1", "1"], check=True, timeout=3)
            original_run(["wlrctl", "pointer", "click", "left"], check=True, timeout=3)
            time.sleep(0.1)
            assert not popup.closed
            button = {
                "outside-button1": "left",
                "outside-button2": "middle",
                "outside-button3": "right",
            }[mode]
            sway("seat seat0 cursor set 5 5")
            original_run(["wlrctl", "pointer", "move", "1", "1"], check=True, timeout=3)
            original_run(["wlrctl", "pointer", "click", button], check=True, timeout=3)
        elif mode == "other-monitor":
            sway("seat seat0 cursor set 1300 20")
            original_run(["wlrctl", "pointer", "move", "1", "1"], check=True, timeout=3)
            original_run(["wlrctl", "pointer", "click", "left"], check=True, timeout=3)
        elif mode == "escape":
            original_run(["wtype", "-k", "Escape"], check=True, timeout=3)
        elif mode == "cancel-copy":
            original_run(["wtype", "-k", "Return"], check=True, timeout=3)
            assert copy_started.wait(3)
            sway("seat seat0 cursor set 5 5")
            original_run(["wlrctl", "pointer", "move", "1", "1"], check=True, timeout=3)
            original_run(["wlrctl", "pointer", "click", "left"], check=True, timeout=3)
        elif mode == "alt-select":
            keys = subprocess.Popen(["wtype", "-M", "alt", "-k", "2", "-s", "400", "-m", "alt"])
            time.sleep(0.2)
            assert not popup.closed, "Popup released focus before Alt was released"
            assert keys.wait(timeout=3) == 0
        elif mode == "copy-only":
            original_run(
                ["wtype", "-M", "ctrl", "-k", "Return", "-m", "ctrl"], check=True, timeout=3
            )
        else:
            keys = subprocess.Popen(
                ["wtype", "-k", "Down", "-P", "Return", "-s", "400", "-p", "Return"]
            )
            time.sleep(0.2)
            assert not popup.closed, "Selection should wait for Enter release"
            assert keys.wait(timeout=3) == 0
        wait_for(lambda: popup.closed, "popup dismissal")
    except BaseException:
        errors.append(traceback.format_exc())
        GLib.idle_add(lambda: Gio.Application.get_default().quit())
    finally:
        done.set()


try:
    wait_for(state.exists, "target input")
    sway('[title="Clipboard paste target"] move container to output HEADLESS-1')
    sway('[title="Clipboard paste target"] focus')
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "sway-test-adapter"
    GLib.timeout_add(500, inspect)
    threading.Thread(target=controller, daemon=True).start()
    with (
        patch("nix_clipboard_history.wayland.subprocess.run", side_effect=ipc),
        patch("nix_clipboard_history.gui.copy", side_effect=transfer),
    ):
        try:
            result = run(Config())
        except RuntimeError as error:
            assert mode == "paste-error" and "could not send" in str(error), str(error)
        else:
            assert result == 0 and mode != "paste-error"
        if mode == "cancel-copy":
            assert copy_finished.wait(3)
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
            assert not popup.get_application(), "Late copy callback reopened the popup"
    assert done.wait(5) and not errors, "\n".join(errors)
    if mode in ("enter", "alt-select"):
        wait_for(
            lambda: state.read_text() == "selected older note", "text pasted into previous input"
        )
        assert len(commands) == 2
        if mode == "enter":
            time.sleep(0.15)
            screenshot("02-pasted.png")
    else:
        assert state.read_text() == "", "Dismissal or copy-only unexpectedly pasted"
        assert len(commands) == (2 if mode == "paste-error" else 0)
    print(f"Popup regression passed: {mode}")
finally:
    target.terminate()
    target.wait(timeout=3)
