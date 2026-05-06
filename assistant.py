import re
import json
from datetime import date

from config import (
    MODEL,
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT_TEMPLATE,
    EXTRACT_SYSTEM,
    EXTRACT_USER_TEMPLATE,
)

_history: list[dict] = []
_history_loaded = False


def load_history_from_disk():
    """Seed in-memory history from saved conversation on first use."""
    global _history, _history_loaded
    if _history_loaded:
        return
    _history_loaded = True
    try:
        from memory import get_history_for_assistant
        prior = get_history_for_assistant(limit=6)
        if prior:
            _history = prior
    except Exception:
        pass


def build_system_prompt(memory_context: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        date=date.today().isoformat(),
        memory_context=memory_context,
    )


def respond(user_input: str, memory_context: str, client) -> str:
    global _history
    load_history_from_disk()

    _history.append({"role": "user", "content": user_input})

    if len(_history) > MAX_HISTORY_TURNS * 2:
        _history = _history[-(MAX_HISTORY_TURNS * 2):]

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=build_system_prompt(memory_context),
        messages=_history,
    )

    reply = response.content[0].text.strip()
    _history.append({"role": "assistant", "content": reply})
    return reply


def respond_stream(user_input: str, memory_context: str, client, on_tool_call=None):
    """Yield text chunks, executing web tools when Claude requests them."""
    from tools import TOOLS, execute_tool

    global _history
    load_history_from_disk()

    _history.append({"role": "user", "content": user_input})
    if len(_history) > MAX_HISTORY_TURNS * 2:
        _history = _history[-(MAX_HISTORY_TURNS * 2):]

    messages = list(_history)
    full_response = ""

    while True:
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=build_system_prompt(memory_context),
            messages=messages,
            tools=TOOLS,
        ) as stream:
            for event in stream:
                if (event.type == "content_block_delta"
                        and event.delta.type == "text_delta"):
                    chunk = event.delta.text
                    full_response += chunk
                    yield chunk
            final = stream.get_final_message()

        if final.stop_reason != "tool_use":
            break

        # Serialize content blocks to plain dicts for the API
        assistant_content = []
        tool_results = []
        for block in final.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                if on_tool_call:
                    on_tool_call(block.name, block.input)
                result = execute_tool(block.name, block.input)
                print(f"[Tool] {block.name}({block.input}) → {len(result)} chars")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

    _history.append({"role": "assistant", "content": full_response})


def extract_memory_update(user_input: str, intent: str, response_text: str, client) -> dict:
    try:
        prompt = EXTRACT_USER_TEMPLATE.format(
            intent=intent,
            user_input=user_input,
            response=response_text,
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?\n?", "", raw).replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"type": "none"}
