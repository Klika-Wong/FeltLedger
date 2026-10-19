"""Versioned, player-visible observation for future offline policy experiments."""

import game


def observation(state, profiles=None):
    if state is None:
        raise ValueError("请先设置牌桌")
    profiles = profiles or {}
    hero = state["hero"]
    choice = game.legal(state)
    if choice is None or choice["seat"] != hero:
        raise ValueError("仅在轮到我的座位时生成决策观测")
    seats = []
    for index, player in enumerate(state["players"]):
        profile = profiles.get(player["name"], {}) if index != hero else {}
        seats.append({
            "seat": index, "folded": player["folded"], "all_in": player["stack"] == 0,
            "stack_cents": player["stack"], "committed_cents": player["committed"],
            "street_bet_cents": player["street_bet"],
            "observed_style": profile.get("style", "unknown"),
            "observed_hands": profile.get("hands", 0),
        })
    history = [
        {key: entry[key] for key in ("street", "seat", "kind", "amount", "to", "all_in", "cards")
         if key in entry}
        for entry in state["history"]
    ]
    return {
        "schema": "PolicyInput-v1", "ruleset": "no-limit-holdem-standard-v1",
        "hand_id": state["id"], "decision_index": len(history),
        "hero_seat": hero, "button_seat": state["button"], "street": state["street"],
        "hero_cards": list(state["players"][hero]["cards"]), "board": list(state["board"]),
        "small_blind_cents": state["small_blind"], "big_blind_cents": state["big_blind"],
        "ante_cents": state["ante"], "pot_cents": game.pot(state),
        "legal": dict(choice), "seats": seats, "action_history": history,
    }
