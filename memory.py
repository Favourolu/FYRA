import re
import json
import uuid
import logging
from datetime import datetime, date
from pathlib import Path

from config import (
    MEMORY_DIR,
    LOGS_DIR,
    MAX_MEMORY_ITEMS,
)

_DEFAULT_PROFILES = {
    "favour": {
        "full_name": "Favour",
        "birthday": None,
        "likes": [],
        "dislikes": [],
        "hobbies": [],
        "facts": [],
    },
    "fiyin": {
        "full_name": "Fiyin",
        "birthday": None,
        "likes": [],
        "dislikes": [],
        "hobbies": [],
        "facts": [],
    },
}

CONVERSATION_FILE = LOGS_DIR / "conversation.json"
PATTERNS_FILE = LOGS_DIR / "patterns.json"
CORRECTIONS_FILE = MEMORY_DIR / "corrections.json"
MAX_CONVERSATION = 200


def _init_files():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    defaults = {
        MEMORY_DIR / "profiles.json": _DEFAULT_PROFILES,
        MEMORY_DIR / "events.json": [],
        MEMORY_DIR / "checkins.json": [],
        MEMORY_DIR / "plans.json": [],
    }
    for path, default in defaults.items():
        if not path.exists():
            path.write_text(json.dumps(default, indent=2))

    if not CONVERSATION_FILE.exists():
        CONVERSATION_FILE.write_text("[]")
    if not PATTERNS_FILE.exists():
        PATTERNS_FILE.write_text(json.dumps({"question_log": [], "insights": ""}, indent=2))
    if not CORRECTIONS_FILE.exists():
        CORRECTIONS_FILE.write_text("[]")

    log_path = LOGS_DIR / "interactions.log"
    if not log_path.exists():
        log_path.touch()


_init_files()

logging.basicConfig(
    filename=str(LOGS_DIR / "interactions.log"),
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


def _read(filename: str):
    path = MEMORY_DIR / filename
    return json.loads(path.read_text())


def _write(filename: str, data):
    path = MEMORY_DIR / filename
    path.write_text(json.dumps(data, indent=2))


def load_all() -> dict:
    return {
        "profiles": _read("profiles.json"),
        "events": _read("events.json"),
        "checkins": _read("checkins.json"),
        "plans": _read("plans.json"),
    }


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
        fiyin_summary = _profile_summary("fiyin", mem["profiles"].get("fiyin", {}))
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

    return "\n\n".join(sections) if sections else "No memory stored yet."


def apply_memory_update(extracted):
    if not extracted or not isinstance(extracted, dict):
        return
    if extracted.get("type") == "none":
        return

    kind = extracted.get("type")

    if kind == "profile":
        profiles = _read("profiles.json")
        person = extracted.get("person", "").lower()
        key = extracted.get("key")
        value = extracted.get("value")

        targets = ["favour", "fiyin"] if person == "both" else [person]
        for t in targets:
            if t not in profiles:
                continue
            if key in ("likes", "dislikes", "hobbies", "facts"):
                existing = profiles[t].get(key, [])
                new_items = value if isinstance(value, list) else [value]
                for item in new_items:
                    if item not in existing:
                        existing.append(item)
                profiles[t][key] = existing
            else:
                profiles[t][key] = value
        _write("profiles.json", profiles)

    elif kind == "event":
        events = _read("events.json")
        events.append({
            "id": str(uuid.uuid4()),
            "type": extracted.get("event_type", "moment"),
            "date": extracted.get("date"),
            "title": extracted.get("title", ""),
            "description": extracted.get("description", ""),
            "tags": extracted.get("tags", []),
        })
        _write("events.json", events)

    elif kind == "checkin":
        checkins = _read("checkins.json")
        checkins.append({
            "timestamp": datetime.utcnow().isoformat(),
            "person": extracted.get("person", "both"),
            "mood": extracted.get("mood", ""),
            "note": extracted.get("note", ""),
        })
        _write("checkins.json", checkins)

    elif kind == "plan":
        plans = _read("plans.json")
        plans.append({
            "id": str(uuid.uuid4()),
            "type": extracted.get("plan_type", "todo"),
            "title": extracted.get("title", ""),
            "description": extracted.get("description", ""),
            "status": extracted.get("status", "idea"),
            "created_at": datetime.utcnow().isoformat(),
        })
        _write("plans.json", plans)


# ── Conversation history ──────────────────────────────────────

def load_conversation_history(limit: int = 30) -> list:
    try:
        data = json.loads(CONVERSATION_FILE.read_text())
        return data[-limit:] if isinstance(data, list) else []
    except Exception:
        return []


def save_conversation_turn(user_text: str, fyra_text: str):
    history = load_conversation_history(MAX_CONVERSATION)
    history.append({
        "timestamp": datetime.utcnow().isoformat(),
        "user": user_text,
        "fyra": fyra_text,
    })
    CONVERSATION_FILE.write_text(json.dumps(history[-MAX_CONVERSATION:], indent=2))


def get_history_for_assistant(limit: int = 5) -> list:
    """Return last N turns as Claude messages format for context injection."""
    history = load_conversation_history(limit)
    messages = []
    for turn in history:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["fyra"]})
    return messages


# ── Live profile data for UI ──────────────────────────────────

def get_profile_panel_data() -> dict:
    profiles = _read("profiles.json")
    favour = profiles.get("favour", {})
    fiyin = profiles.get("fiyin", {})
    plans = _read("plans.json")
    open_tasks = [p for p in plans if p.get("status") != "done"]

    return {
        "favour": {
            "name": favour.get("full_name", "Favour"),
            "birthday": favour.get("birthday", "—"),
            "likes": favour.get("likes", [])[:3],
            "facts": favour.get("facts", [])[:2],
        },
        "fiyin": {
            "name": fiyin.get("full_name", "Fiyin"),
            "birthday": fiyin.get("birthday", "—"),
            "likes": fiyin.get("likes", [])[:3],
            "facts": fiyin.get("facts", [])[:2],
        },
        "open_tasks": len(open_tasks),
    }


# ── Startup reminders ─────────────────────────────────────────

def get_startup_brief() -> str:
    """Return a brief for Fyra to deliver on startup. Empty string = nothing to say."""
    mem = load_all()
    today = date.today()
    alerts = []

    for event in mem["events"]:
        event_date_str = event.get("date")
        if not event_date_str:
            continue
        try:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            # Check anniversary this year
            this_year = event_date.replace(year=today.year)
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


def log_question_pattern(intent: str, user_input: str, client):
    """Append question to rolling log; every 10 entries generate fresh insights via haiku."""
    from config import MODEL_FAST
    try:
        data = json.loads(PATTERNS_FILE.read_text())
    except Exception:
        data = {"question_log": [], "insights": ""}

    log = data.get("question_log", [])
    log.append({"timestamp": datetime.utcnow().isoformat(), "intent": intent, "text": user_input[:200]})
    if len(log) > 100:
        log = log[-100:]
    data["question_log"] = log

    if len(log) % 10 == 0:
        recent = log[-20:]
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
            data["insights"] = resp.content[0].text.strip()
        except Exception:
            pass

    PATTERNS_FILE.write_text(json.dumps(data, indent=2))


def save_correction(user_input: str, prior_response: str, client):
    """Extract what was wrong and what the correct answer is, then persist it."""
    from config import MODEL_FAST
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
        raw = resp.content[0].text.strip()
        raw = re.sub(r"```(?:json)?\n?", "", raw).replace("```", "").strip()
        parsed = json.loads(raw)
        if not parsed.get("topic"):
            return
    except Exception:
        return

    try:
        corrections = json.loads(CORRECTIONS_FILE.read_text())
    except Exception:
        corrections = []

    corrections.append({
        "timestamp": datetime.utcnow().isoformat(),
        "topic": parsed.get("topic", ""),
        "was_wrong": parsed.get("was_wrong", ""),
        "correct_is": parsed.get("correct_is", ""),
    })
    CORRECTIONS_FILE.write_text(json.dumps(corrections[-50:], indent=2))


def get_learning_context() -> str:
    """Return insights and recent corrections to inject into the conversation context."""
    parts = []
    try:
        data = json.loads(PATTERNS_FILE.read_text())
        insights = data.get("insights", "").strip()
        if insights:
            parts.append(f"Observed patterns about these users:\n{insights}")
    except Exception:
        pass

    try:
        corrections = json.loads(CORRECTIONS_FILE.read_text())
        recent = [c for c in corrections[-5:] if c.get("topic")]
        if recent:
            lines = [
                f"  - On '{c['topic']}': previously said '{c['was_wrong']}' but correct is '{c['correct_is']}'"
                for c in recent
            ]
            parts.append("Known corrections (never repeat these mistakes):\n" + "\n".join(lines))
    except Exception:
        pass

    return "\n\n".join(parts)


def log_interaction(user_input: str, intent: str, response: str):
    logging.info("INTENT=%s | INPUT=%s | RESPONSE=%s", intent, user_input[:120], response[:200])
