import tempfile
import unittest
from pathlib import Path

import app
import storage


class GameApiTest(unittest.TestCase):
    def test_profile_can_be_reused_across_hands(self):
        with tempfile.TemporaryDirectory() as temp:
            original = (app.DATA, app.PROFILES, app.GAME_FILE, app.HAND_HISTORY, app.ARCHIVE_DB, app.UNDO_FILE)
            try:
                app.DATA = Path(temp)
                app.PROFILES = app.DATA / "profiles.json"
                app.GAME_FILE = app.DATA / "current_game.json"
                app.HAND_HISTORY = app.DATA / "hands.jsonl"
                app.ARCHIVE_DB = app.DATA / "archive.sqlite3"
                app.UNDO_FILE = app.DATA / "undo.json"
                started = app.game_command("/api/game/start", {
                    "players": [{"name": "我", "stack": 50}, {"name": "座位2", "stack": 50}],
                    "hero": 0, "button": 0, "small_blind": 0.5, "big_blind": 1, "total_chips": 100})
                self.assertEqual(started["pot"], 150)
                app.game_command("/api/game/profile", {"seat": 1, "name": "常客甲", "style": "lag", "note": "常跟注"})
                self.assertEqual(app.load_profiles()["常客甲"]["style"], "lag")
                app.game_command("/api/game/action", {"action": "fold"})
                following = app.game_command("/api/game/next", {})
                self.assertEqual(following["players"][1]["name"], "常客甲")
                self.assertEqual(app.load_profiles()["常客甲"]["hands"], 1)
                self.assertEqual(len(storage.list_hands(app.ARCHIVE_DB)["hands"]), 1)
                self.assertFalse(app.HAND_HISTORY.exists())
                app.game_command("/api/game/start", {
                    "players": [{"name": "我", "stack": 40}, {"name": "对手5", "stack": 60}],
                    "hero": 0, "button": 0, "small_blind": 0.5, "big_blind": 1,
                    "total_chips": 100, "force": True})
                linked = app.game_command("/api/game/profile", {
                    "seat": 1, "name": "常客甲", "style": "tight", "note": "第二次见面后调整"})
                self.assertEqual(linked["players"][1]["name"], "常客甲")
                self.assertEqual(app.load_profiles()["常客甲"]["style"], "tight")
                self.assertEqual(app.load_profiles()["常客甲"]["hands"], 1)
            finally:
                app.DATA, app.PROFILES, app.GAME_FILE, app.HAND_HISTORY, app.ARCHIVE_DB, app.UNDO_FILE = original


if __name__ == "__main__":
    unittest.main()
