import random
import tempfile
import unittest
from pathlib import Path

import app
from poker import advise, estimate_equity, hand_rank, parse_cards


class PokerTest(unittest.TestCase):
    def test_hand_order(self):
        straight_flush = hand_rank(parse_cards(["As", "Ks", "Qs", "Js", "Ts", "2d", "3c"]))
        quads = hand_rank(parse_cards(["Ah", "Ad", "Ac", "As", "Kd", "2c", "3d"]))
        full_house = hand_rank(parse_cards(["Ah", "Ad", "Ac", "Kd", "Kc", "2c", "3d"]))
        self.assertGreater(straight_flush, quads)
        self.assertGreater(quads, full_house)

    def test_ace_low_straight(self):
        self.assertEqual(hand_rank(parse_cards(["As", "2d", "3c", "4h", "5s"]))[0:2], (4, 5))

    def test_duplicate_card_rejected(self):
        with self.assertRaises(ValueError):
            advise({"hero": ["As", "As"], "board": [], "pot": 1, "call": 0})

    def test_forced_board_tie(self):
        equity = estimate_equity(parse_cards(["2c", "3d"]), parse_cards(["As", "Ks", "Qs", "Js", "Ts"]), 2,
                                 samples=20, rng=random.Random(1))
        self.assertAlmostEqual(equity, 1 / 3)

    def test_invalid_money(self):
        with self.assertRaises(ValueError):
            advise({"hero": ["As", "Kd"], "board": [], "pot": "nan", "call": 1})

    def test_no_call_has_no_call_ev(self):
        result = advise({"hero": ["As", "Kd"], "board": [], "opponents": 1, "pot": 3, "call": 0})
        self.assertIsNone(result["call_ev"])
        self.assertNotEqual(result["action"], "加注候选")

    def test_folded_opponent_ends_hand(self):
        result = app.advice_with_memory({"opponents": 1, "names": ["对手1"],
                                         "styles": ["unknown"], "active": [False]})
        self.assertEqual(result["action"], "本手结束")
        self.assertIsNone(result["equity"])

    def test_hand_recorded_only_once(self):
        with tempfile.TemporaryDirectory() as temp:
            original_data, original_profiles = app.DATA, app.PROFILES
            try:
                app.DATA = Path(temp)
                app.PROFILES = app.DATA / "profiles.json"
                payload = {"session_id": "test-once", "hand_id": "hand-1",
                           "players": [{"name": "对手1", "preflop": "check"}]}
                self.assertEqual(app.record_hand(payload)["profiles"]["对手1"]["vpip"], 0)
                with self.assertRaises(ValueError):
                    app.record_hand(payload)
                self.assertEqual(app.load_profiles()["对手1"]["hands"], 1)
            finally:
                app.DATA, app.PROFILES = original_data, original_profiles
                app.SESSIONS.pop("test-once", None)
                app.RECORDED_HANDS.pop("test-once", None)


if __name__ == "__main__":
    unittest.main()
