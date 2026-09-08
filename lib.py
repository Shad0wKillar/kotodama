import array
import json
import os
import re
import signal
import subprocess
import time
import traceback
import wave
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = PROJECT_DIR / ".state"
LOG_FILE = STATE_DIR / "kotodama.log"
FAILURE_LOG = STATE_DIR / "failures.jsonl"
RATE_STATE_FILE = STATE_DIR / "ratelimit.json"
COOLDOWN_FILE = STATE_DIR / "cooldown_until"

load_dotenv(PROJECT_DIR / ".env")

STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
CLEANUP_MODEL = os.environ.get("GROQ_CLEANUP_MODEL", "openai/gpt-oss-120b")

# Keep the source audio after a successful transcript, so a bad cleanup or a
# transcript you disagree with can always be re-run. ~2 MB per minute.
KEEP_AUDIO = os.environ.get("KOTODAMA_KEEP_AUDIO", "1").lower() not in ("0", "false", "no")
MAX_ATTEMPTS = int(os.environ.get("KOTODAMA_MAX_ATTEMPTS", "3"))
API_TIMEOUT = float(os.environ.get("KOTODAMA_TIMEOUT", "25"))
SILENCE_THRESHOLD = int(os.environ.get("KOTODAMA_SILENCE_THRESHOLD", "400"))
# Stop and wait for the window to roll over once Groq says we're this close to
# the per-minute token ceiling.
TOKEN_RESERVE = int(os.environ.get("KOTODAMA_TOKEN_RESERVE", "1500"))
# A 429 means the per-minute window is spent. There is nothing to do but let it
# roll over, so wait out a full window before trying again — and hold the whole
# queue, not just the one call, since every job draws on the same budget.
RATE_LIMIT_WAIT = float(os.environ.get("KOTODAMA_RATE_LIMIT_WAIT", "60"))
RATE_LIMIT_ATTEMPTS = int(os.environ.get("KOTODAMA_RATE_LIMIT_ATTEMPTS", "5"))

CLEANUP_PROMPT = (
    "You are a dictation cleanup tool. You will be given a raw speech-to-text "
    "transcript. Rewrite it clean: remove filler words (um, uh, like, you know), "
    "fix grammar and punctuation, keep the speaker's meaning, wording, and tone "
    "intact. Do not add content that wasn't said, do not answer questions in the "
    "text, do not add commentary. Output only the cleaned transcript, nothing else."
)


def log(message, exc=None):
    """Append a timestamped line (plus traceback) to .state/kotodama.log.

    Deliberately never raises: logging must not be able to break a capture.
    """
    try:
        STATE_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{stamp}] {message}\n")
            if exc is not None:
                for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
                    for sub in line.rstrip("\n").split("\n"):
                        f.write(f"    {sub}\n")
    except Exception:
        pass


def notify(title, body=""):
    try:
        subprocess.run(["notify-send", title, body], check=False)
    except FileNotFoundError:
        pass


def copy_to_clipboard(text):
    subprocess.run(["wl-copy"], input=text.encode(), check=True)


def parse_duration(text):
    """Groq sends waits as '43.2s', '2m52.8s', '577ms', or bare seconds."""
    text = str(text).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    units = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    total, matched = 0.0, False
    for value, unit in re.findall(r"([\d.]+)\s*(ms|s|m|h)", text):
        matched = True
        total += float(value) * units[unit]
    return total if matched else None


def retry_after_seconds(exc):
    """How long Groq asked us to wait, if it said so."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        wait = parse_duration(headers.get(key) or "")
        if wait:
            return wait
    return None


def describe_error(exc):
    """(title, body, retryable) — an honest label instead of 'network error'."""
    name = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)

    if name == "RateLimitError" or status == 429:
        wait = max(RATE_LIMIT_WAIT, retry_after_seconds(exc) or 0.0)
        return (
            "Rate limited",
            f"Per-minute token budget spent. Waiting {wait:.0f}s, then retrying.",
            True,
        )
    if name == "AuthenticationError" or status == 401:
        return ("Bad API key", "Groq rejected GROQ_API_KEY — check .env.", False)
    if name == "PermissionDeniedError" or status == 403:
        return ("Access denied", "Your key cannot use this model.", False)
    if name == "NotFoundError" or status == 404:
        return ("Model not found", "Check GROQ_STT_MODEL / GROQ_CLEANUP_MODEL.", False)
    if name == "BadRequestError" or status == 400:
        return ("Rejected by Groq", f"{str(exc)[:100]}", False)
    if name in ("APITimeoutError", "APIConnectionError"):
        return ("Network error", "Groq unreachable or timed out.", True)
    if status is not None and 500 <= status < 600:
        return ("Groq server error", f"HTTP {status} — transient.", True)
    return (f"Failed: {name}", str(exc)[:100] or "Unknown error.", True)


def groq_message(exc):
    """The error string Groq itself returned, dug out of the response body."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("message") or error.get("code")
        if isinstance(error, str):
            return error
    return None


def record_failure(phase, exc, attempt=None, **context):
    """Append one machine-readable record per failure to .state/failures.jsonl.

    This is the file to read when something went wrong: every attempt of every
    failed call lands here with the phase, the HTTP status, Groq's own message,
    which models were in play, and the size/peak of the audio involved.
    """
    try:
        title, detail, retryable = describe_error(exc)
        response = getattr(exc, "response", None)
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "phase": phase,
            "attempt": attempt,
            "title": title,
            "detail": detail,
            "retryable": retryable,
            "exception": type(exc).__name__,
            "http_status": getattr(response, "status_code", None),
            "groq_message": groq_message(exc),
            "message": str(exc)[:500],
            "stt_model": STT_MODEL,
            "cleanup_model": CLEANUP_MODEL,
            "retry_after": retry_after_seconds(exc),
        }
        for key, value in context.items():
            if value is not None:
                record[key] = value

        wav = context.get("wav_path")
        if wav and Path(wav).exists():
            record["wav_bytes"] = Path(wav).stat().st_size
            record["wav_peak"] = peak_amplitude(wav)

        try:
            record["rate_state"] = json.loads(RATE_STATE_FILE.read_text())
        except Exception:
            pass

        STATE_DIR.mkdir(exist_ok=True)
        with open(FAILURE_LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def normalize_index(value):
    """Segment indexes travel as '4', 4 and '004' — compare them as one thing."""
    try:
        return f"{int(str(value).strip()):03d}"
    except (TypeError, ValueError):
        return None


def read_failures(session_id=None, index=None):
    """Every recorded failure, oldest first, optionally filtered."""
    if not FAILURE_LOG.exists():
        return []
    wanted = normalize_index(index) if index is not None else None
    out = []
    for line in FAILURE_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        if session_id and record.get("session_id") != session_id:
            continue
        if wanted is not None and normalize_index(record.get("index")) != wanted:
            continue
        out.append(record)
    return out


def is_rate_limit(exc):
    return (
        type(exc).__name__ == "RateLimitError"
        or getattr(getattr(exc, "response", None), "status_code", None) == 429
    )


def set_cooldown(seconds, reason=""):
    """Record a hard stop on all Groq traffic until `seconds` from now.

    Written to disk on purpose: the pause has to outlive the process that hit
    the limit, or the next job would start up and immediately 429 again.
    """
    until = time.time() + seconds
    try:
        STATE_DIR.mkdir(exist_ok=True)
        COOLDOWN_FILE.write_text(
            json.dumps(
                {
                    "until": until,
                    "seconds": seconds,
                    "reason": reason,
                    "set_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
        )
    except Exception as exc:
        log("cooldown: could not persist the hold", exc)
    log(f"cooldown: holding every Groq call for {seconds:.0f}s — {reason}")
    return until


def cooldown_remaining():
    """Seconds left on the hold, 0.0 if there isn't one."""
    try:
        data = json.loads(COOLDOWN_FILE.read_text())
    except Exception:
        return 0.0
    return max(0.0, float(data.get("until") or 0) - time.time())


def clear_cooldown():
    COOLDOWN_FILE.unlink(missing_ok=True)


def wait_out_cooldown():
    """Block until any active rate-limit hold expires."""
    remaining = cooldown_remaining()
    if remaining <= 0:
        clear_cooldown()
        return 0.0
    log(f"cooldown: {remaining:.0f}s left before the next Groq call is allowed")
    notify("Rate limit — waiting", f"Paused {remaining:.0f}s, then retrying automatically.")
    time.sleep(remaining)
    clear_cooldown()
    return remaining


def note_rate_limit(headers, endpoint):
    """Remember what Groq just told us about our remaining budget."""
    try:
        if not headers:
            return
        remaining = headers.get("x-ratelimit-remaining-tokens")
        if remaining is None:
            return
        limit = headers.get("x-ratelimit-limit-tokens")
        reset = parse_duration(headers.get("x-ratelimit-reset-tokens") or "") or 0.0
        data = {
            "endpoint": endpoint,
            "remaining_tokens": int(float(remaining)),
            "limit_tokens": int(float(limit)) if limit else None,
            "reset_seconds": reset,
            "at": time.time(),
        }
        STATE_DIR.mkdir(exist_ok=True)
        RATE_STATE_FILE.write_text(json.dumps(data))
        log(
            f"rate: {data['remaining_tokens']}/{data['limit_tokens']} tokens left "
            f"on {endpoint}, window resets in {reset:.1f}s"
        )
    except Exception as exc:
        log("rate: could not read rate-limit headers", exc)


def pace_for_rate_limit():
    """Block until the token window rolls over, if the last call left us short.

    Called by the queue worker between jobs, which is why a burst of segments
    can no longer stampede the per-minute limit.
    """
    wait_out_cooldown()
    try:
        data = json.loads(RATE_STATE_FILE.read_text())
    except Exception:
        return
    remaining = data.get("remaining_tokens")
    if remaining is None or remaining > TOKEN_RESERVE:
        return
    elapsed = time.time() - float(data.get("at") or 0)
    wait = (data.get("reset_seconds") or 0.0) - elapsed
    if wait <= 0:
        return
    wait = min(wait, 65.0)
    log(f"rate: {remaining} tokens left (reserve {TOKEN_RESERVE}) — pausing {wait:.1f}s")
    notify("Waiting on rate limit", f"{remaining} tokens left; pausing {wait:.0f}s.")
    time.sleep(wait)


def with_retries(fn, what, phase="api", context=None):
    """Run fn(), retrying transient failures. Every failed attempt is recorded.

    Rate limits are handled separately from everything else. A 429 is not a
    flaky call to back off from a little — it means this minute's token budget
    is gone, so the only fix is to wait out the window. Those waits get their
    own allowance (RATE_LIMIT_ATTEMPTS) and do not consume the ordinary retry
    budget, which is reserved for timeouts and 5xx.
    """
    context = context or {}
    attempt = 0
    rate_waits = 0
    while True:
        attempt += 1
        wait_out_cooldown()
        try:
            return fn()
        except Exception as exc:
            title, detail, retryable = describe_error(exc)
            record_failure(phase, exc, attempt=attempt, **context)

            if is_rate_limit(exc):
                rate_waits += 1
                if rate_waits > RATE_LIMIT_ATTEMPTS:
                    log(
                        f"{what}: still rate limited after {RATE_LIMIT_ATTEMPTS} "
                        f"full-window waits — giving up, audio is kept",
                        exc,
                    )
                    raise
                # Honour Groq's own retry-after if it wants longer than a window.
                wait = max(RATE_LIMIT_WAIT, retry_after_seconds(exc) or 0.0)
                log(
                    f"{what}: rate limited (hold {rate_waits}/{RATE_LIMIT_ATTEMPTS}) "
                    f"— stopping the queue for {wait:.0f}s, then retrying"
                )
                set_cooldown(wait, f"429 on {what}")
                notify("Rate limited", f"Waiting {wait:.0f}s, then retrying automatically.")
                time.sleep(wait)
                clear_cooldown()
                attempt -= 1  # a rate-limit hold is not a failed attempt
                continue

            log(f"{what}: attempt {attempt}/{MAX_ATTEMPTS} failed — {title}: {detail}", exc)
            if not retryable or attempt >= MAX_ATTEMPTS:
                raise
            wait = min(max(retry_after_seconds(exc) or min(2 ** attempt, 30), 1.0), 60.0)
            log(f"{what}: waiting {wait:.1f}s before retry")
            time.sleep(wait)


def peak_amplitude(wav_path):
    """Loudest sample in the file, or None if the WAV can't be parsed."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
    except Exception as exc:
        log(f"{Path(wav_path).name}: unreadable WAV header", exc)
        return None
    samples = array.array("h", frames[: len(frames) // 2 * 2])
    if not samples:
        return 0
    return max(max(samples), -min(samples))


def is_silent(wav_path, threshold=None):
    threshold = SILENCE_THRESHOLD if threshold is None else threshold
    peak = peak_amplitude(wav_path)
    if peak is None:
        # Unparseable: let Groq decide rather than silently dropping audio.
        return False
    if peak < threshold:
        log(f"{Path(wav_path).name}: peak {peak} < threshold {threshold} — treated as silence")
        return True
    return False


def start_pw_record(wav_path):
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
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


def _client():
    from groq import Groq

    return Groq(timeout=API_TIMEOUT, max_retries=1)


def transcribe(wav_path):
    """Raw speech-to-text. Raises on API failure."""
    with open(wav_path, "rb") as f:
        response = _client().audio.transcriptions.with_raw_response.create(
            file=f, model=STT_MODEL
        )
    note_rate_limit(response.headers, "transcriptions")
    return response.parse().text.strip()


def clean(transcript):
    """LLM tidy-up of a raw transcript. Raises on API failure."""
    response = _client().chat.completions.with_raw_response.create(
        model=CLEANUP_MODEL,
        messages=[
            {"role": "system", "content": CLEANUP_PROMPT},
            {"role": "user", "content": transcript},
        ],
        temperature=0.2,
    )
    note_rate_limit(response.headers, "chat.completions")
    return response.parse().choices[0].message.content.strip()


def transcribe_and_clean(wav_path, context=None):
    """Cleaned transcript text, or None if silent/no speech.

    Raises only if speech-to-text itself failed — a failed *cleanup* degrades to
    the raw transcript, since throwing away good audio-to-text over a cosmetic
    second call is never the right trade.
    """
    name = Path(wav_path).name
    context = dict(context or {})
    context.setdefault("wav_path", str(wav_path))

    if is_silent(wav_path):
        return None

    raw = with_retries(
        lambda: transcribe(wav_path), f"stt {name}", phase="stt", context=context
    )
    if not raw:
        log(f"{name}: speech-to-text returned no text")
        return None

    # The cleanup model carries the tight per-minute token budget, so give the
    # window a chance to roll over before spending on it.
    pace_for_rate_limit()
    try:
        return with_retries(
            lambda: clean(raw), f"cleanup {name}", phase="cleanup", context=context
        )
    except Exception as exc:
        title, detail, _ = describe_error(exc)
        log(f"{name}: cleanup failed ({title}) — keeping raw transcript", exc)
        notify("Cleanup skipped", f"{title}. Saved the raw transcript instead.")
        return raw
