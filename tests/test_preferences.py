import json
from pathlib import Path
import tempfile
import unittest
from proton_bridge_gtk import preferences


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "proton-bridge-gtk/preferences.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_or_invalid_files_are_empty(self):
        self.assertEqual(preferences.load(self.path), {})
        self.path.parent.mkdir(parents=True)
        for content in ("not json", "[1, 2]"):
            self.path.write_text(content)
            self.assertEqual(preferences.load(self.path), {})

    def test_changes_are_merged_and_kept_private(self):
        preferences.save(self.path, language="ru")
        preferences.save(self.path, sync_oldest_first=True, sync_repair_pending=True)
        stored = preferences.save(self.path, sync_repair_pending=False)
        expected = {"language": "ru", "sync_oldest_first": True, "sync_repair_pending": False}
        self.assertEqual(stored, expected)
        self.assertEqual(json.loads(self.path.read_text()), expected)
        self.assertTrue(self.path.read_bytes().isascii())
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_default_path_is_not_the_bridge_vault(self):
        self.assertEqual(preferences.default_path().parts[-2:], ("proton-bridge-gtk", "preferences.json"))
        self.assertNotIn("protonmail", preferences.default_path().parts)


if __name__ == "__main__":
    unittest.main()
