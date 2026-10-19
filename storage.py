"""Bounded, local storage for completed research hand records."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3


SCHEMA_VERSION = 1


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        db.close()
        raise ValueError("归档数据库版本高于当前程序；请升级程序")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS hands (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        hand_id TEXT NOT NULL UNIQUE,
        archived_at TEXT NOT NULL,
        player_count INTEGER NOT NULL,
        total_chips INTEGER NOT NULL,
        result_method TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""")
    if version == 0:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    db.commit()
    return db


def _insert(db, state):
    if state.get("phase") != "complete" or not state.get("id"):
        raise ValueError("只能归档已完成且有标识的手牌")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    result = db.execute("""INSERT INTO hands
        (hand_id, archived_at, player_count, total_chips, result_method, payload_json)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(hand_id) DO NOTHING""",
        (state["id"], datetime.now(timezone.utc).isoformat(), len(state["players"]),
         state["table_total"], state["result"]["method"], payload))
    return result.rowcount == 1


def archive_hand(path, state):
    with closing(connect(path)) as db, db:
        return _insert(db, state)


def list_hands(path, limit=10, before=None):
    if not 1 <= limit <= 50 or (before is not None and before < 1):
        raise ValueError("归档分页参数无效")
    with closing(connect(path)) as db:
        rows = db.execute("""SELECT sequence, hand_id, archived_at, player_count,
            total_chips, result_method FROM hands
            WHERE (? IS NULL OR sequence < ?) ORDER BY sequence DESC LIMIT ?""",
            (before, before, limit + 1)).fetchall()
    page = [dict(row) for row in rows[:limit]]
    return {"hands": page, "next_before": page[-1]["sequence"] if len(rows) > limit else None}


def get_hand(path, hand_id):
    with closing(connect(path)) as db:
        row = db.execute("SELECT payload_json FROM hands WHERE hand_id=?", (hand_id,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def iter_hands(path, batch_size=100):
    """Stream archived states for future offline evaluation without loading the archive."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("批量大小无效")
    with closing(connect(path)) as db:
        cursor = db.execute("SELECT payload_json FROM hands ORDER BY sequence")
        while batch := cursor.fetchmany(batch_size):
            for row in batch:
                yield json.loads(row["payload_json"])


def migrate_legacy(path, legacy_path, batch_size=100):
    """Import old JSONL in small transactions; keep the source as a renamed backup."""
    legacy_path = Path(legacy_path)
    if not legacy_path.exists():
        return 0
    imported = 0
    with closing(connect(path)) as db, legacy_path.open(encoding="utf-8") as source:
        batch = []
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"旧归档第 {number} 行不是有效 JSON；原文件已保留") from error
            if len(batch) >= batch_size:
                with db:
                    imported += sum(_insert(db, state) for state in batch)
                batch.clear()
        if batch:
            with db:
                imported += sum(_insert(db, state) for state in batch)
    backup = legacy_path.with_suffix(legacy_path.suffix + ".migrated")
    suffix = 1
    while backup.exists():
        backup = legacy_path.with_suffix(legacy_path.suffix + f".migrated.{suffix}")
        suffix += 1
    legacy_path.rename(backup)
    return imported
