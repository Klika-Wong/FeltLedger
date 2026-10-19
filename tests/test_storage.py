import json
import tempfile
import unittest
from pathlib import Path

import storage


def completed_hand(number):
    return {"id": f"hand-{number}", "phase": "complete", "players": [{"name": "我"}, {"name": "对手"}],
            "hero": 0, "table_total": 10000, "board": [], "history": [],
            "result": {"method": "fold", "awards": {"0": 150}}}


class ArchiveTest(unittest.TestCase):
    def test_archive_is_idempotent_and_paginated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive.sqlite3"
            for number in range(25):
                self.assertTrue(storage.archive_hand(path, completed_hand(number)))
            self.assertFalse(storage.archive_hand(path, completed_hand(24)))
            first = storage.list_hands(path, limit=10)
            self.assertEqual(len(first["hands"]), 10)
            self.assertEqual(first["hands"][0]["hand_id"], "hand-24")
            second = storage.list_hands(path, limit=10, before=first["next_before"])
            third = storage.list_hands(path, limit=10, before=second["next_before"])
            self.assertEqual(len({item["hand_id"] for page in (first, second, third) for item in page["hands"]}), 25)
            self.assertIsNone(third["next_before"])
            self.assertEqual(len(list(storage.iter_hands(path, batch_size=7))), 25)

    def test_legacy_migration_streams_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive.sqlite3"
            legacy = Path(temp) / "hands.jsonl"
            legacy.write_text("\n".join(json.dumps(completed_hand(i)) for i in range(3)) + "\n", encoding="utf-8")
            self.assertEqual(storage.migrate_legacy(path, legacy, batch_size=2), 3)
            self.assertFalse(legacy.exists())
            self.assertTrue(Path(str(legacy) + ".migrated").exists())
            self.assertEqual(len(storage.list_hands(path)["hands"]), 3)
            legacy.write_text(json.dumps(completed_hand(0)) + "\n", encoding="utf-8")
            self.assertEqual(storage.migrate_legacy(path, legacy), 0)


if __name__ == "__main__":
    unittest.main()
