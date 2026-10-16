"""Supervise one watcher that requests one supported MIME per clipboard offer."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import threading

from .config import Config
from .store import Store

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/tiff", "image/bmp")
TEXT_TYPES = ("text/plain;charset=utf-8", "text/plain;charset=UTF-8", "text/plain", "UTF8_STRING")


def capture_types(config: Config) -> tuple[str, ...]:
    return (IMAGE_TYPES if config.capture_images else ()) + TEXT_TYPES


def run(config: Config) -> int:
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError(
            "Run the clipboard service inside a Wayland session (WAYLAND_DISPLAY missing)"
        )
    with Store(config=config) as store:
        lock_path = store.directory / "daemon.lock"
        with lock_path.open("a") as lock:
            lock_path.chmod(0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("The clipboard capture service is already running") from error
            stop = threading.Event()
            previous = {}
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_args: stop.set())
            watchers = []
            try:
                watchers.append(
                    subprocess.Popen(
                        [
                            os.environ.get("NIX_CLIPBOARD_WATCHER", "nix-clipboard-history-watch"),
                            *capture_types(config),
                            "--",
                            sys.executable,
                            "-m",
                            "nix_clipboard_history",
                            "capture",
                            "--kind",
                            "auto",
                        ],
                        start_new_session=True,
                    )
                )
                store.prune()
                ticks = 0
                while not stop.wait(0.5):
                    if any(child.poll() is not None for child in watchers):
                        raise RuntimeError(
                            "Clipboard watcher exited; check Wayland data-control support"
                        )
                    ticks += 1
                    if ticks % 120 == 0:
                        store.prune()
            finally:
                for child in watchers:
                    # Include helpers waiting for an application to provide clipboard data.
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                for child in watchers:
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
    return 0
