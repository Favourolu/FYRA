import os
import base64
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
if not ANTHROPIC_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

import anthropic
import intent as intent_module
import assistant
import memory as memory_module

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def _tts(text: str):
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests
        import msgpack
        voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "").strip() or None
        payload = {"text": text, "format": "mp3", "latency": "normal"}
        if voice_id:
            payload["reference_id"] = voice_id
        r = requests.post(
            "https://api.fish.audio/v1/tts",
            data=msgpack.packb(payload, use_bin_type=True),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/msgpack",
            },
            timeout=30,
            stream=True,
        )
        r.raise_for_status()
        audio_bytes = b"".join(r.iter_content(chunk_size=4096))
        return base64.b64encode(audio_bytes).decode("utf-8")
    except Exception:
        return None


@app.route("/")
def index():
    return render_template("index.html")


@socketio.on("user_message")
def handle_message(data):
    text = data.get("text", "").strip()
    if not text:
        return

    emit("status", {"state": "processing"})

    classified_intent = intent_module.classify(text, _client)
    ctx = memory_module.get_relevant_memory(classified_intent, text)
    response_text = assistant.respond(text, ctx, _client)

    if classified_intent in ("store_memory", "check_in"):
        extracted = assistant.extract_memory_update(
            text, classified_intent, response_text, _client
        )
        memory_module.apply_memory_update(extracted)

    memory_module.log_interaction(text, classified_intent, response_text)

    audio_b64 = _tts(response_text)

    emit("fyra_response", {
        "text": response_text,
        "audio": audio_b64,
        "intent": classified_intent,
    })


if __name__ == "__main__":
    print("\nFyra UI → http://localhost:5000\n")
    socketio.run(app, debug=False, port=5000, allow_unsafe_werkzeug=True)
