import re
import json
from datetime import date

import db as _db
from config import (
    MODEL,
    MODEL_FAST,
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT_TEMPLATE,
    EXTRACT_SYSTEM,
    EXTRACT_USER_TEMPLATE,
)

# Per-session conversation history keyed by socket ID.
# Each connection gets its own isolated history so simultaneous users
# never see each other's messages or context.
_histories: dict[str, list[dict]] = {}


def _get_history(sid: str) -> list[dict]:
    if sid not in _histories:
        try:
            from memory import get_history_for_assistant
            prior = get_history_for_assistant(limit=6)
            _histories[sid] = prior if prior else []
        except Exception:
            _histories[sid] = []
    return _histories[sid]


def clear_session(sid: str):
    _histories.pop(sid, None)


def build_system_prompt(memory_context: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        date=date.today().isoformat(),
        memory_context=memory_context,
    )


def respond(user_input: str, memory_context: str, client, sid: str = "cli") -> str:
    history = _get_history(sid)
    history.append({"role": "user", "content": user_input})

    if len(history) > MAX_HISTORY_TURNS * 2:
        _histories[sid] = history[-(MAX_HISTORY_TURNS * 2):]
        history = _histories[sid]

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=build_system_prompt(memory_context),
        messages=history,
    )
    _db.track_usage(MODEL, response.usage.input_tokens, response.usage.output_tokens)

    reply = response.content[0].text.strip()
    history.append({"role": "assistant", "content": reply})
    return reply


def respond_stream(user_input: str, memory_context: str, client, sid: str, on_tool_call=None):
    """Yield text chunks for one session, isolated from all other sessions."""
    from tools import TOOLS, execute_tool

    history = _get_history(sid)
    history.append({"role": "user", "content": user_input})

    if len(history) > MAX_HISTORY_TURNS * 2:
        _histories[sid] = history[-(MAX_HISTORY_TURNS * 2):]
        history = _histories[sid]

    messages = list(history)
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
        _db.track_usage(MODEL, final.usage.input_tokens, final.usage.output_tokens)

        if final.stop_reason != "tool_use":
            break

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

    history.append({"role": "assistant", "content": full_response})


def extract_memory_update(user_input: str, intent: str, response_text: str, client) -> dict:
    try:
        prompt = EXTRACT_USER_TEMPLATE.format(
            intent=intent,
            user_input=user_input,
            response=response_text,
        )
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=512,
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        _db.track_usage(MODEL_FAST, response.usage.input_tokens, response.usage.output_tokens)
        raw = response.content[0].text.strip()
        raw = re.sub(r"```(?:json)?\n?", "", raw).replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"type": "none"}
