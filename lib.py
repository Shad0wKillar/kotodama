import array
import os
import signal
import subprocess
import time
import wave
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = PROJECT_DIR / ".state"

load_dotenv(PROJECT_DIR / ".env")

STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
CLEANUP_MODEL = os.environ.get("GROQ_CLEANUP_MODEL", "openai/gpt-oss-120b")

CLEANUP_PROMPT = (
    "You are a dictation cleanup tool. You will be given a raw speech-to-text "
    "transcript. Rewrite it clean: remove filler words (um, uh, like, you know), "
    "fix grammar and punctuation, keep the speaker's meaning, wording, and tone "
    "intact. Do not add content that wasn't said, do not answer questions in the "
    "text, do not add commentary. Output only the cleaned transcript, nothing else."
)


def notify(title, body=""):
    try:
        subprocess.run(["notify-send", title, body], check=False)
    except FileNotFoundError:
        pass


def copy_to_clipboard(text):
    subprocess.run(["wl-copy"], input=text.encode(), check=True)


def is_silent(wav_path, threshold=400):
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    samples = array.array("h", frames)
    if not samples:
        return True
    peak = max(max(samples), -min(samples))
    return peak < threshold


def start_pw_record(wav_path):
    wav_path = Path(wav_path)
    wav_path.unlink(missing_ok=True)
    proc = subprocess.Popen(
        ["pw-record", "--channels=1", "--rate=16000", str(wav_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def stop_pw_record(pid, timeout=5.0):
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    waited = 0.0
    while waited < timeout:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
        waited += 0.1


def transcribe_and_clean(wav_path):
    """Returns cleaned transcript text, or None if silent/empty.
    Raises on network failure (APITimeoutError, APIConnectionError)."""
    if is_silent(wav_path):
        return None

    from groq import Groq

    client = Groq(timeout=25.0, max_retries=1)
    with open(wav_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f,
            model=STT_MODEL,
        ).text

    transcript = transcript.strip()
    if not transcript:
        return None

    cleaned = (
        client.chat.completions.create(
            model=CLEANUP_MODEL,
            messages=[
                {"role": "system", "content": CLEANUP_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.2,
        )
        .choices[0]
        .message.content.strip()
    )
    return cleaned
