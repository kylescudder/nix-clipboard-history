"""Real data-control, capture supervision, and clipboard ownership under headless Sway.

Run on Linux with: nix develop --command env PYTHONPATH=. python tests/wayland_smoke.py
Sway is only a test compositor; automatic Hyprland paste has separate unit coverage.
"""

import base64
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from nix_clipboard_history.store import Store
from nix_clipboard_history.wayland import copy


def wait_for(check, description, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {description}")


def main():
    # Sway refuses to run as root. A container can safely drop privileges for this test.
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)
    with tempfile.TemporaryDirectory(prefix="clipboard-wayland-") as directory:
        root = Path(directory)
        os.environ.update(
            {
                "HOME": directory,
                "TMPDIR": directory,
                "XDG_RUNTIME_DIR": directory,
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "WLR_BACKENDS": "headless",
                "WLR_RENDERER": "pixman",
                "WLR_HEADLESS_OUTPUTS": "1",
                "GDK_BACKEND": "wayland",
                "GSK_RENDERER": "cairo",
                "GTK_A11Y": "none",
            }
        )
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
        configuration = root / "sway.conf"
        configuration.write_text("seat seat0 fallback true\nxwayland disable\n")
        log = (root / "sway.log").open("w+")
        compositor = subprocess.Popen(
            ["sway", "--unsupported-gpu", "--config", str(configuration)], stdout=log, stderr=log
        )
        daemon = None
        try:
            wait_for(lambda: list(root.glob("wayland-*")), "Wayland socket")
            socket = next(p for p in root.glob("wayland-*") if not p.name.endswith(".lock"))
            os.environ["WAYLAND_DISPLAY"] = socket.name
            daemon = subprocess.Popen([sys.executable, "-m", "nix_clipboard_history", "daemon"])
            with Store() as store:
                wait_for(store.daemon_running, "capture service")
                # Allow the watchers to bind data-control before testing a selection.
                time.sleep(0.3)
                text = "Clipboard history\nwith whitespace 🙂\n".encode()
                copy(text, "text/plain;charset=utf-8")
                wait_for(lambda: len(store.list()) == 1, "text capture")
                assert store.get(store.list()[0].id)[0] == text
                paste_result = subprocess.run(
                    ["wl-paste", "--no-newline"], capture_output=True, check=True, timeout=3
                )
                assert paste_result.stdout == text
                copy(text, "text/plain;charset=utf-8")
                time.sleep(0.2)
                assert len(store.list()) == 1, "Repeated selection should be deduplicated"
                image = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
                )
                copy(image, "image/png")
                wait_for(lambda: len(store.list(kind="image")) == 1, "image capture")
                assert store.get(store.list(kind="image")[0].id) == (image, "image/png")
                paste_result = subprocess.run(
                    ["wl-paste", "--type", "image/png"], capture_output=True, check=True, timeout=3
                )
                assert paste_result.stdout == image
                # Sensitive copies must never appear in the database.
                subprocess.run(
                    ["wl-copy", "--sensitive"],
                    input=b"must not be saved",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=3,
                )
                time.sleep(0.2)
                assert not store.list("must not be saved")
                store.set_paused(True)
                copy(b"paused secret", "text/plain")
                time.sleep(0.2)
                assert not store.list("paused secret")
                store.set_paused(False)
                copy(b"resumed", "text/plain")
                wait_for(lambda: bool(store.list("resumed")), "resume capture")
                popup = subprocess.run(
                    [sys.executable, "tests/layer_smoke.py"], capture_output=True, timeout=10
                )
                assert popup.returncode == 0, popup.stderr.decode()
                print(popup.stdout.decode().strip())
                assert (
                    subprocess.run(
                        ["wl-paste", "--no-newline"], capture_output=True, check=True, timeout=3
                    ).stdout
                    == b"resumed"
                )
                duplicate = subprocess.run(
                    [sys.executable, "-m", "nix_clipboard_history", "daemon"],
                    capture_output=True,
                    timeout=3,
                )
                assert duplicate.returncode == 1 and b"already running" in duplicate.stderr
                daemon.send_signal(signal.SIGTERM)
                assert daemon.wait(timeout=5) == 0
                assert not store.daemon_running()
            print(
                "Wayland smoke passed: real text/image capture, ownership, sensitive hints, "
                "pause/resume, deduplication, and daemon shutdown."
            )
        except BaseException:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            for process in (daemon, compositor):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            log.close()


if __name__ == "__main__":
    main()
