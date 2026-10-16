"""Real data-control, capture supervision, and clipboard ownership under headless Sway.

Run on Linux with: nix develop --command env PYTHONPATH=. python tests/wayland_smoke.py
Hyprland IPC syntax has unit coverage; popup regressions adapt its dispatches to Sway.
"""

import argparse
import base64
import json
import os
import shlex
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


def check_offer(store, root, name, offers, expected):
    """Publish distinct representations in one actual GTK clipboard offer."""
    ready = root / f"{name}-ready"
    specification = json.dumps([(mime, base64.b64encode(data).decode()) for mime, data in offers])
    with (root / f"{name}.log").open("w+") as log:
        owner = subprocess.Popen(
            [sys.executable, "tests/multi_offer.py", specification, str(ready)],
            stdout=log,
            stderr=log,
        )
        try:
            wait_for(lambda: Path(str(ready) + ".mapped").exists(), f"{name} source window")
            # Let any preceding clipboard transfer finish before isolating this offer.
            store.clear(include_pinned=True)
            # A regular GTK source needs a genuine input serial to own selection.
            subprocess.run(["wtype", "-s", "100", "-k", "F12"], check=True, timeout=3)
            wait_for(ready.exists, f"{name} clipboard offer")
            actual_types = (
                subprocess.check_output(["wl-paste", "--list-types"], timeout=3)
                .decode()
                .splitlines()
            )
            assert all(mime in actual_types for mime, _data in offers), actual_types
            if name == "svg-before-png":
                assert actual_types.index("image/svg+xml") < actual_types.index("image/png"), (
                    actual_types
                )
            if expected is not None:
                wait_for(lambda: bool(store.list()), f"{name} capture")
            time.sleep(0.3)
            entries = store.list()
            if expected is None:
                assert not entries, f"{name}: unexpected history entry"
            else:
                assert len(entries) == 1, f"{name}: one offer produced {entries}"
                assert store.get(entries[0].id) == expected, (name, entries)
            print(f"MIME regression passed: {name}")
        except BaseException:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            owner.terminate()
            owner.wait(timeout=3)


def main(package=None):
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
                "WLR_HEADLESS_OUTPUTS": "2",
                "GDK_BACKEND": "wayland",
                "GSK_RENDERER": "cairo",
                "GTK_A11Y": "none",
            }
        )
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
        subprocess.run(["bash", "native/build.sh", str(root / "native")], check=True)
        os.environ["NIX_CLIPBOARD_WATCHER"] = str(root / "native/nix-clipboard-history-watch")
        configuration = root / "sway.conf"
        configuration.write_text(
            "seat seat0 fallback true\nxwayland disable\n"
            "output HEADLESS-1 mode 1280x800 pos 0 0\n"
            "output HEADLESS-2 mode 1280x800 pos 1280 0\n"
            'for_window [title="Clipboard paste target"] floating enable\n'
        )
        log = (root / "sway.log").open("w+")
        compositor = subprocess.Popen(
            ["sway", "--unsupported-gpu", "--config", str(configuration)], stdout=log, stderr=log
        )
        daemon = None
        pointer = None
        try:
            wait_for(lambda: list(root.glob("wayland-*")), "Wayland socket")
            socket = next(p for p in root.glob("wayland-*") if not p.name.endswith(".lock"))
            os.environ["WAYLAND_DISPLAY"] = socket.name
            wait_for(lambda: list(root.glob("sway-ipc*.sock")), "Sway IPC socket")
            os.environ["SWAYSOCK"] = str(next(root.glob("sway-ipc*.sock")))
            # One-shot virtual devices disappear before GTK can bind wl_pointer.
            # Keep a device connected while real wlrctl clicks drive the popup.
            protocol = os.environ["WLR_POINTER_PROTOCOL"]
            for action, filename in (
                ("client-header", "pointer-client.h"),
                ("private-code", "pointer.c"),
            ):
                subprocess.run(
                    ["wayland-scanner", action, protocol, str(root / filename)], check=True
                )
            flags = shlex.split(
                subprocess.check_output(
                    ["pkg-config", "--cflags", "--libs", "wayland-client"], text=True
                )
            )
            subprocess.run(
                [
                    "cc",
                    "tests/virtual_pointer.c",
                    str(root / "pointer.c"),
                    "-I",
                    directory,
                    *flags,
                    "-o",
                    str(root / "pointer"),
                ],
                check=True,
            )
            pointer = subprocess.Popen([str(root / "pointer"), str(root / "pointer-ready")])
            wait_for(lambda: (root / "pointer-ready").exists(), "persistent pointer")
            daemon_command = [sys.executable, "-m", "nix_clipboard_history", "daemon"]
            daemon_options = {}
            if package:
                daemon_command = [str(package / "bin/nix-clipboard-history"), "daemon"]
                environment = os.environ.copy()
                environment.pop("PYTHONPATH", None)
                environment.pop("NIX_PYTHONPATH", None)
                # A checkout or development shell must not hide missing installed imports.
                daemon_options = {"cwd": directory, "env": environment}
            daemon = subprocess.Popen(daemon_command, **daemon_options)
            with Store() as store:
                wait_for(store.daemon_running, "capture service")
                # Allow the watcher to bind data-control before testing a selection.
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
                store.set_paused(False)
                svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
                check_offer(
                    store,
                    root,
                    "mixed-text-image",
                    [
                        ("text/plain", b"image description"),
                        ("image/png", image),
                    ],
                    (image, "image/png"),
                )
                check_offer(
                    store,
                    root,
                    "svg-before-png",
                    [
                        ("image/svg+xml", svg),
                        ("image/png", image),
                    ],
                    (image, "image/png"),
                )
                gif = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
                check_offer(
                    store,
                    root,
                    "png-preferred-over-gif",
                    [
                        ("image/gif", gif),
                        ("image/png", image),
                    ],
                    (image, "image/png"),
                )
                check_offer(
                    store,
                    root,
                    "unsupported-image-text-fallback",
                    [
                        ("image/svg+xml", svg),
                        ("text/plain", b"plain text fallback"),
                    ],
                    (b"plain text fallback", "text/plain;charset=utf-8"),
                )
                check_offer(store, root, "unsupported-image-only", [("image/svg+xml", svg)], None)
                check_offer(
                    store,
                    root,
                    "sensitive-multi-format",
                    [
                        ("image/png", image),
                        ("text/plain", b"sensitive"),
                        ("x-kde-passwordManagerHint", b"secret"),
                    ],
                    None,
                )
                store.clear(include_pinned=True)
                store.add(b"selected older note", "text", "test")
                store.add(b"latest note", "text", "test")
                store.set_paused(True)
                for mode in (
                    "outside-button1",
                    "outside-button2",
                    "outside-button3",
                    "other-monitor",
                    "enter",
                    "alt-select",
                    "copy-only",
                    "paste-error",
                    "escape",
                    "cancel-copy",
                ):
                    state = root / f"{mode}.txt"
                    regression = subprocess.run(
                        [sys.executable, "tests/popup_smoke.py", mode, str(state)],
                        capture_output=True,
                        timeout=15,
                    )
                    assert regression.returncode == 0, (
                        regression.stdout.decode() + regression.stderr.decode()
                    )
                    print(regression.stdout.decode().strip())
                duplicate = subprocess.run(
                    daemon_command,
                    capture_output=True,
                    timeout=3,
                    **daemon_options,
                )
                assert duplicate.returncode == 1 and b"already running" in duplicate.stderr
                daemon.send_signal(signal.SIGTERM)
                assert daemon.wait(timeout=5) == 0
                assert not store.daemon_running()
                copy(b"capture failure regression", "text/plain")
                failed_capture = subprocess.run(
                    [
                        os.environ["NIX_CLIPBOARD_WATCHER"],
                        "text/plain",
                        "--",
                        sys.executable,
                        "-c",
                        "raise SystemExit(23)",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                assert failed_capture.returncode == 1, failed_capture.stderr
                assert b"capture command exited with status 23" in failed_capture.stderr
                store.set_paused(False)
                settings = root / "config/nix-clipboard-history/config.json"
                settings.parent.mkdir(parents=True, exist_ok=True)
                settings.write_text('{"capture_images":false}')
                daemon = subprocess.Popen(daemon_command, **daemon_options)
                wait_for(store.daemon_running, "text-only service")
                time.sleep(0.3)
                check_offer(
                    store,
                    root,
                    "images-disabled-text-fallback",
                    [
                        ("image/png", image),
                        ("text/plain", b"text when images disabled"),
                    ],
                    (b"text when images disabled", "text/plain;charset=utf-8"),
                )
                check_offer(store, root, "images-disabled-image-only", [("image/png", image)], None)
                daemon.send_signal(signal.SIGTERM)
                assert daemon.wait(timeout=5) == 0 and not store.daemon_running()
            print(
                "Wayland smoke passed: real text/image capture, ownership, sensitive hints, "
                "pause/resume, deduplication, and daemon shutdown."
            )
        except BaseException:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            for process in (daemon, pointer, compositor):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package", type=Path, help="Test an installed Nix package outside the checkout"
    )
    args = parser.parse_args()
    main(args.package.resolve() if args.package else None)
