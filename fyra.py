import os
import sys

from dotenv import load_dotenv

load_dotenv()

_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
if not _ANTHROPIC_KEY:
    print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
    sys.exit(1)

import anthropic
import intent as intent_module
import assistant
import memory

_voice = None


def _get_voice():
    global _voice
    if _voice is None:
        try:
            import voice as v
            _voice = v
        except ImportError as e:
            print(f"[voice unavailable: {e}]")
            _voice = False
    return _voice if _voice else None


def _speak(text: str):
    v = _get_voice()
    if v:
        v.speak(text)


def _voice_input() -> str:
    v = _get_voice()
    if not v:
        print("[voice modules not available — type instead]")
        return ""
    audio = v.record_audio()
    text = v.transcribe(audio)
    if text:
        print(f"You said: {text}")
    return text


def main():
    client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY)

    print("\nFyra is ready. Type your message, 'v' for voice, or 'quit' to exit.\n")

    while True:
        try:
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not raw:
            continue

        if raw.lower() in ("quit", "bye", "exit"):
            farewell = "Take care. I'll be here when you need me."
            print(f"Fyra: {farewell}")
            _speak(farewell)
            break

        if raw.lower() == "v":
            user_input = _voice_input()
            if not user_input:
                continue
        else:
            user_input = raw

        classified_intent = intent_module.classify(user_input, client)
        memory_context = memory.get_relevant_memory(classified_intent, user_input)
        response_text = assistant.respond(user_input, memory_context, client)

        print(f"Fyra: {response_text}\n")
        _speak(response_text)

        if classified_intent in ("store_memory", "check_in"):
            extracted = assistant.extract_memory_update(
                user_input, classified_intent, response_text, client
            )
            memory.apply_memory_update(extracted)

        memory.log_interaction(user_input, classified_intent, response_text)


if __name__ == "__main__":
    main()
