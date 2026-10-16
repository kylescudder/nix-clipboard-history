"""Clipboard ownership and Hyprland integration; never pass clipboard text to a shell."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True)
class Target:
    address: str = ""
    app_class: str = ""


def active_window() -> Target:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return Target()
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "activewindow"], capture_output=True, check=True, timeout=2
        )
        window = json.loads(result.stdout)
        address = window.get("address", "")
        if not re.fullmatch(r"0x[0-9a-fA-F]+", address) or address == "0x0":
            return Target()
        return Target(address, window.get("class", ""))
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
        return Target()


def copy(data: bytes, mime: str):
    try:
        # wl-copy forks its clipboard owner after taking stdin; no GTK clipboard lifetime race.
        result = subprocess.run(
            ["wl-copy", "--type", mime],
            input=data,
            stdout=subprocess.DEVNULL,
            # The forked owner keeps stderr open. A pipe here would make communicate()
            # wait until the next clipboard change rather than until ownership is ready.
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except FileNotFoundError as error:
        raise RuntimeError("wl-copy is missing; install wl-clipboard") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("wl-copy timed out; check your Wayland session") from error
    if result.returncode:
        raise RuntimeError("Could not take clipboard ownership; check your Wayland session")


def focused_monitor() -> str:
    """Match the Hyprland output to GDK when constructing a multi-monitor popup."""
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "monitors"], capture_output=True, check=True, timeout=2
        )
        return next(monitor["name"] for monitor in json.loads(result.stdout) if monitor["focused"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, StopIteration):
        return ""


def restore_focus(target: Target):
    """Restore keyboard focus only after all layer surfaces have been destroyed."""
    if not target.address:
        raise RuntimeError("Copied, but no Hyprland target was found. Paste manually with Ctrl+V.")
    try:
        result = subprocess.run(
            [
                "hyprctl",
                "dispatch",
                f"hl.dsp.focus({{window={json.dumps('address:' + target.address)}}})",
            ],
            capture_output=True,
            timeout=3,
        )
        if result.stdout.strip() == b"Invalid dispatcher":
            result = subprocess.run(
                ["hyprctl", "dispatch", "focuswindow", f"address:{target.address}"],
                capture_output=True,
                timeout=3,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            "Copied, but Hyprland did not restore focus. Paste manually with Ctrl+V."
        ) from error
    if result.returncode == 0 and result.stdout.strip() == b"ok":
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if active_window().address == target.address:
                return
            time.sleep(0.02)
    raise RuntimeError("Copied, but the previous window could not be focused. Paste manually.")


def paste(target: Target, config: Config):
    if not target.address:
        raise RuntimeError("Copied, but no Hyprland target was found. Paste manually with Ctrl+V.")
    # Abort if focus changed while the popup was closing rather than pasting into another app.
    if active_window().address != target.address:
        raise RuntimeError("Copied; the focused window changed. Paste manually with Ctrl+V.")
    terminal = target.app_class.casefold() in {name.casefold() for name in config.terminal_classes}
    modifiers = "CTRL SHIFT" if terminal else "CTRL"
    shortcut = (
        f"hl.dsp.send_shortcut({{mods={json.dumps(modifiers)}, "
        f'key="V", window={json.dumps("address:" + target.address)}}})'
    )
    try:
        result = subprocess.run(
            ["hyprctl", "dispatch", shortcut],
            capture_output=True,
            timeout=3,
        )
        # A legacy parser rejects the Lua dispatcher before executing any shortcut.
        # Retry only that explicit rejection, never an ambiguous failure or timeout.
        if result.stdout.strip() == b"Invalid dispatcher":
            if active_window().address != target.address:
                raise RuntimeError(
                    "Copied; the focused window changed. Paste manually with Ctrl+V."
                )
            result = subprocess.run(
                ["hyprctl", "dispatch", "sendshortcut", f"{modifiers},V,address:{target.address}"],
                capture_output=True,
                timeout=3,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            "Copied, but Hyprland did not respond. Paste manually with Ctrl+V."
        ) from error
    if result.returncode or result.stdout.strip() != b"ok":
        raise RuntimeError(
            "Copied, but Hyprland could not send the paste shortcut. Paste manually."
        )
