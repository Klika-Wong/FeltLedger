import unittest

from game import act, legal, set_board, set_cards, settle, side_pots, start, next_hand, pot


def table(stacks=(100, 100), button=0):
    return start({"players": [{"name": f"P{i}", "stack": stack} for i, stack in enumerate(stacks)],
                  "button": button, "hero": 0, "small_blind": 0.5, "big_blind": 1})


class GameTest(unittest.TestCase):
    def test_heads_up_order_and_full_hand(self):
        game = table()
        self.assertEqual((game["small_blind_seat"], game["big_blind_seat"]), (0, 1))
        self.assertEqual(legal(game)["seat"], 0)
        set_cards(game, 0, ["As", "Ad"])
        set_cards(game, 1, ["Ks", "Kd"])
        act(game, "call")
        self.assertEqual(legal(game)["seat"], 1)
        act(game, "check")
        self.assertEqual(game["phase"], "board")
        set_board(game, ["2c", "3d", "4h"])
        self.assertEqual(legal(game)["seat"], 1)
        act(game, "check")
        act(game, "check")
        set_board(game, ["5s"])
        act(game, "check")
        act(game, "check")
        set_board(game, ["9c"])
        act(game, "check")
        act(game, "check")
        self.assertEqual(game["phase"], "showdown")
        settle(game)
        self.assertEqual(game["result"]["method"], "verified_cards")
        self.assertEqual(game["players"][0]["stack"], 10100)
        self.assertEqual(game["players"][1]["stack"], 9900)
        following = next_hand(game)
        self.assertEqual(following["button"], 1)
        self.assertEqual(following["board"], [])

    def test_fold_wins_without_board(self):
        game = table()
        act(game, "fold")
        self.assertEqual(game["phase"], "complete")
        self.assertEqual(game["players"][1]["stack"], 10050)

    def test_short_all_in_side_pot_and_uncalled_return(self):
        game = table((20, 50, 100), button=2)
        # Button P2, SB P0, BB P1, first action P2.
        act(game, "raise_to", 60)
        act(game, "all_in")  # P0 to 20
        act(game, "all_in")  # P1 to 50
        self.assertEqual(game["phase"], "board")
        self.assertEqual(game["players"][2]["stack"], 50 * 100)  # 10 returned
        self.assertEqual([side["amount"] for side in side_pots(game)], [6000, 6000])
        self.assertEqual(pot(game), 12000)
        set_cards(game, 0, ["As", "Ad"])
        set_cards(game, 1, ["Ks", "Kd"])
        set_cards(game, 2, ["Qs", "Qd"])
        for cards in (["2c", "3d", "4h"], ["5s"], ["9c"]):
            set_board(game, cards)
        settle(game)
        self.assertEqual([p["stack"] for p in game["players"]], [6000, 6000, 5000])
        self.assertEqual(game["result"]["awards"], {"0": 6000, "1": 6000})

    def test_short_raise_does_not_reopen(self):
        game = table((100, 100, 1.5), button=1)
        # P1 button calls, P2 small blind makes a short all-in raise to 1.5.
        act(game, "call")
        act(game, "all_in")
        self.assertEqual(game["current_bet"], 150)
        act(game, "call")  # P0 big blind responds.
        self.assertEqual(legal(game)["seat"], 1)
        self.assertFalse(legal(game)["can_raise"])
        with self.assertRaises(ValueError):
            act(game, "raise_to", 4)

    def test_duplicate_known_card(self):
        game = table()
        set_cards(game, 0, ["As", "Kd"])
        with self.assertRaises(ValueError):
            set_cards(game, 1, ["As", "Qd"])

    def test_total_chips_is_checked(self):
        config = {"players": [{"name": "我", "stack": 30}, {"name": "对手", "stack": 70}],
                  "button": 0, "hero": 0, "small_blind": 0.5, "big_blind": 1, "total_chips": 100}
        self.assertEqual(start(config)["table_total"], 10000)
        config["total_chips"] = 99
        with self.assertRaises(ValueError):
            start(config)

    def test_opponent_can_bet_and_raise_each_street(self):
        game = table((100, 100, 100), button=0)
        act(game, "call")
        act(game, "call")
        act(game, "check")
        set_board(game, ["2c", "7d", "Jh"])
        self.assertEqual(legal(game)["seat"], 1)
        act(game, "raise_to", 2)  # first post-flop bet
        self.assertEqual(legal(game)["seat"], 2)
        act(game, "raise_to", 5)
        act(game, "call")
        act(game, "call")
        self.assertEqual(game["street"], "turn")
        self.assertEqual(game["phase"], "board")
        self.assertEqual(pot(game), 1800)

    def test_unknown_showdown_requires_manual_award(self):
        game = table()
        act(game, "call")
        act(game, "check")
        for cards in (["2c", "3d", "4h"], ["5s"], ["9c"]):
            set_board(game, cards)
            act(game, "check")
            act(game, "check")
        with self.assertRaises(ValueError):
            settle(game)
        settle(game, {"0": 2})
        self.assertEqual(game["result"]["method"], "manual_unverified")

    def test_no_extra_actions_when_only_one_player_can_bet(self):
        game = table((10, 20, 100, 100), button=3)
        act(game, "raise_to", 30)  # P2
        act(game, "call")          # P3
        act(game, "all_in")        # P0 small blind
        act(game, "all_in")        # P1 big blind
        set_board(game, ["2c", "3d", "4h"])
        self.assertEqual(legal(game)["seat"], 2)
        act(game, "fold")          # P3 is now the only player with chips
        self.assertEqual(game["phase"], "board")
        self.assertEqual(game["street"], "turn")
        self.assertIsNone(legal(game))
        set_board(game, ["5s"])
        set_board(game, ["9c"])
        self.assertEqual(game["phase"], "showdown")


if __name__ == "__main__":
    unittest.main()
