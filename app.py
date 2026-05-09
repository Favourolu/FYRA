import os
import re
import queue
import base64
import threading
import socket as _socket
from flask import Flask, render_template, request
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
from config import MODEL_FAST

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

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


def _strip_md(text: str) -> str:
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)   # bold/italic
    text = re.sub(r'#{1,6}\s+', '', text)                    # headers
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)           # code
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.M)    # bullets
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)    # numbered lists
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)   # links
    text = re.sub(r'\|', ' ', text)                          # table pipes
    text = re.sub(r'[{}\[\]]', '', text)                     # brackets
    text = re.sub(r'\n+', ' ', text).strip()
    return text


def _tts(text: str):
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not api_key:
        print("[TTS] No FISH_AUDIO_API_KEY set — skipping voice")
        return None
    try:
        import requests
        import msgpack
        voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "").strip() or "329ff0b9604444ec982526af54630427"
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


def _generate_greeting(person: str, memory_context: str) -> str:
    from datetime import datetime
    hour = datetime.now().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    name = person.capitalize() if person != "unknown" else "there"
    brief = memory_module.get_startup_brief()
    context = memory_context + (f"\nAlerts: {brief}" if brief else "")
    response = _client.messages.create(
        model=MODEL_FAST,
        max_tokens=80,
        system=(
            "You are Fyra, a personal AI inspired by J.A.R.V.I.S. "
            "Write exactly one short greeting sentence spoken aloud — no markdown, no lists. "
            "Use the person's name. Weave in the time of day naturally. "
            "If context has open tasks or upcoming events, mention one briefly. "
            "Be warm but efficient."
        ),
        messages=[{"role": "user", "content": f"Greet {name}. Time of day: {time_of_day}.\nContext:\n{context}"}],
    )
    return response.content[0].text.strip()


@app.route("/")
def index():
    startup_context = request.args.get("context","").strip()[:2000]
    return render_template("index.html", startup_context=startup_context)


@socketio.on("connect")
def on_connect():
    profile_data = memory_module.get_profile_panel_data()
    emit("profile_update", profile_data)

    history = memory_module.load_conversation_history(limit=20)
    if history:
        emit("conversation_history", {"history": history})

    # Jarvis-style: ask who's there every session
    prompt = "Who am I speaking with?"
    audio = _tts(prompt)
    emit("greeting_prompt", {"text": prompt, "audio": audio})


@socketio.on("greeting_response")
def handle_greeting(data):
    text = data.get("text", "").strip().lower()
    sid = request.sid

    if "favour" in text:
        person = "favour"
    elif "fiyin" in text:
        person = "fiyin"
    else:
        person = "unknown"

    ctx = memory_module.get_relevant_memory("check_in", person)
    greeting = _generate_greeting(person, ctx)

    socketio.emit("stream_start", {}, to=sid)
    socketio.emit("stream_chunk", {"text": greeting}, to=sid)
    socketio.emit("stream_end", {"intent": "greeting"}, to=sid)
    audio = _tts(greeting)
    if audio:
        socketio.emit("audio_chunk", {"audio": audio}, to=sid)


@socketio.on("user_message")
def handle_message(data):
    text = data.get("text", "").strip()
    if not text:
        return

    sid = request.sid
    emit("status", {"state": "processing"})

    classified_intent = intent_module.classify(text, _client)
    ctx = memory_module.get_relevant_memory(classified_intent, text)

    full_response = ""
    sentence_buf = ""
    emit("stream_start", {})

    def _on_tool(name, _inp):
        socketio.emit("tool_use", {"tool": name}, to=sid)

    # Background TTS thread — converts sentences to audio as they stream in,
    # so speech starts while the rest of the text is still appearing.
    tts_q = queue.SimpleQueue()

    def _tts_worker():
        while True:
            item = tts_q.get()
            if item is None:
                break
            audio = _tts(item)
            if audio:
                socketio.emit("audio_chunk", {"audio": audio}, to=sid)

    tts_thread = threading.Thread(target=_tts_worker, daemon=True)
    tts_thread.start()

    for chunk in assistant.respond_stream(text, ctx, _client, on_tool_call=_on_tool):
        full_response += chunk
        sentence_buf += chunk
        socketio.emit("stream_chunk", {"text": chunk}, to=sid)

        stripped = sentence_buf.strip()
        if stripped and stripped[-1] in ".!?:" and len(stripped) >= 12:
            tts_q.put(_strip_md(stripped))
            sentence_buf = ""

    if sentence_buf.strip():
        tts_q.put(_strip_md(sentence_buf.strip()))
    tts_q.put(None)  # signal worker to stop

    socketio.emit("stream_end", {"intent": classified_intent}, to=sid)

    if classified_intent in ("store_memory", "check_in", "task_help"):
        extracted = assistant.extract_memory_update(
            text, classified_intent, full_response, _client
        )
        memory_module.apply_memory_update(extracted)

    memory_module.save_conversation_turn(text, full_response)
    memory_module.log_interaction(text, classified_intent, full_response)

    profile_data = memory_module.get_profile_panel_data()
    socketio.emit("profile_update", profile_data, to=sid)


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
