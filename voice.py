import os
import io
import tempfile
import time

import numpy as np
import sounddevice as sd
import msgpack
import requests
import pygame

from config import RECORDING_SECONDS

_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        print("Loading Whisper model (first use)...")
        import whisper
        _whisper_model = whisper.load_model("base")
        print("Whisper ready.")
    return _whisper_model


def record_audio(seconds: int = RECORDING_SECONDS) -> np.ndarray:
    sample_rate = 16000
    print(f"Listening... ({seconds}s)")
    for i in range(seconds, 0, -1):
        print(f"  {i}s", end="\r", flush=True)
        time.sleep(1)
    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    print("Processing...    ")
    return audio.flatten()


def transcribe(audio: np.ndarray) -> str:
    model = _get_whisper_model()
    result = model.transcribe(audio, fp16=False)
    return result["text"].strip()


def speak(text: str):
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not api_key:
        return

    voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "").strip() or None

    payload = {"text": text, "format": "mp3", "latency": "normal"}
    if voice_id:
        payload["reference_id"] = voice_id

    try:
        response = requests.post(
            "https://api.fish.audio/v1/tts",
            data=msgpack.packb(payload, use_bin_type=True),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/msgpack",
            },
            timeout=30,
            stream=True,
        )
        response.raise_for_status()

        audio_bytes = b"".join(response.iter_content(chunk_size=4096))

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        if not pygame.mixer.get_init():
            pygame.mixer.init()

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.music.unload()
        os.unlink(tmp_path)

    except Exception:
        pass
