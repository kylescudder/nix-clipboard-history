import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from nix_clipboard_history.config import Config
from nix_clipboard_history.store import Store, image_mime

PNG = b"\x89PNG\r\n\x1a\n" + b"example image bytes"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config()
        self.store = Store(Path(self.temp.name) / "private", self.config)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_preserves_exact_text_including_newlines_and_shell_characters(self):
        data = "  hello\n$(touch /tmp/unwanted) `echo nope`\n🙂\n".encode()
        entry_id = self.store.add(data, "text", "kitty")
        self.assertEqual(self.store.get(entry_id), (data, "text/plain;charset=utf-8"))

    def test_history_survives_reopening(self):
        entry_id = self.store.add(b"remember", "text")
        with Store(self.store.directory) as other:
            self.assertEqual(other.get(entry_id)[0], b"remember")

    def test_deduplicates_and_preserves_pins(self):
        first = self.store.add(b"first", "text")
        self.store.pin(first)
        self.store.add(b"second", "text")
        self.assertEqual(self.store.add(b"first", "text"), first)
        self.assertEqual(len(self.store.list()), 2)
        self.assertTrue(self.store.list()[0].pinned)

    def test_duplicate_moves_to_most_recent_position(self):
        first = self.store.add(b"first", "text")
        self.store.add(b"second", "text")
        self.store.add(b"first", "text")
        self.assertEqual(self.store.list()[0].id, first)

    def test_duplicate_updates_searchable_source(self):
        entry_id = self.store.add(b"shared", "text", "firefox")
        self.store.add(b"shared", "text", "kitty")
        self.assertEqual([e.id for e in self.store.list("kitty")], [entry_id])
        self.assertEqual(self.store.list("firefox"), [])
        self.store.add(b"shared", "text")
        self.assertEqual([e.id for e in self.store.list("kitty")], [entry_id])

    def test_search_is_unicode_casefolded_all_words_and_literal(self):
        wanted = self.store.add("Straße %_ hello\nworld".encode(), "text", "Firefox")
        self.store.add(b"hello planet", "text")
        self.assertEqual([e.id for e in self.store.list("STRASSE WORLD firefox %_")], [wanted])
        self.assertEqual(self.store.list("hello absent"), [])

    def test_type_and_pin_filters(self):
        text = self.store.add(b"example", "text")
        image = self.store.add(PNG, "image")
        self.store.pin(text)
        self.assertEqual([e.id for e in self.store.list(kind="image")], [image])
        self.assertEqual([e.id for e in self.store.list(kind="text")], [text])
        self.assertEqual([e.id for e in self.store.list(kind="pinned")], [text])

    def test_roundtrips_image_bytes_and_mime(self):
        entry_id = self.store.add(PNG, "image")
        self.assertEqual(self.store.get(entry_id), (PNG, "image/png"))

    def test_rejects_empty_binary_unknown_and_oversized_items(self):
        for data, kind in [
            (b"", "text"),
            (b" \n", "text"),
            (b"a\0b", "text"),
            (b"\xff", "text"),
            (b"<svg />", "image"),
            (b"abc", "file"),
        ]:
            with self.subTest(data=data):
                self.assertIsNone(self.store.add(data, kind))
        self.config.max_item_bytes = 4
        self.assertIsNone(self.store.add(b"12345", "text"))
        self.assertEqual(self.store.stats()["items"], 0)

    def test_images_can_be_disabled(self):
        self.config.capture_images = False
        self.assertIsNone(self.store.add(PNG, "image"))

    def test_paused_state_is_shared_and_blocks_writes(self):
        self.store.set_paused(True)
        with Store(self.store.directory) as other:
            self.assertTrue(other.paused)
            self.assertIsNone(other.add(b"private", "text"))
            other.set_paused(False)
        self.assertFalse(self.store.paused)
        self.assertIsNotNone(self.store.add(b"public", "text"))

    def test_count_limit_removes_oldest_but_keeps_pins(self):
        self.config.max_items = 2
        pin = self.store.add(b"keep", "text")
        self.store.pin(pin)
        old = self.store.add(b"old", "text")
        new = self.store.add(b"new", "text")
        self.assertEqual({e.id for e in self.store.list()}, {pin, new})
        with self.assertRaises(ValueError):
            self.store.get(old)

    def test_retention_prunes_expired_items_even_without_new_copies(self):
        old = self.store.add(b"old", "text")
        pin = self.store.add(b"pin", "text")
        self.store.pin(pin)
        self.store.db.execute("UPDATE entries SET updated_at=?", (time.time() - 31 * 86400,))
        self.store.prune()
        self.assertEqual([e.id for e in self.store.list()], [pin])
        with self.assertRaises(ValueError):
            self.store.get(old)

    def test_byte_budget_includes_pinned_items(self):
        self.config.max_total_bytes = 8
        pin = self.store.add(b"pinned", "text")
        self.store.pin(pin)
        self.assertIsNone(self.store.add(b"too large for remaining budget", "text"))
        item = self.store.add(b"ok", "text")
        self.assertEqual({e.id for e in self.store.list()}, {pin, item})

    def test_pinned_items_can_exceed_retention_budgets(self):
        pin = self.store.add(b"pinned", "text")
        self.store.pin(pin)
        self.config.max_total_bytes = 1
        self.store.prune()
        self.assertEqual(self.store.stats()["items"], 1)
        self.store.pin(pin)
        self.assertEqual(self.store.stats()["items"], 0)

    def test_clear_keeps_pins_unless_all_is_requested(self):
        pin = self.store.add(b"pin", "text")
        self.store.pin(pin)
        self.store.add(b"delete", "text")
        self.store.clear()
        self.assertEqual([e.id for e in self.store.list()], [pin])
        self.store.clear(include_pinned=True)
        self.assertEqual(self.store.list(), [])

    def test_delete_updates_other_readers(self):
        entry_id = self.store.add(b"delete", "text")
        with Store(self.store.directory) as other:
            revision = other.revision
            self.store.delete(entry_id)
            self.assertGreater(other.revision, revision)
            self.assertEqual(other.list(), [])

    def test_directory_and_database_are_private(self):
        self.assertEqual(os.stat(self.store.directory).st_mode & 0o777, 0o700)
        for path in self.store.directory.glob("history.sqlite3*"):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_supported_image_signatures(self):
        for data, expected in [
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"GIF89a", "image/gif"),
            (b"RIFF0000WEBP", "image/webp"),
            (b"II\x2a\x00", "image/tiff"),
            (b"BM1234", "image/bmp"),
        ]:
            self.assertEqual(image_mime(data), expected)


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Config.load(Path(directory) / "missing").max_items, 500)

    def test_loads_custom_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"auto_paste": False, "max_items": 50, "excluded_apps": ["foo"]})
            )
            config = Config.load(path)
            self.assertFalse(config.auto_paste)
            self.assertEqual(config.max_items, 50)

    def test_rejects_invalid_settings(self):
        for values in [
            {"max_items": 0},
            {"max_items": True},
            {"auto_paste": "yes"},
            {"excluded_apps": [1]},
            {"unknown": 1},
            {"paste_delay_ms": 5001},
            [],
        ]:
            with self.subTest(values=values), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(values))
                with self.assertRaises(ValueError):
                    Config.load(path)
