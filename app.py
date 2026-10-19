"""Local HTTP API for hand-recording research and experiments."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import os
import tempfile
import threading

from poker import advise
import game
import storage
import policy


ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("FELTLEDGER_DATA_DIR", ROOT / "data")).expanduser().resolve()
PROFILES = DATA / "profiles.json"
GAME_FILE = DATA / "current_game.json"
HAND_HISTORY = DATA / "hands.jsonl"
ARCHIVE_DB = DATA / "archive.sqlite3"
UNDO_FILE = DATA / "undo.json"
PROFILE_LOCK = threading.Lock()
SESSIONS = {}
RECORDED_HANDS = {}


def inferred_style(profile):
    hands = profile.get("hands", 0)
    if hands < 5:
        return "unknown"
    # Shrink a sparse sample toward a neutral 25% VPIP prior.
    vpip = (profile["vpip"] + 2.5) / (hands + 10)
    if vpip >= 0.35:
        return "loose"
    if vpip <= 0.18:
        return "tight"
    return "unknown"


def advice_with_memory(payload):
    names = payload.get("names", [])
    styles = payload.get("styles", [])
    active = payload.get("active", [])
    if not isinstance(names, list) or len(names) != int(payload.get("opponents", 1)):
        raise ValueError("对手昵称数量与人数不符")
    if not isinstance(styles, list) or len(styles) != len(names):
        raise ValueError("风格标签数量与人数不符")
    if not isinstance(active, list) or len(active) != len(names) or any(type(value) is not bool for value in active):
        raise ValueError("在局状态与人数不符")
    if not any(active):
        return {"action": "本手结束", "equity": None, "call_ev": None,
                "reason": "所有对手已弃牌；不需要再计算摊牌胜率。", "samples": 0,
                "effective_styles": [], "disclaimer": "请开始下一手。"}
    session_id = str(payload.get("session_id", ""))
    with PROFILE_LOCK:
        profiles = load_profiles()
        session = SESSIONS.get(session_id, {})
        resolved = []
        for name, style, is_active in zip(names, styles, active):
            if not is_active:
                continue
            if style != "unknown":
                resolved.append(style)
            else:
                short = inferred_style(session.get(name, {}))
                resolved.append(short if short != "unknown" else inferred_style(profiles.get(name, {})))
    result = advise({**payload, "opponents": sum(active), "styles": resolved})
    result["effective_styles"] = resolved
    return result


def load_profiles():
    if not PROFILES.exists():
        return {}
    value = json.loads(PROFILES.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("画像文件格式无效")
    return value


def save_profiles(profiles):
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DATA, delete=False) as file:
        json.dump(profiles, file, ensure_ascii=False, indent=2)
        temp = file.name
    os.replace(temp, PROFILES)


def load_game():
    if not GAME_FILE.exists():
        return None
    return json.loads(GAME_FILE.read_text(encoding="utf-8"))


def save_game(state):
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DATA, delete=False) as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        temp = file.name
    os.replace(temp, GAME_FILE)


def game_view(state):
    facts = {}
    for seat, player in enumerate(state["players"]):
        if len(player["cards"]) == 2 and len(state["board"]) >= 3:
            facts[str(seat)] = game.best_hand(player["cards"] + state["board"])
    return {**state, "pot": game.pot(state), "legal": game.legal(state), "facts": facts,
            "side_pots": game.side_pots(state) if state["phase"] in ("showdown", "complete") else []}


def record_game_profiles(state):
    if state["phase"] != "complete" or state.get("profiles_recorded"):
        return
    profiles = load_profiles()
    for seat, player in enumerate(state["players"]):
        name = player["name"]
        profile = profiles.setdefault(name, {"hands": 0, "vpip": 0, "pfr": 0})
        preflop = [entry for entry in state["history"] if entry["street"] == "preflop" and entry["seat"] == seat]
        profile["hands"] += 1
        profile["vpip"] += any(entry["kind"] in ("call", "raise", "bet") for entry in preflop)
        profile["pfr"] += any(entry["kind"] == "raise" for entry in preflop)
    save_profiles(profiles)
    state["profiles_recorded"] = True


def game_command(path, payload):
    with PROFILE_LOCK:
        current = load_game()
        if path == "/api/game/start":
            if current and current["phase"] != "complete" and payload.get("force") is not True:
                raise ValueError("当前手牌尚未结束；重设牌桌需先确认覆盖")
            state = game.start(payload)
            UNDO_FILE.unlink(missing_ok=True)
        else:
            if current is None:
                raise ValueError("请先设置牌桌")
            state = deepcopy(current)
            if path == "/api/game/undo":
                if not UNDO_FILE.exists():
                    raise ValueError("没有可撤销的操作")
                state = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
                UNDO_FILE.unlink()
                save_game(state)
                return game_view(state)
            if path == "/api/game/action":
                game.act(state, payload.get("action"), payload.get("amount"))
            elif path == "/api/game/board":
                game.set_board(state, payload.get("cards", []))
            elif path == "/api/game/cards":
                game.set_cards(state, payload.get("seat"), payload.get("cards", []))
            elif path == "/api/game/profile":
                seat = int(payload.get("seat", -1))
                name = str(payload.get("name", "")).strip()
                style = payload.get("style", "unknown")
                note = str(payload.get("note", "")).strip()
                if not 0 <= seat < len(state["players"]) or not name or len(name) > 40:
                    raise ValueError("座位或档案名称无效")
                if any(i != seat and p["name"] == name for i, p in enumerate(state["players"])):
                    raise ValueError("同一手不能有两个座位关联同一对手")
                if style not in ("unknown", "tight", "loose", "aggressive", "passive", "tag", "lag", "nit", "calling_station", "bluffy") or len(note) > 200:
                    raise ValueError("风格或备注无效")
                profiles = load_profiles()
                profile = profiles.setdefault(name, {"hands": 0, "vpip": 0, "pfr": 0})
                profile["style"] = style
                profile["note"] = note
                save_profiles(profiles)
                state["players"][seat]["name"] = name
            elif path == "/api/game/settle":
                game.settle(state, payload.get("awards"))
            elif path == "/api/game/next":
                if current["phase"] != "complete":
                    raise ValueError("本手未结束")
                state = game.next_hand(state)
                if storage.archive_hand(ARCHIVE_DB, current):
                    record_game_profiles(current)
                UNDO_FILE.unlink(missing_ok=True)
            else:
                raise ValueError("未知操作")
            if path != "/api/game/next":
                DATA.mkdir(parents=True, exist_ok=True)
                UNDO_FILE.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        save_game(state)
    return game_view(state)


def game_advice():
    state = load_game()
    profiles = load_profiles()
    observed = policy.observation(state, profiles)
    choice = observed["legal"]
    cards = observed["hero_cards"]
    if len(cards) != 2:
        raise ValueError("请先录入我的两张底牌")
    opponents = [seat for seat in observed["seats"]
                 if seat["seat"] != observed["hero_seat"] and not seat["folded"]]
    styles = []
    for seat in opponents:
        player = state["players"][seat["seat"]]
        profile = profiles.get(player["name"], {})
        style = seat["observed_style"]
        styles.append(style if style != "unknown" else inferred_style(profile))
    result = advise({"hero": cards, "board": observed["board"], "opponents": len(opponents),
                     "pot": observed["pot_cents"] / 100, "call": choice["to_call"] / 100,
                     "mode": "normal", "styles": styles})
    if result["action"] == "加注候选" and not choice["can_raise"]:
        result["action"] = "仅跟注或弃牌可选"
        result["reason"] = "当前行动线未重新开放加注；请在合法动作中复核。"
    result["model_accuracy"] = "未评估：胜率抽样精度不等于策略准确率"
    result["effective_styles"] = styles
    return result


def record_hand(payload):
    players = payload.get("players")
    if not isinstance(players, list) or not 1 <= len(players) <= 8:
        raise ValueError("每手需有 1–8 名对手")
    seen = set()
    session_id = str(payload.get("session_id", ""))
    hand_id = str(payload.get("hand_id", ""))
    if not 1 <= len(session_id) <= 80:
        raise ValueError("会话标识无效")
    if not 1 <= len(hand_id) <= 80:
        raise ValueError("手牌标识无效")
    for player in players:
        name = str(player.get("name", "")).strip()
        action = player.get("preflop")
        if not name or len(name) > 40 or name in seen:
            raise ValueError("对手昵称不能为空、重复或超过 40 字")
        if action not in ("fold", "check", "call", "raise"):
            raise ValueError("翻前行动必须是弃牌、过牌、跟注或加注")
        seen.add(name)
    with PROFILE_LOCK:
        recorded = RECORDED_HANDS.setdefault(session_id, set())
        if hand_id in recorded:
            raise ValueError("本手已记录；请先开始下一手")
        profiles = load_profiles()
        session = SESSIONS.setdefault(session_id, {})
        for player in players:
            for target in (profiles, session):
                profile = target.setdefault(player["name"].strip(), {"hands": 0, "vpip": 0, "pfr": 0})
                profile["hands"] += 1
                profile["vpip"] += player["preflop"] in ("call", "raise")
                profile["pfr"] += player["preflop"] == "raise"
        save_profiles(profiles)
        recorded.add(hand_id)
    return {"profiles": profiles, "session": session}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/":
            body = (ROOT / "web" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif request.path == "/api/profiles":
            self.send_json(200, {"profiles": load_profiles()})
        elif request.path == "/api/game":
            state = load_game()
            self.send_json(200, {"game": game_view(state) if state else None})
        elif request.path == "/api/game/observation":
            try:
                self.send_json(200, {"observation": policy.observation(load_game(), load_profiles())})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
        elif request.path == "/api/hands":
            try:
                query = parse_qs(request.query)
                limit = int(query.get("limit", ["10"])[0])
                before = int(query["before"][0]) if "before" in query else None
                self.send_json(200, storage.list_hands(ARCHIVE_DB, limit, before))
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
        elif request.path.startswith("/api/hands/"):
            hand_id = request.path.removeprefix("/api/hands/")
            if not hand_id or "/" in hand_id or len(hand_id) > 80:
                self.send_json(400, {"error": "手牌标识无效"})
                return
            state = storage.get_hand(ARCHIVE_DB, hand_id)
            self.send_json(200, {"hand": state}) if state else self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        game_paths = {"/api/game/start", "/api/game/action", "/api/game/board", "/api/game/cards",
                      "/api/game/settle", "/api/game/next", "/api/game/undo", "/api/game/profile"}
        if self.path not in {"/api/advice", "/api/hand", "/api/game/advice"} | game_paths:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("请求体长度无效")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求必须是对象")
            if self.path == "/api/advice":
                result = advice_with_memory(payload)
            elif self.path == "/api/hand":
                result = record_hand(payload)
            elif self.path == "/api/game/advice":
                result = game_advice()
            else:
                result = {"game": game_command(self.path, payload)}
            self.send_json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})


if __name__ == "__main__":
    storage.migrate_legacy(ARCHIVE_DB, HAND_HISTORY)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("本地原型：http://127.0.0.1:8765")
    server.serve_forever()
