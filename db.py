import os
import sqlite3
import threading
from datetime import date
from pathlib import Path

from config import BASE_DIR

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
