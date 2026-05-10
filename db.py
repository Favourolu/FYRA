import os
import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from config import BASE_DIR, MEMORY_DIR, LOGS_DIR

DB_PATH = BASE_DIR / "fyra.db"
DAILY_CAP_USD = float(os.getenv("DAILY_SPEND_CAP", "5.0"))

# Cost per 1M tokens (input / output)
_COSTS = {
    "claude-sonnet-4-6":         {"in": 3.0,  "out": 15.0},
    "claude-haiku-4-5-20251001": {"in": 1.0,  "out": 5.0},
}

_write_lock = threading.Lock()


class BudgetExceeded(Exception):
    pass


def _connect():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_db_conn():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                day        TEXT    NOT NULL,
                model      TEXT    NOT NULL,
                input_tok  INTEGER DEFAULT 0,
                output_tok INTEGER DEFAULT 0,
                calls      INTEGER DEFAULT 0,
                PRIMARY KEY (day, model)
            )
        """)
        conn.commit()
    init_memory_tables()
    migrate_json_to_sqlite()


def init_memory_tables():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                person TEXT NOT NULL,
                field  TEXT NOT NULL,
                value  TEXT NOT NULL,
                PRIMARY KEY (person, field)
            );

            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                event_type  TEXT,
                date        TEXT,
                title       TEXT,
                description TEXT,
                tags        TEXT DEFAULT '[]',
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                person    TEXT,
                mood      TEXT,
                note      TEXT
            );

            CREATE TABLE IF NOT EXISTS plans (
                id          TEXT PRIMARY KEY,
                plan_type   TEXT,
                title       TEXT,
                description TEXT,
                status      TEXT DEFAULT 'idea',
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT,
                topic      TEXT,
                was_wrong  TEXT,
                correct_is TEXT,
                UNIQUE(topic, was_wrong)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user_text TEXT,
                fyra_text TEXT
            );

            CREATE TABLE IF NOT EXISTS patterns (
                id           INTEGER PRIMARY KEY CHECK(id = 1),
                question_log TEXT DEFAULT '[]',
                insights     TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS calendar_tokens (
                person        TEXT PRIMARY KEY,
                access_token  TEXT,
                refresh_token TEXT,
                expiry        TEXT,
                scopes        TEXT
            );

            CREATE TABLE IF NOT EXISTS watchlist_prices (
                person     TEXT,
                ticker     TEXT,
                price      REAL,
                checked_at TEXT,
                PRIMARY KEY (person, ticker)
            );

            CREATE TABLE IF NOT EXISTS voice_profiles (
                person       TEXT PRIMARY KEY,
                avg_rms      REAL,
                pitch_mean   REAL,
                pitch_std    REAL,
                sample_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notices (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                person  TEXT,
                topic   TEXT,
                sent_at TEXT
            );
        """)
        conn.commit()


def migrate_json_to_sqlite():
    """One-time migration: read existing JSON files, insert into SQLite if tables are empty."""
    try:
        with get_db_conn() as conn:
            _migrate_profiles(conn)
            _migrate_events(conn)
            _migrate_checkins(conn)
            _migrate_plans(conn)
            _migrate_conversations(conn)
            _migrate_patterns(conn)
            _migrate_corrections(conn)
            conn.commit()
    except Exception:
        pass


def _migrate_profiles(conn):
    if conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] > 0:
        return
    path = MEMORY_DIR / "profiles.json"
    if not path.exists():
        return
    try:
        profiles = json.loads(path.read_text())
        for person, data in profiles.items():
            for field, value in data.items():
                v = json.dumps(value) if isinstance(value, (list, dict)) else (value or "")
                conn.execute(
                    "INSERT OR IGNORE INTO profiles (person, field, value) VALUES (?, ?, ?)",
                    (person, field, v)
                )
    except Exception:
        pass


def _migrate_events(conn):
    if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] > 0:
        return
    path = MEMORY_DIR / "events.json"
    if not path.exists():
        return
    try:
        import uuid
        from datetime import datetime
        events = json.loads(path.read_text())
        for e in events:
            conn.execute(
                "INSERT OR IGNORE INTO events (id, event_type, date, title, description, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    e.get("id", str(uuid.uuid4())),
                    e.get("type", "moment"),
                    e.get("date"),
                    e.get("title", ""),
                    e.get("description", ""),
                    json.dumps(e.get("tags", [])),
                    e.get("created_at", datetime.utcnow().isoformat()),
                )
            )
    except Exception:
        pass


def _migrate_checkins(conn):
    if conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] > 0:
        return
    path = MEMORY_DIR / "checkins.json"
    if not path.exists():
        return
    try:
        checkins = json.loads(path.read_text())
        for c in checkins:
            conn.execute(
                "INSERT INTO checkins (timestamp, person, mood, note) VALUES (?, ?, ?, ?)",
                (c.get("timestamp", ""), c.get("person", ""), c.get("mood", ""), c.get("note", ""))
            )
    except Exception:
        pass


def _migrate_plans(conn):
    if conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] > 0:
        return
    path = MEMORY_DIR / "plans.json"
    if not path.exists():
        return
    try:
        import uuid
        from datetime import datetime
        plans = json.loads(path.read_text())
        for p in plans:
            conn.execute(
                "INSERT OR IGNORE INTO plans (id, plan_type, title, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    p.get("id", str(uuid.uuid4())),
                    p.get("type", "todo"),
                    p.get("title", ""),
                    p.get("description", ""),
                    p.get("status", "idea"),
                    p.get("created_at", datetime.utcnow().isoformat()),
                )
            )
    except Exception:
        pass


def _migrate_conversations(conn):
    if conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] > 0:
        return
    path = LOGS_DIR / "conversation.json"
    if not path.exists():
        return
    try:
        turns = json.loads(path.read_text())
        for t in turns:
            conn.execute(
                "INSERT INTO conversations (timestamp, user_text, fyra_text) VALUES (?, ?, ?)",
                (t.get("timestamp", ""), t.get("user", ""), t.get("fyra", ""))
            )
    except Exception:
        pass


def _migrate_patterns(conn):
    if conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0] > 0:
        return
    path = LOGS_DIR / "patterns.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        conn.execute(
            "INSERT OR REPLACE INTO patterns (id, question_log, insights) VALUES (1, ?, ?)",
            (json.dumps(data.get("question_log", [])), data.get("insights", ""))
        )
    except Exception:
        pass


def _migrate_corrections(conn):
    if conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] > 0:
        return
    path = MEMORY_DIR / "corrections.json"
    if not path.exists():
        return
    try:
        corrections = json.loads(path.read_text())
        for c in corrections:
            conn.execute(
                "INSERT OR IGNORE INTO corrections (timestamp, topic, was_wrong, correct_is) VALUES (?, ?, ?, ?)",
                (c.get("timestamp", ""), c.get("topic", ""), c.get("was_wrong", ""), c.get("correct_is", ""))
            )
    except Exception:
        pass


init_db()


def _cost(model: str, inp: int, out: int) -> float:
    rates = _COSTS.get(model, {"in": 3.0, "out": 15.0})
    return (inp * rates["in"] + out * rates["out"]) / 1_000_000


def get_today_spend() -> float:
    today = date.today().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT model, input_tok, output_tok FROM api_usage WHERE day=?",
            (today,)
        ).fetchall()
    return sum(_cost(m, i, o) for m, i, o in rows)


def check_budget():
    spend = get_today_spend()
    if spend >= DAILY_CAP_USD:
        raise BudgetExceeded(
            f"Daily API budget of ${DAILY_CAP_USD:.2f} reached "
            f"(${spend:.2f} spent today). I'll be back tomorrow."
        )


def track_usage(model: str, input_tokens: int, output_tokens: int):
    today = date.today().isoformat()
    with _write_lock:
        with _connect() as conn:
            conn.execute("""
                INSERT INTO api_usage (day, model, input_tok, output_tok, calls)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(day, model) DO UPDATE SET
                    input_tok  = input_tok  + excluded.input_tok,
                    output_tok = output_tok + excluded.output_tok,
                    calls      = calls      + 1
            """, (today, model, input_tokens, output_tokens))
            conn.commit()


def get_usage_summary() -> dict:
    today = date.today().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT model, input_tok, output_tok, calls FROM api_usage WHERE day=?",
            (today,)
        ).fetchall()
    total_cost = sum(_cost(m, i, o) for m, i, o, _ in rows)
    total_calls = sum(c for _, _, _, c in rows)
    return {
        "date": today,
        "spend_usd": round(total_cost, 4),
        "cap_usd": DAILY_CAP_USD,
        "calls": total_calls,
        "remaining_usd": round(max(0.0, DAILY_CAP_USD - total_cost), 4),
        "pct_used": round(min(100.0, total_cost / DAILY_CAP_USD * 100), 1),
    }
