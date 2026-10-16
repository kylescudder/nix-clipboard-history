import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = {
            **os.environ,
            "XDG_DATA_HOME": self.temp.name,
            "XDG_CONFIG_HOME": self.temp.name,
            "CLIPBOARD_STATE": "data",
            "HYPRLAND_INSTANCE_SIGNATURE": "",
        }

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, data=b"", **env):
        return subprocess.run(
            [sys.executable, "-m", "nix_clipboard_history", *args],
            input=data,
            capture_output=True,
            env={**self.env, **env},
            timeout=10,
        )

    def test_capture_and_search_roundtrip_through_separate_processes(self):
        result = self.cli("capture", data="hello\nworld 🙂".encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("list", "WORLD")
        entries = json.loads(result.stdout)
        self.assertEqual(len(entries), 1)
        self.assertNotIn("body", entries[0])
        self.assertEqual(entries[0]["title"], "hello world 🙂")

    def test_sensitive_nil_and_clear_states_are_not_persisted(self):
        for state in ("sensitive", "nil", "clear", "unknown"):
            self.assertEqual(
                self.cli("capture", data=b"secret", CLIPBOARD_STATE=state).returncode, 0
            )
        self.assertEqual(json.loads(self.cli("list").stdout), [])

    def test_auto_capture_uses_the_selected_image_mime(self):
        result = self.cli(
            "capture",
            "--kind",
            "auto",
            data=b"\x89PNG\r\n\x1a\nimage",
            CLIPBOARD_TYPE="image/png",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads(self.cli("list").stdout)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "image")
        self.assertEqual(entries[0]["mime_type"], "image/png")

    def test_auto_capture_preserves_plain_text(self):
        result = self.cli(
            "capture",
            "--kind",
            "auto",
            data=b"one\ntwo\n",
            CLIPBOARD_TYPE="text/plain;charset=utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads(self.cli("list").stdout)
        self.assertEqual([entry["kind"] for entry in entries], ["text"])

    def test_auto_capture_rejects_missing_unsupported_and_sensitive_types(self):
        for mime in ("", "image/svg+xml", "text/html", "application/octet-stream"):
            self.assertEqual(
                self.cli(
                    "capture",
                    "--kind",
                    "auto",
                    data=b"do not capture",
                    CLIPBOARD_TYPE=mime,
                ).returncode,
                0,
            )
        self.cli(
            "capture",
            "--kind",
            "auto",
            data=b"sensitive",
            CLIPBOARD_TYPE="text/plain",
            CLIPBOARD_STATE="sensitive",
        )
        self.assertEqual(json.loads(self.cli("list").stdout), [])

    def test_auto_capture_respects_disabled_images(self):
        directory = Path(self.temp.name) / "nix-clipboard-history"
        directory.mkdir()
        (directory / "config.json").write_text('{"capture_images":false}')
        self.assertEqual(
            self.cli(
                "capture",
                "--kind",
                "auto",
                data=b"\x89PNG\r\n\x1a\nimage",
                CLIPBOARD_TYPE="image/png",
            ).returncode,
            0,
        )
        self.assertEqual(json.loads(self.cli("list").stdout), [])

    def test_pause_and_resume_apply_to_new_capture_processes(self):
        self.cli("pause")
        self.cli("capture", data=b"not stored")
        self.assertEqual(json.loads(self.cli("status").stdout)["items"], 0)
        self.cli("resume")
        self.cli("capture", data=b"stored")
        self.assertEqual(json.loads(self.cli("status").stdout)["items"], 1)

    def test_clear_requires_explicit_confirmation(self):
        self.cli("capture", data=b"keep")
        self.assertEqual(self.cli("clear").returncode, 2)
        self.assertEqual(json.loads(self.cli("status").stdout)["items"], 1)
        self.assertEqual(self.cli("clear", "--yes").returncode, 0)
        self.assertEqual(json.loads(self.cli("status").stdout)["items"], 0)

    def test_nonexistent_id_has_readable_error(self):
        result = self.cli("copy", "999")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"no longer exists", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_invalid_config_has_readable_error(self):
        directory = Path(self.temp.name) / "nix-clipboard-history"
        directory.mkdir()
        (directory / "config.json").write_text('{"max_items":false}')
        result = self.cli("status")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"max_items must be a int", result.stderr)


if __name__ == "__main__":
    unittest.main()
