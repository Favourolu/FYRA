import eventlet
eventlet.monkey_patch()

import os
import base64
import socket as _socket
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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


def _local_ip() -> str:
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _tts(text: str):
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not api_key:
        print("[TTS] No FISH_AUDIO_API_KEY set — skipping voice")
        return None
    try:
        import requests
        import msgpack
        voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "").strip() or "933563129e564b19a115bedd57b7406a"
        payload = {"text": text, "format": "mp3", "latency": "normal", "reference_id": voice_id}
        print(f"[TTS] Requesting voice | id={voice_id or '(default)'} | len={len(text)}")
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
        if not r.ok:
            print(f"[TTS] Error {r.status_code}: {r.text[:200]}")
            return None
        audio_bytes = b"".join(r.iter_content(chunk_size=4096))
        print(f"[TTS] OK — {len(audio_bytes)} bytes")
        return base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as e:
        print(f"[TTS] Exception: {e}")
        return None


@app.route("/")
def index():
    return render_template("index.html")


@socketio.on("connect")
def on_connect():
    # Send live profile data to update the UI panel
    profile_data = memory_module.get_profile_panel_data()
    emit("profile_update", profile_data)

    # Send conversation history so UI can restore it
    history = memory_module.load_conversation_history(limit=20)
    if history:
        emit("conversation_history", {"history": history})

    # Send startup brief if there's something to surface
    brief = memory_module.get_startup_brief()
    if brief:
        audio = _tts(brief)
        emit("startup_brief", {"text": brief, "audio": audio})


@socketio.on("user_message")
def handle_message(data):
    text = data.get("text", "").strip()
    if not text:
        return

    emit("status", {"state": "processing"})

    classified_intent = intent_module.classify(text, _client)
    ctx = memory_module.get_relevant_memory(classified_intent, text)

    # Stream response — emit text chunks immediately, TTS each sentence
    full_response = ""
    sentence_buf = ""
    emit("stream_start", {})

    for chunk in assistant.respond_stream(text, ctx, _client):
        full_response += chunk
        sentence_buf += chunk
        emit("stream_chunk", {"text": chunk})

        # TTS when we hit a natural sentence boundary
        stripped = sentence_buf.strip()
        if stripped and stripped[-1] in ".!?:" and len(stripped) >= 12:
            audio = _tts(stripped)
            sentence_buf = ""
            emit("audio_chunk", {"audio": audio})

    # Flush any remaining text
    if sentence_buf.strip():
        audio = _tts(sentence_buf.strip())
        emit("audio_chunk", {"audio": audio})

    emit("stream_end", {"intent": classified_intent})

    if classified_intent in ("store_memory", "check_in", "task_help"):
        extracted = assistant.extract_memory_update(
            text, classified_intent, full_response, _client
        )
        memory_module.apply_memory_update(extracted)

    memory_module.save_conversation_turn(text, full_response)
    memory_module.log_interaction(text, classified_intent, full_response)

    profile_data = memory_module.get_profile_panel_data()
    emit("profile_update", profile_data)


@socketio.on("set_voice")
def handle_set_voice(data):
    """Allow setting voice ID from the UI at runtime."""
    voice_id = data.get("voice_id", "").strip()
    os.environ["FISH_AUDIO_VOICE_ID"] = voice_id
    emit("voice_set", {"voice_id": voice_id})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    ip = _local_ip()
    print(f"\nFyra UI → http://localhost:{port}")
    print(f"Mobile  → http://{ip}:{port}\n")
    socketio.run(app, host="0.0.0.0", debug=False, port=port, allow_unsafe_werkzeug=True)
