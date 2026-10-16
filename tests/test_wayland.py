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
            run.call_args.args[0],
            [
                "hyprctl",
                "dispatch",
                'hl.dsp.send_shortcut({mods="CTRL", key="V", window="address:0xabc"})',
            ],
        )
        self.assertEqual(run.call_count, 1)

    @patch("nix_clipboard_history.wayland.active_window")
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_terminal_paste_adds_shift(self, run, active):
        target = Target("0xabc", "com.mitchellh.ghostty")
        active.return_value = target
        run.return_value = subprocess.CompletedProcess([], 0, b"ok\n")
        paste(target, Config())
        self.assertEqual(
            run.call_args.args[0][-1],
            'hl.dsp.send_shortcut({mods="CTRL SHIFT", key="V", window="address:0xabc"})',
        )

    @patch("nix_clipboard_history.wayland.active_window", return_value=Target("0xabc", "kitty"))
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_legacy_parser_rejection_falls_back_to_legacy_shortcut(self, run, _active):
        run.side_effect = [
            subprocess.CompletedProcess([], 1, b"Invalid dispatcher\n"),
            subprocess.CompletedProcess([], 0, b"ok\n"),
        ]
        paste(Target("0xabc", "kitty"), Config())
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args.args[0],
            ["hyprctl", "dispatch", "sendshortcut", "CTRL SHIFT,V,address:0xabc"],
        )

    @patch("nix_clipboard_history.wayland.active_window", return_value=Target("0xabc", "firefox"))
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_lua_dispatch_error_does_not_retry_and_risk_duplicate_paste(self, run, _active):
        run.return_value = subprocess.CompletedProcess([], 1, b"send_shortcut: window not found")
        with self.assertRaisesRegex(RuntimeError, "could not send"):
            paste(Target("0xabc", "firefox"), Config())
        self.assertEqual(run.call_count, 1)

    @patch("nix_clipboard_history.wayland.active_window")
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_focus_is_rechecked_before_legacy_fallback(self, run, active):
        active.side_effect = [Target("0xabc", "firefox"), Target("0xdef", "other")]
        run.return_value = subprocess.CompletedProcess([], 1, b"Invalid dispatcher\n")
        with self.assertRaisesRegex(RuntimeError, "focused window changed"):
            paste(Target("0xabc", "firefox"), Config())
        self.assertEqual(run.call_count, 1)

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
    def test_paste_timeout_leaves_an_actionable_error(self, run, _active):
        with self.assertRaisesRegex(RuntimeError, "Hyprland did not respond"):
            paste(Target("0xabc", "firefox"), Config())
        self.assertEqual(run.call_count, 1)

    @patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "example"})
    @patch("nix_clipboard_history.wayland.subprocess.run")
    def test_rejects_malformed_compositor_response(self, run):
        for data in [b"invalid json", b"[]", b'{"address":"0xabc,malicious"}', b"{}"]:
            run.return_value = subprocess.CompletedProcess([], 0, data)
            self.assertEqual(active_window(), Target())
