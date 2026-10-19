import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import app


class HttpArchiveTest(unittest.TestCase):
    def test_hand_archive_and_observation_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            original = (app.DATA, app.PROFILES, app.GAME_FILE, app.HAND_HISTORY, app.ARCHIVE_DB, app.UNDO_FILE)
            app.DATA = Path(temp)
            app.PROFILES = app.DATA / "profiles.json"
            app.GAME_FILE = app.DATA / "current_game.json"
            app.HAND_HISTORY = app.DATA / "hands.jsonl"
            app.ARCHIVE_DB = app.DATA / "archive.sqlite3"
            app.UNDO_FILE = app.DATA / "undo.json"
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def post(route, body):
                request = Request(base + route, data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json"})
                with urlopen(request) as response:
                    return json.load(response)

            def get(route):
                with urlopen(base + route) as response:
                    return json.load(response)

            try:
                post("/api/game/start", {"players": [{"name": "我", "stack": 50},
                                                     {"name": "对手", "stack": 50}],
                                         "hero": 0, "button": 0, "small_blind": 0.5, "big_blind": 1})
                post("/api/game/cards", {"seat": 0, "cards": ["As", "Kd"]})
                post("/api/game/cards", {"seat": 1, "cards": ["Qh", "Qc"]})
                observed = get("/api/game/observation")["observation"]
                self.assertEqual(observed["hero_cards"], ["As", "Kd"])
                self.assertNotIn("Qh", json.dumps(observed))
                post("/api/game/action", {"action": "fold"})
                post("/api/game/next", {})
                page = get("/api/hands?limit=10")
                self.assertEqual(len(page["hands"]), 1)
                archived = get("/api/hands/" + page["hands"][0]["hand_id"])["hand"]
                self.assertEqual(archived["result"]["method"], "fold")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                app.DATA, app.PROFILES, app.GAME_FILE, app.HAND_HISTORY, app.ARCHIVE_DB, app.UNDO_FILE = original


if __name__ == "__main__":
    unittest.main()
