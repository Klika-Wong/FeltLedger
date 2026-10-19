"""Manual, street-by-street no-limit hold'em hand recorder (amounts in cents)."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from itertools import combinations
from uuid import uuid4

from poker import hand_rank, parse_cards


STREETS = ("preflop", "flop", "turn", "river")
HAND_NAMES = ("高牌", "一对", "两对", "三条", "顺子", "同花", "葫芦", "四条", "同花顺")


def cents(value, *, allow_zero=True):
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("金额格式无效") from error
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("金额必须精确到分")
    result = int(amount * 100)
    if result < 0 or result > 100_000_000_000 or (not allow_zero and result == 0):
        raise ValueError("金额必须为合理的正数")
    return result


def next_seat(state, start, eligible=None):
    eligible = eligible if eligible is not None else set(range(len(state["players"])))
    for offset in range(1, len(state["players"]) + 1):
        seat = (start + offset) % len(state["players"])
        if seat in eligible:
            return seat
    raise ValueError("没有可用座位")


def order_after(state, start, eligible):
    count = len(state["players"])
    return [(start + offset) % count for offset in range(1, count + 1)
            if (start + offset) % count in eligible]


def live(state):
    return [i for i, player in enumerate(state["players"]) if not player["folded"]]


def can_act(state):
    return [i for i in live(state) if state["players"][i]["stack"] > 0]


def pot(state):
    return sum(player["committed"] for player in state["players"])


def record(state, kind, seat=None, amount=0, **extra):
    state["history"].append({"street": state["street"], "seat": seat, "kind": kind,
                             "amount": amount, **extra})


def commit(state, seat, amount, *, street=True):
    player = state["players"][seat]
    if amount < 0 or amount > player["stack"]:
        raise ValueError("投入超过剩余筹码")
    player["stack"] -= amount
    player["committed"] += amount
    if street:
        player["street_bet"] += amount
    return amount


def start(config):
    seats = config.get("players", [])
    if not isinstance(seats, list) or not 2 <= len(seats) <= 9:
        raise ValueError("牌桌人数需为 2–9")
    sb = cents(config.get("small_blind"), allow_zero=False)
    bb = cents(config.get("big_blind"), allow_zero=False)
    ante = cents(config.get("ante", 0))
    if sb >= bb:
        raise ValueError("小盲必须小于大盲")
    names = [str(player.get("name", "")).strip() for player in seats]
    if any(not name or len(name) > 40 for name in names) or len(set(names)) != len(names):
        raise ValueError("座位昵称不能为空、重复或超过 40 字")
    players = [{"name": name, "stack": cents(item.get("stack"), allow_zero=False),
                "committed": 0, "street_bet": 0, "folded": False, "cards": [], "start_stack": cents(item.get("stack"), allow_zero=False)}
               for name, item in zip(names, seats)]
    table_total = sum(player["stack"] for player in players)
    if config.get("total_chips") is not None and cents(config["total_chips"], allow_zero=False) != table_total:
        raise ValueError("座位筹码合计必须等于设置的牌桌总筹码")
    button = int(config.get("button", 0))
    hero = int(config.get("hero", 0))
    if not 0 <= button < len(players) or not 0 <= hero < len(players):
        raise ValueError("庄位或我的座位无效")
    state = {"id": uuid4().hex, "players": players, "button": button, "hero": hero,
             "table_total": table_total,
             "small_blind": sb, "big_blind": bb, "ante": ante, "board": [],
             "street": "preflop", "phase": "action", "current_bet": bb,
             "min_raise": bb, "pending": [], "acted_at": {}, "history": [],
             "result": None, "profiles_recorded": False}
    sb_seat = button if len(players) == 2 else next_seat(state, button)
    bb_seat = next_seat(state, sb_seat)
    state["small_blind_seat"] = sb_seat
    state["big_blind_seat"] = bb_seat
    for seat in range(len(players)):
        if ante:
            record(state, "ante", seat, commit(state, seat, min(ante, players[seat]["stack"]), street=False))
    for seat, amount, kind in ((sb_seat, sb, "small_blind"), (bb_seat, bb, "big_blind")):
        record(state, kind, seat, commit(state, seat, min(amount, players[seat]["stack"])))
    state["pending"] = order_after(state, bb_seat, set(can_act(state)))
    if len(can_act(state)) == 1 and state["pending"]:
        only = state["pending"][0]
        if players[only]["street_bet"] >= state["current_bet"]:
            state["pending"] = []
    if not state["pending"]:
        finish_round(state)
    return state


def unique_cards(state, seat=None, new_cards=None, new_board=None):
    board = state["board"] if new_board is None else new_board
    cards = list(board)
    for index, player in enumerate(state["players"]):
        cards.extend(new_cards if index == seat else player["cards"])
    if len(cards) != len(set(cards)):
        raise ValueError("本手出现重复的牌")


def set_cards(state, seat, cards):
    if state["phase"] == "complete":
        raise ValueError("本手已结束")
    seat = int(seat)
    if not 0 <= seat < len(state["players"]):
        raise ValueError("座位无效")
    parsed = parse_cards(cards)
    if len(parsed) not in (0, 2):
        raise ValueError("底牌只能留空或录入两张")
    unique_cards(state, seat=seat, new_cards=parsed)
    state["players"][seat]["cards"] = parsed
    return state


def legal(state):
    if state["phase"] != "action" or not state["pending"]:
        return None
    seat = state["pending"][0]
    player = state["players"][seat]
    to_call = max(0, state["current_bet"] - player["street_bet"])
    acted_at = state["acted_at"].get(str(seat))
    can_raise = acted_at is None or state["current_bet"] - acted_at >= state["min_raise"]
    return {"seat": seat, "to_call": min(to_call, player["stack"]),
            "can_check": to_call == 0, "can_raise": can_raise and player["stack"] > to_call and len(can_act(state)) > 1,
            "min_raise_to": state["current_bet"] + state["min_raise"] if state["current_bet"] else state["big_blind"],
            "max_to": player["street_bet"] + player["stack"]}


def act(state, action, amount=None):
    choice = legal(state)
    if choice is None:
        raise ValueError("当前不在行动阶段")
    seat = choice["seat"]
    player = state["players"][seat]
    old_bet = state["current_bet"]
    if action == "fold":
        player["folded"] = True
        record(state, "fold", seat)
    elif action == "check":
        if not choice["can_check"]:
            raise ValueError("面对下注不能过牌")
        record(state, "check", seat)
    elif action == "call":
        if choice["to_call"] == 0:
            raise ValueError("无需跟注时请过牌")
        paid = commit(state, seat, choice["to_call"])
        record(state, "call", seat, paid, all_in=player["stack"] == 0)
    elif action in ("raise_to", "all_in"):
        target = cents(amount) if action == "raise_to" else choice["max_to"]
        if target <= old_bet:
            if action != "all_in" or target <= player["street_bet"]:
                raise ValueError("加注目标必须高于当前下注")
            paid = commit(state, seat, target - player["street_bet"])
            record(state, "call", seat, paid, all_in=True)
        else:
            if not choice["can_raise"]:
                raise ValueError("短额全下后未重新开放加注")
            if target > choice["max_to"]:
                raise ValueError("加注超过剩余筹码")
            if target < choice["min_raise_to"] and target != choice["max_to"]:
                raise ValueError("低于最小加注；只有全下可例外")
            paid = commit(state, seat, target - player["street_bet"])
            state["current_bet"] = target
            if target - old_bet >= state["min_raise"]:
                state["min_raise"] = target - old_bet
            record(state, "bet" if old_bet == 0 else "raise", seat, paid,
                   to=target, all_in=player["stack"] == 0)
    else:
        raise ValueError("行动无效")
    state["acted_at"][str(seat)] = old_bet if action != "raise_to" and action != "all_in" else state["current_bet"]
    state["pending"].pop(0)
    if state["current_bet"] > old_bet:
        needs_action = {i for i in can_act(state) if i != seat and state["players"][i]["street_bet"] < state["current_bet"]}
        state["pending"] = order_after(state, seat, needs_action)
    if len(can_act(state)) == 1 and state["pending"]:
        only = state["pending"][0]
        if state["players"][only]["street_bet"] >= state["current_bet"]:
            state["pending"] = []
    if len(live(state)) == 1:
        winner = live(state)[0]
        won = pot(state)
        state["players"][winner]["stack"] += won
        state["result"] = {"method": "fold", "awards": {str(winner): won}, "pots": []}
        state["phase"] = "complete"
        state["pending"] = []
        record(state, "win_by_fold", winner, won)
    elif not state["pending"]:
        finish_round(state)
    return state


def refund_uncalled(state):
    live_seats = live(state)
    if not live_seats:
        return
    top = max(live_seats, key=lambda i: state["players"][i]["committed"])
    player = state["players"][top]
    others = [p["committed"] for i, p in enumerate(state["players"]) if i != top]
    difference = player["committed"] - max(others, default=0)
    if difference > 0:
        player["committed"] -= difference
        player["street_bet"] = max(0, player["street_bet"] - difference)
        player["stack"] += difference
        record(state, "uncalled_return", top, difference)


def finish_round(state):
    refund_uncalled(state)
    if state["street"] == "river":
        state["phase"] = "showdown"
    else:
        state["street"] = STREETS[STREETS.index(state["street"]) + 1]
        state["phase"] = "board"
        state["current_bet"] = 0
        state["min_raise"] = state["big_blind"]
        state["acted_at"] = {}
        for player in state["players"]:
            player["street_bet"] = 0


def set_board(state, cards):
    if state["phase"] != "board":
        raise ValueError("当前尚未进入发公共牌阶段")
    parsed = parse_cards(cards)
    expected = 3 if state["street"] == "flop" else 1
    if len(parsed) != expected:
        raise ValueError(f"本街应录入 {expected} 张新公共牌")
    unique_cards(state, new_board=state["board"] + parsed)
    state["board"].extend(parsed)
    record(state, "board", amount=0, cards=parsed)
    eligible = set(can_act(state))
    if len(eligible) >= 2:
        state["pending"] = order_after(state, state["button"], eligible)
        state["phase"] = "action"
    elif state["street"] == "river":
        state["phase"] = "showdown"
    else:
        state["street"] = STREETS[STREETS.index(state["street"]) + 1]
        state["phase"] = "board"
    return state


def best_hand(cards):
    if len(cards) < 5:
        return None
    five = max(combinations(cards, 5), key=hand_rank)
    rank = hand_rank(five)
    return {"name": HAND_NAMES[rank[0]], "cards": list(five), "rank": list(rank)}


def side_pots(state):
    levels = sorted({p["committed"] for p in state["players"] if p["committed"] > 0})
    previous = 0
    result = []
    for level in levels:
        contributors = [i for i, p in enumerate(state["players"]) if p["committed"] >= level]
        eligible = [i for i in contributors if not state["players"][i]["folded"]]
        amount = (level - previous) * len(contributors)
        if amount:
            if not eligible:
                raise ValueError("边池没有可获奖玩家；请核对行动线")
            result.append({"amount": amount, "eligible": eligible})
        previous = level
    return result


def settle(state, manual_awards=None):
    if state["phase"] != "showdown":
        raise ValueError("当前不是摊牌阶段")
    pots = side_pots(state)
    live_seats = live(state)
    known = all(len(state["players"][i]["cards"]) == 2 for i in live_seats)
    awards = {i: 0 for i in live_seats}
    if manual_awards is None:
        if not known:
            raise ValueError("仍有未知底牌；请录入亮牌或手动填写现场分池结果")
        ranks = {i: hand_rank(state["players"][i]["cards"] + state["board"]) for i in live_seats}
        for side in pots:
            best = max(ranks[i] for i in side["eligible"])
            winners = [i for i in side["eligible"] if ranks[i] == best]
            each, odd = divmod(side["amount"], len(winners))
            for i in winners:
                awards[i] += each
            for i in order_after(state, state["button"], set(winners))[:odd]:
                awards[i] += 1
        method = "verified_cards"
    else:
        if not isinstance(manual_awards, dict):
            raise ValueError("现场分池结果必须为座位与金额的对应表")
        for key, value in manual_awards.items():
            i = int(key)
            if i not in awards:
                raise ValueError("弃牌玩家不能获奖")
            awards[i] = cents(value)
        if sum(awards.values()) != pot(state):
            raise ValueError("现场获奖金额之和必须等于底池")
        method = "manual_unverified"
    for i, amount in awards.items():
        state["players"][i]["stack"] += amount
    state["result"] = {"method": method, "awards": {str(i): value for i, value in awards.items() if value}, "pots": pots,
                       "hands": {str(i): best_hand(state["players"][i]["cards"] + state["board"])
                                 for i in live_seats if len(state["players"][i]["cards"]) == 2}}
    state["phase"] = "complete"
    record(state, "showdown", amount=pot(state), method=method)
    return state


def next_hand(state):
    if state["phase"] != "complete":
        raise ValueError("本手未结束")
    seats = [{"name": p["name"], "stack": Decimal(p["stack"]) / 100}
             for p in state["players"] if p["stack"] > 0]
    if len(seats) < 2:
        raise ValueError("不足两位有筹码的玩家；请重新设置牌桌")
    old_to_new = {old: new for new, old in enumerate(i for i, p in enumerate(state["players"]) if p["stack"] > 0)}
    old_button = next_seat(state, state["button"], set(old_to_new))
    hero = old_to_new.get(state["hero"])
    if hero is None:
        raise ValueError("我的座位已无筹码；请重新设置牌桌")
    return start({"players": seats, "button": old_to_new[old_button], "hero": hero,
                  "small_blind": Decimal(state["small_blind"]) / 100,
                  "big_blind": Decimal(state["big_blind"]) / 100,
                  "ante": Decimal(state["ante"]) / 100})
