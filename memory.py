import json
import uuid
import logging
from datetime import datetime, date
from pathlib import Path

from config import LOGS_DIR, MAX_MEMORY_ITEMS
from db import get_db_conn, _write_lock

MAX_CONVERSATION = 200

logging.basicConfig(
    filename=str(LOGS_DIR / "interactions.log"),
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# Ensure logs dir exists for the log file
LOGS_DIR.mkdir(parents=True, exist_ok=True)
_log_path = LOGS_DIR / "interactions.log"
if not _log_path.exists():
    _log_path.touch()


# ── Internal helpers ──────────────────────────────────────────

def _profile_to_dict(rows) -> dict:
    """Convert profile rows (person, field, value) into nested dict."""
    result = {}
    for row in rows:
        person = row["person"]
        field  = row["field"]
        raw    = row["value"]
        try:
            value = json.loads(raw)
        except Exception:
            value = raw
        if person not in result:
            result[person] = {}
        result[person][field] = value
    return result


def _get_profile(person: str) -> dict:
    with get_db_conn() as conn:
        rows = conn.execute(
            "SELECT person, field, value FROM profiles WHERE person = ?", (person,)
        ).fetchall()
    p = _profile_to_dict(rows).get(person, {})
    return p


def _set_profile_field(person: str, field: str, value):
    v = json.dumps(value) if isinstance(value, (list, dict)) else (value or "")
    with _write_lock:
        with get_db_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO profiles (person, field, value) VALUES (?, ?, ?)",
                (person, field, v)
            )
            conn.commit()


# ── Public API ────────────────────────────────────────────────

def load_all() -> dict:
    with get_db_conn() as conn:
        profile_rows = conn.execute("SELECT person, field, value FROM profiles").fetchall()
        event_rows   = conn.execute("SELECT * FROM events ORDER BY date ASC").fetchall()
        checkin_rows = conn.execute("SELECT * FROM checkins ORDER BY id ASC").fetchall()
        plan_rows    = conn.execute("SELECT * FROM plans ORDER BY created_at ASC").fetchall()

    profiles = _profile_to_dict(profile_rows)

    events = []
    for r in event_rows:
        events.append({
            "id": r["id"],
            "type": r["event_type"],        # remap event_type → "type" for compat
            "date": r["date"],
            "title": r["title"],
            "description": r["description"],
            "tags": json.loads(r["tags"] or "[]"),
        })

    checkins = []
    for r in checkin_rows:
        checkins.append({
            "timestamp": r["timestamp"],
            "person": r["person"],
            "mood": r["mood"],
            "note": r["note"],
        })

    plans = []
    for r in plan_rows:
        plans.append({
            "id": r["id"],
            "type": r["plan_type"],
            "title": r["title"],
            "description": r["description"],
            "status": r["status"],
            "created_at": r["created_at"],
        })

    return {"profiles": profiles, "events": events, "checkins": checkins, "plans": plans}


def get_relevant_memory(intent: str, user_input: str) -> str:
    mem = load_all()
    keywords = set(user_input.lower().split())
    sections = []

    def _profile_summary(person: str, profile: dict) -> str:
        lines = [f"  {person.capitalize()}:"]
        if profile.get("birthday"):
            lines.append(f"    Birthday: {profile['birthday']}")
        for key in ("likes", "dislikes", "hobbies", "facts"):
            items = profile.get(key, [])
            if items:
                lines.append(f"    {key.capitalize()}: {', '.join(str(i) for i in items)}")
        return "\n".join(lines)

    if intent in ("retrieve_memory", "store_memory", "general_chat", "task_help"):
        favour_summary = _profile_summary("favour", mem["profiles"].get("favour", {}))
        fiyin_summary  = _profile_summary("fiyin",  mem["profiles"].get("fiyin",  {}))
        sections.append("Profiles:\n" + favour_summary + "\n" + fiyin_summary)

    if intent in ("retrieve_memory", "store_memory"):
        matched_events = [
            e for e in mem["events"]
            if any(kw in (e.get("title", "") + e.get("description", "")).lower() for kw in keywords)
        ]
        recent_events = matched_events or mem["events"][-MAX_MEMORY_ITEMS:]
        if recent_events:
            event_lines = [
                f"  [{e.get('date', '?')}] {e.get('title', '')} — {e.get('description', '')}"
                for e in recent_events[-MAX_MEMORY_ITEMS:]
            ]
            sections.append("Events:\n" + "\n".join(event_lines))

    if intent in ("check_in", "suggest_action", "retrieve_memory"):
        recent_checkins = mem["checkins"][-MAX_MEMORY_ITEMS:]
        if recent_checkins:
            checkin_lines = [
                f"  [{c.get('timestamp', '?')[:10]}] {c.get('person', '?')}: {c.get('mood', '')} — {c.get('note', '')}"
                for c in recent_checkins
            ]
            sections.append("Recent check-ins:\n" + "\n".join(checkin_lines))

    if intent in ("suggest_action", "retrieve_memory", "task_help"):
        open_plans = [p for p in mem["plans"] if p.get("status") != "done"][-MAX_MEMORY_ITEMS:]
        if open_plans:
            plan_lines = [
                f"  [{p.get('type', '?')}] {p.get('title', '')} — {p.get('description', '')}"
                for p in open_plans
            ]
            sections.append("Plans & tasks:\n" + "\n".join(plan_lines))

    if intent == "market_query":
        with get_db_conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, person, mood, note FROM checkins ORDER BY id DESC LIMIT 2"
            ).fetchall()
        if rows:
            lines = [
                f"  [{r['timestamp'][:10]}] {r['person']}: {r['mood']} — {r['note']}"
                for r in reversed(rows)
            ]
            sections.append("Recent emotional context:\n" + "\n".join(lines))

    return "\n\n".join(sections) if sections else "No memory stored yet."


def apply_memory_update(extracted):
    if not extracted or not isinstance(extracted, dict):
        return
    if extracted.get("type") == "none":
        return

    kind = extracted.get("type")

    if kind == "profile":
        person = extracted.get("person", "").lower()
        key    = extracted.get("key")
        value  = extracted.get("value")

        targets = ["favour", "fiyin"] if person == "both" else [person]
        for t in targets:
            if key in ("likes", "dislikes", "hobbies", "facts"):
                current = _get_profile(t).get(key, [])
                new_items = value if isinstance(value, list) else [value]
                for item in new_items:
                    if item not in current:
                        current.append(item)
                _set_profile_field(t, key, current)
            else:
                _set_profile_field(t, key, value)

    elif kind == "event":
        with _write_lock:
            with get_db_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO events (id, event_type, date, title, description, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        extracted.get("event_type", "moment"),
                        extracted.get("date"),
                        extracted.get("title", ""),
                        extracted.get("description", ""),
                        json.dumps(extracted.get("tags", [])),
                        datetime.utcnow().isoformat(),
                    )
                )
                conn.commit()

    elif kind == "checkin":
        with _write_lock:
            with get_db_conn() as conn:
                conn.execute(
                    "INSERT INTO checkins (timestamp, person, mood, note) VALUES (?, ?, ?, ?)",
                    (
                        datetime.utcnow().isoformat(),
                        extracted.get("person", "both"),
                        extracted.get("mood", ""),
                        extracted.get("note", ""),
                    )
                )
                conn.commit()

    elif kind == "plan":
        with _write_lock:
            with get_db_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO plans (id, plan_type, title, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        extracted.get("plan_type", "todo"),
                        extracted.get("title", ""),
                        extracted.get("description", ""),
                        extracted.get("status", "idea"),
                        datetime.utcnow().isoformat(),
                    )
                )
                conn.commit()


# ── Conversation history ──────────────────────────────────────

def load_conversation_history(limit: int = 30) -> list:
    with get_db_conn() as conn:
        rows = conn.execute(
            "SELECT timestamp, user_text, fyra_text FROM conversations ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [{"timestamp": r["timestamp"], "user": r["user_text"], "fyra": r["fyra_text"]}
            for r in reversed(rows)]


def save_conversation_turn(user_text: str, fyra_text: str):
    with _write_lock:
        with get_db_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (timestamp, user_text, fyra_text) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), user_text, fyra_text)
            )
            conn.execute("""
                DELETE FROM conversations
                WHERE id NOT IN (
                    SELECT id FROM conversations ORDER BY id DESC LIMIT ?
                )
            """, (MAX_CONVERSATION,))
            conn.commit()


def get_history_for_assistant(limit: int = 5) -> list:
    history = load_conversation_history(limit)
    messages = []
    for turn in history:
        messages.append({"role": "user",      "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["fyra"]})
    return messages


# ── Live profile data for UI ──────────────────────────────────

def get_profile_panel_data() -> dict:
    with get_db_conn() as conn:
        profile_rows = conn.execute("SELECT person, field, value FROM profiles").fetchall()
        plan_rows    = conn.execute("SELECT status FROM plans").fetchall()

    profiles = _profile_to_dict(profile_rows)
    favour   = profiles.get("favour", {})
    fiyin    = profiles.get("fiyin",  {})
    open_tasks = sum(1 for r in plan_rows if r["status"] != "done")

    return {
        "favour": {
            "name":     favour.get("full_name", "Favour"),
            "birthday": favour.get("birthday", "—"),
            "likes":    favour.get("likes", [])[:3],
            "facts":    favour.get("facts", [])[:2],
        },
        "fiyin": {
            "name":     fiyin.get("full_name", "Fiyin"),
            "birthday": fiyin.get("birthday", "—"),
            "likes":    fiyin.get("likes", [])[:3],
            "facts":    fiyin.get("facts", [])[:2],
        },
        "open_tasks": open_tasks,
    }


# ── Startup reminders ─────────────────────────────────────────

def get_startup_brief() -> str:
    mem   = load_all()
    today = date.today()
    alerts = []

    for event in mem["events"]:
        event_date_str = event.get("date")
        if not event_date_str:
            continue
        try:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            this_year  = event_date.replace(year=today.year)
            days_until = (this_year - today).days
            if 0 <= days_until <= 7:
                label = "today" if days_until == 0 else f"in {days_until} day{'s' if days_until > 1 else ''}"
                alerts.append(f"{event.get('title', 'an event')} is {label}")
        except Exception:
            continue

    open_plans = [p for p in mem["plans"] if p.get("status") in ("idea", "planned")]
    if open_plans:
        alerts.append(f"{len(open_plans)} open task{'s' if len(open_plans) > 1 else ''} pending")

    if not alerts:
        return ""
    return "Quick brief: " + "; ".join(alerts) + "."


# ── Pattern learning ──────────────────────────────────────────

def log_question_pattern(intent: str, user_input: str, client):
    from config import MODEL_FAST
    import db as _db

    with get_db_conn() as conn:
        row = conn.execute("SELECT question_log, insights FROM patterns WHERE id = 1").fetchone()

    if row:
        log      = json.loads(row["question_log"] or "[]")
        insights = row["insights"] or ""
    else:
        log      = []
        insights = ""

    log.append({"timestamp": datetime.utcnow().isoformat(), "intent": intent, "text": user_input[:200]})
    if len(log) > 100:
        log = log[-100:]

    if len(log) % 10 == 0:
        recent  = log[-20:]
        summary = "\n".join(f"[{e['intent']}] {e['text']}" for e in recent)
        try:
            resp = client.messages.create(
                model=MODEL_FAST,
                max_tokens=150,
                system=(
                    "You are an analyst reviewing recent questions asked to a personal AI. "
                    "Identify 2-3 recurring topics, preferences, or patterns. "
                    "Write one compact paragraph — no bullets, no markdown. "
                    "Focus on what would help the AI serve these users better."
                ),
                messages=[{"role": "user", "content": f"Recent questions:\n{summary}"}],
            )
            _db.track_usage(MODEL_FAST, resp.usage.input_tokens, resp.usage.output_tokens)
            insights = resp.content[0].text.strip()
        except Exception:
            pass

    with _write_lock:
        with get_db_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO patterns (id, question_log, insights) VALUES (1, ?, ?)",
                (json.dumps(log), insights)
            )
            conn.commit()


def save_correction(user_input: str, prior_response: str, client):
    from config import MODEL_FAST
    import db as _db

    try:
        resp = client.messages.create(
            model=MODEL_FAST,
            max_tokens=150,
            system="Extract the correction. Return ONLY valid JSON, no explanation or markdown.",
            messages=[{
                "role": "user",
                "content": (
                    f"The user corrected Fyra.\n"
                    f"User said: {user_input}\n"
                    f"Prior response: {prior_response[:300]}\n\n"
                    'Return JSON: {"topic": "...", "was_wrong": "...", "correct_is": "..."}\n'
                    'If not a clear correction, return: {"topic": null}'
                ),
            }],
        )
        _db.track_usage(MODEL_FAST, resp.usage.input_tokens, resp.usage.output_tokens)
        import re
        raw = resp.content[0].text.strip()
        raw = re.sub(r"```(?:json)?\n?", "", raw).replace("```", "").strip()
        parsed = json.loads(raw)
        if not parsed.get("topic"):
            return
    except Exception:
        return

    topic     = str(parsed.get("topic", "")).strip()
    was_wrong = str(parsed.get("was_wrong", "")).strip()
    correct   = str(parsed.get("correct_is", "")).strip()

    # Validation
    if not (2 <= len(topic) <= 100):
        return
    if not was_wrong or not correct:
        return
    user_words = {w for w in user_input.lower().split() if len(w) > 2}
    haystack   = (topic + " " + was_wrong).lower()
    if not any(w in haystack for w in user_words):
        return

    with _write_lock:
        with get_db_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO corrections (timestamp, topic, was_wrong, correct_is) VALUES (?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), topic, was_wrong, correct)
            )
            # Rolling 50-row cap
            conn.execute("""
                DELETE FROM corrections
                WHERE id NOT IN (
                    SELECT id FROM corrections ORDER BY id DESC LIMIT 50
                )
            """)
            conn.commit()


def get_learning_context() -> str:
    parts = []

    with get_db_conn() as conn:
        pat_row = conn.execute("SELECT insights FROM patterns WHERE id = 1").fetchone()
        cor_rows = conn.execute(
            "SELECT topic, was_wrong, correct_is FROM corrections ORDER BY id DESC LIMIT 5"
        ).fetchall()

    if pat_row:
        insights = (pat_row["insights"] or "").strip()
        if insights:
            parts.append(f"Observed patterns about these users:\n{insights}")

    if cor_rows:
        lines = [
            f"  - On '{r['topic']}': previously said '{r['was_wrong']}' but correct is '{r['correct_is']}'"
            for r in cor_rows
            if r["topic"]
        ]
        if lines:
            parts.append("Known corrections (never repeat these mistakes):\n" + "\n".join(lines))

    return "\n\n".join(parts)


# ── Interaction log ───────────────────────────────────────────

def log_interaction(user_input: str, intent: str, response: str):
    logging.info("INTENT=%s | INPUT=%s | RESPONSE=%s", intent, user_input[:120], response[:200])
