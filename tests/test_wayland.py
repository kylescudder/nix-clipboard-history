import os
import subprocess
import unittest
from unittest.mock import patch

from nix_clipboard_history.config import Config
from nix_clipboard_history.wayland import Target, active_window, copy, paste


class WaylandTests(unittest.TestCase):
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_copy_passes_raw_bytes_on_stdin_and_preserves_image_type(self, run):
        run.return_value = subprocess.CompletedProcess([], 0)
        payload = b"\x89PNG\x00\n$(echo never execute)"
        copy(payload, "image/png")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["wl-copy", "--type", "image/png"])
        self.assertEqual(kwargs["input"], payload)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("shell", kwargs)

    @patch("nix_clipboard_history.wayland.subprocess.run", side_effect=FileNotFoundError)
    def test_copy_failure_is_actionable(self, _run):
        with self.assertRaisesRegex(RuntimeError, "wl-copy is missing"):
            copy(b"hello", "text/plain")

    @patch("nix_clipboard_history.wayland.active_window")
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_paste_targets_the_original_window(self, run, active):
        target = Target("0xabc", "firefox")
        active.return_value = target
        run.return_value = subprocess.CompletedProcess([], 0, b"ok\n")
        paste(target, Config())
        self.assertEqual(
            run.call_args.args[0], ["hyprctl", "dispatch", "sendshortcut", "CTRL,V,address:0xabc"]
        )

    @patch("nix_clipboard_history.wayland.active_window")
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_terminal_paste_adds_shift(self, run, active):
        target = Target("0xabc", "com.mitchellh.ghostty")
        active.return_value = target
        run.return_value = subprocess.CompletedProcess([], 0, b"ok\n")
        paste(target, Config())
        self.assertEqual(run.call_args.args[0][-1], "CTRL SHIFT,V,address:0xabc")

    @patch("nix_clipboard_history.wayland.active_window")
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_focus_change_prevents_pasting_into_another_app(self, run, active):
        active.return_value = Target("0xdef", "other")
        with self.assertRaisesRegex(RuntimeError, "focused window changed"):
            paste(Target("0xabc", "firefox"), Config())
        run.assert_not_called()

    def test_no_target_leaves_content_for_manual_paste(self):
        with self.assertRaisesRegex(RuntimeError, "no Hyprland target"):
            paste(Target(), Config())

    @patch("nix_clipboard_history.wayland.active_window", return_value=Target("0xabc", "firefox"))
    @patch(
        "nix_clipboard_history.wayland.subprocess.run",
        side_effect=subprocess.TimeoutExpired("hyprctl", 3),
    )
    def test_paste_timeout_leaves_an_actionable_error(self, _run, _active):
        with self.assertRaisesRegex(RuntimeError, "Hyprland did not respond"):
            paste(Target("0xabc", "firefox"), Config())

    @patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "example"})
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_rejects_malformed_compositor_response(self, run):
        for data in [b"invalid json", b"[]", b'{"address":"0xabc,malicious"}', b"{}"]:
            run.return_value = subprocess.CompletedProcess([], 0, data)
            self.assertEqual(active_window(), Target())
