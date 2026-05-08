from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).parent
MEMORY_DIR = BASE_DIR / "memory"
LOGS_DIR = BASE_DIR / "logs"

MODEL = "claude-sonnet-4-6"
MODEL_FAST = "claude-haiku-4-5-20251001"
MAX_HISTORY_TURNS = 10
MAX_MEMORY_ITEMS = 10
RECORDING_SECONDS = 7

VALID_INTENTS = [
    "store_memory",
    "retrieve_memory",
    "suggest_action",
    "check_in",
    "task_help",
    "market_query",
    "general_chat",
]

SYSTEM_PROMPT_TEMPLATE = """\
You are Fyra — an intelligent personal AI assistant for Favour and Fiyin, inspired by J.A.R.V.I.S. from Iron Man.
You are calm, sharp, direct, and highly capable. You assist with anything they need: tasks, research, planning, \
reminders, creative work, personal matters, general questions, or anything else life throws at them.
You know them personally — their preferences, habits, goals, and relationship — and bring that context into \
every interaction naturally without being asked.
You never fabricate facts. You are concise and direct, never verbose. You speak like a trusted intelligent \
companion, not a chatbot. You have access to web search — use it proactively whenever you need current \
information, news, weather, facts, or anything you are unsure about. Never say you cannot browse the internet.
Today's date is {date}.

You are also the intelligence layer for AfriTerminal — Africa's financial data terminal built by Favour. You have real-time access to AfriTerminal's live market data via the fetch_afriterminal_data tool, covering NGX stocks, corporate filings, FX rates, African sovereign bonds, CBN macro data, and global markets. When answering any question about African capital markets, always fetch the relevant dataset first — never invent or estimate market figures. Do not give buy or sell recommendations.

What you know about Favour and Fiyin:
{memory_context}
"""

INTENT_SYSTEM = (
    "You are an intent classifier. Reply with ONLY the intent label, nothing else. "
    "Valid labels: store_memory, retrieve_memory, suggest_action, check_in, task_help, market_query, general_chat"
)

INTENT_USER_TEMPLATE = """\
Classify this message into exactly one intent:
- store_memory: user wants to save a fact, event, preference, or memory
- retrieve_memory: user is asking what Fyra knows or remembers about them
- suggest_action: user wants ideas, recommendations, or suggestions
- check_in: user is sharing their mood, feelings, or current state
- task_help: user needs help with a task, to-do, schedule, reminder, or plan
- market_query: question about African markets, NGX stocks, FX rates, bonds, filings, CBN, or AfriTerminal data
- general_chat: questions, research, general assistance, conversation, or anything else

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

For store_memory — plan or task:
{{"type": "plan", "plan_type": "date_idea|goal|todo|task", "title": "...", "description": "...", "status": "idea"}}

For check_in:
{{"type": "checkin", "person": "favour|fiyin|both", "mood": "...", "note": "..."}}

If nothing meaningful to save, return: {{"type": "none"}}
"""
