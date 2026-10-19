"""Small, dependency-free hold'em evaluator and advice prototype."""

from collections import Counter
import math
import random
import re

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = [rank + suit for rank in RANKS for suit in SUITS]


def parse_cards(value):
    if not isinstance(value, list):
        raise ValueError("牌必须是数组")
    if any(not isinstance(card, str) or not re.fullmatch(r"[2-9TJQKA][cdhs]", card.strip(), re.I) for card in value):
        raise ValueError("牌无效；格式示例：As、Td")
    cards = [card.strip()[0].upper() + card.strip()[1].lower() for card in value]
    if any(card not in DECK for card in cards) or len(cards) != len(set(cards)):
        raise ValueError("牌无效或重复；格式示例：As、Td")
    return cards


def straight_high(values):
    values = set(values)
    if 14 in values:
        values.add(1)
    for high in range(14, 4, -1):
        if (high in values and high - 1 in values and high - 2 in values
                and high - 3 in values and high - 4 in values):
            return high
    return 0


def hand_rank(cards):
    """Comparable tuple for a complete five to seven card hand."""
    counts = Counter(RANKS.index(card[0]) + 2 for card in cards)
    suits = {suit: [] for suit in SUITS}
    for card in cards:
        suits[card[1]].append(RANKS.index(card[0]) + 2)
    for values in suits.values():
        if len(values) >= 5:
            high = straight_high(values)
            if high:
                return (8, high)
    quads = sorted((rank for rank, count in counts.items() if count == 4), reverse=True)
    if quads:
        return (7, quads[0], max(rank for rank in counts if rank != quads[0]))
    trips = sorted((rank for rank, count in counts.items() if count >= 3), reverse=True)
    if trips:
        pairs = sorted((rank for rank, count in counts.items() if count >= 2 and rank != trips[0]), reverse=True)
        if pairs:
            return (6, trips[0], pairs[0])
    for values in suits.values():
        if len(values) >= 5:
            return (5, *sorted(values, reverse=True)[:5])
    high = straight_high(counts)
    if high:
        return (4, high)
    if trips:
        return (3, trips[0], *sorted((rank for rank in counts if rank != trips[0]), reverse=True)[:2])
    pairs = sorted((rank for rank, count in counts.items() if count >= 2), reverse=True)
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1], max(rank for rank in counts if rank not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *sorted((rank for rank in counts if rank != pairs[0]), reverse=True)[:3])
    return (0, *sorted(counts, reverse=True)[:5])


def estimate_equity_stats(hero, board, opponent_count, samples=350, rng=None):
    rng = rng or random.Random()
    deck = [card for card in DECK if card not in hero + board]
    needed = 5 - len(board) + 2 * opponent_count
    if needed > len(deck):
        raise ValueError("人数超出可用牌数")
    share = 0.0
    share_squared = 0.0
    for _ in range(samples):
        drawn = rng.sample(deck, needed)
        complete_board = board + drawn[:5 - len(board)]
        own = hand_rank(hero + complete_board)
        others = [hand_rank(drawn[5 - len(board) + 2 * i:5 - len(board) + 2 * i + 2] + complete_board)
                  for i in range(opponent_count)]
        best = max([own] + others)
        if own == best:
            value = 1 / (1 + sum(other == best for other in others))
            share += value
            share_squared += value * value
    mean = share / samples
    standard_error = math.sqrt(max(0, share_squared / samples - mean * mean) / samples)
    return mean, standard_error


def estimate_equity(hero, board, opponent_count, samples=350, rng=None):
    return estimate_equity_stats(hero, board, opponent_count, samples, rng)[0]


def advise(payload):
    hero = parse_cards(payload.get("hero", []))
    board = parse_cards(payload.get("board", []))
    if len(hero) != 2 or len(board) not in (0, 3, 4, 5) or len(set(hero + board)) != len(hero + board):
        raise ValueError("需录入两张底牌；公共牌为 0、3、4 或 5 张，且不得重复")
    count = int(payload.get("opponents", 1))
    if not 1 <= count <= 8:
        raise ValueError("对手数必须为 1–8")
    pot = float(payload.get("pot", 0))
    call = float(payload.get("call", 0))
    if not math.isfinite(pot) or not math.isfinite(call) or not 0 <= pot <= 1_000_000_000 or not 0 <= call <= 1_000_000_000:
        raise ValueError("底池和跟注额必须为非负且合理的数字")
    if payload.get("mode", "normal") not in ("normal", "squid"):
        raise ValueError("玩法无效")
    samples = 1500
    equity, standard_error = estimate_equity_stats(hero, board, count, samples)
    call_ev = equity * pot - (1 - equity) * call if call else None
    squid = payload.get("mode") == "squid" and bool(payload.get("squid_holder"))
    styles = payload.get("styles", [])
    allowed_styles = ("unknown", "tight", "loose", "aggressive", "passive", "tag", "lag", "nit", "calling_station", "bluffy")
    if not isinstance(styles, list) or any(style not in allowed_styles for style in styles):
        raise ValueError("对手标签无效")
    tight = sum(style in ("tight", "tag", "nit") for style in styles)
    loose = sum(style in ("loose", "lag", "calling_station") for style in styles)
    passive = sum(style in ("passive", "calling_station") for style in styles)
    aggressive = sum(style in ("aggressive", "lag", "bluffy") for style in styles)
    # A small explicit adjustment for exploration; never presented as a solved policy.
    raise_threshold = 0.68 + 0.02 * loose - 0.02 * tight + 0.02 * passive - 0.01 * aggressive - (0.04 if squid else 0)
    if call and call_ev < 0:
        action = "弃牌"
        reason = "随机手牌基线下，跟注净期望为负。"
    elif equity >= raise_threshold and pot > 0:
        action = "加注候选" if call else "下注候选"
        reason = "估计摊牌胜率较高；下注额度需结合真实对手范围复核。"
    elif call:
        action = "跟注"
        reason = "随机手牌基线下，跟注净期望为正。"
    else:
        action = "过牌"
        reason = "当前无需支付筹码；可保留后续决策空间。"
    if squid:
        reason += " 已计入鱿鱼持有者的轻度进攻倾向，未计入惩罚金的真实 EV。"
    return {
        "action": action, "equity": round(equity, 4), "call_ev": round(call_ev, 2) if call_ev is not None else None,
        "reason": reason, "samples": samples,
        "equity_interval": [round(max(0, equity - 1.96 * standard_error), 4),
                            round(min(1, equity + 1.96 * standard_error), 4)],
        "style_adjustment": round(raise_threshold - 0.68, 3),
        "disclaimer": "实验估算：对手底牌按随机分布抽样；不是 GTO、RL 策略或真实行动 EV。",
    }
