import json
import uuid
import logging
from datetime import datetime
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

    if intent in ("retrieve_memory", "store_memory", "general_chat"):
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

    if intent in ("suggest_action", "retrieve_memory"):
        open_plans = [p for p in mem["plans"] if p.get("status") != "done"][-MAX_MEMORY_ITEMS:]
        if open_plans:
            plan_lines = [
                f"  [{p.get('type', '?')}] {p.get('title', '')} — {p.get('description', '')}"
                for p in open_plans
            ]
            sections.append("Plans & ideas:\n" + "\n".join(plan_lines))

    return "\n\n".join(sections) if sections else "No memory stored yet."


def apply_memory_update(extracted: dict):
    if not extracted or extracted.get("type") == "none":
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


def log_interaction(user_input: str, intent: str, response: str):
    logging.info("INTENT=%s | INPUT=%s | RESPONSE=%s", intent, user_input[:120], response[:200])
