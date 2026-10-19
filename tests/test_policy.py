import json
import unittest

import game
import policy


class ObservationTest(unittest.TestCase):
    def test_opponent_private_cards_and_notes_are_excluded(self):
        state = game.start({"players": [{"name": "我", "stack": 100}, {"name": "对手", "stack": 100}],
                            "hero": 0, "button": 0, "small_blind": 0.5, "big_blind": 1})
        game.set_cards(state, 0, ["As", "Kd"])
        game.set_cards(state, 1, ["Qh", "Qc"])
        observed = policy.observation(state, {"对手": {"style": "tight", "hands": 12, "note": "私人备注"}})
        serialized = json.dumps(observed, ensure_ascii=False)
        self.assertEqual(observed["schema"], "PolicyInput-v1")
        self.assertEqual(observed["hero_cards"], ["As", "Kd"])
        self.assertEqual(observed["seats"][1]["observed_style"], "tight")
        for secret in ("Qh", "Qc", "私人备注", "对手"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
