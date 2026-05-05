from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).parent
MEMORY_DIR = BASE_DIR / "memory"
LOGS_DIR = BASE_DIR / "logs"

MODEL = "claude-haiku-4-5-20251001"
MAX_HISTORY_TURNS = 10
MAX_MEMORY_ITEMS = 10
RECORDING_SECONDS = 7

VALID_INTENTS = [
    "store_memory",
    "retrieve_memory",
    "suggest_action",
    "check_in",
    "general_chat",
]

SYSTEM_PROMPT_TEMPLATE = """\
You are Fyra, a personal AI assistant for Favour and Fiyin — two people in a close relationship.
You are calm, warm, concise, and emotionally aware. You speak naturally and personally.
You remember things that matter to them: preferences, events, moods, plans.
You never fabricate facts you haven't been told. You don't overstep emotionally.
Today's date is {date}.

Here is what you know about them:
{memory_context}
"""

INTENT_SYSTEM = (
    "You are an intent classifier. Reply with ONLY the intent label, nothing else. "
    "Valid labels: store_memory, retrieve_memory, suggest_action, check_in, general_chat"
)

INTENT_USER_TEMPLATE = """\
Classify this message into exactly one intent:
- store_memory: user wants to save a fact, event, or memory
- retrieve_memory: user is asking what you know or remember
- suggest_action: user wants ideas, suggestions, or plans
- check_in: user is sharing their mood, feelings, or current state
- general_chat: anything else

Message: {user_input}
"""

EXTRACT_SYSTEM = (
    "You are a data extractor. Return ONLY valid JSON, no explanation or markdown code fences."
)

EXTRACT_USER_TEMPLATE = """\
Extract what should be saved from this conversation.

Intent: {intent}
User said: {user_input}
Assistant responded: {response}

Return JSON in one of these formats:

For store_memory — profile update:
{{"type": "profile", "person": "favour|fiyin|both", "key": "likes|dislikes|hobbies|facts|birthday|full_name", "value": <string or list>}}

For store_memory — event:
{{"type": "event", "event_type": "anniversary|trip|moment|milestone", "date": "YYYY-MM-DD or null", "title": "...", "description": "...", "tags": []}}

For store_memory — plan:
{{"type": "plan", "plan_type": "date_idea|goal|todo", "title": "...", "description": "...", "status": "idea"}}

For check_in:
{{"type": "checkin", "person": "favour|fiyin|both", "mood": "...", "note": "..."}}

If nothing meaningful to save, return: {{"type": "none"}}
"""
