#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

import jobs
import lib

PID_FILE = lib.STATE_DIR / "recording.pid"
WAV_FILE = lib.STATE_DIR / "recording.wav"
FAILED_DIR = lib.STATE_DIR / "failed-dictations"
PENDING_DIR = lib.STATE_DIR / "pending-audio"


def start_recording():
    lib.STATE_DIR.mkdir(exist_ok=True)
    if PID_FILE.exists():
        print("Already recording.", file=sys.stderr)
        return
    pid = lib.start_pw_record(WAV_FILE)
    PID_FILE.write_text(str(pid))
    lib.notify("Dictation", "Recording... press again to stop")


def stop_recording_and_process():
    if not PID_FILE.exists():
        print("Not recording.", file=sys.stderr)
        return
    pid = int(PID_FILE.read_text())
    lib.stop_pw_record(pid)
    PID_FILE.unlink(missing_ok=True)

    if not WAV_FILE.exists() or WAV_FILE.stat().st_size < 1000:
        lib.log("dictate: no audio captured (missing or under 1000 bytes)")
        lib.notify("Dictation", "No audio captured.")
        return

    # Move the audio somewhere unique before queueing: the job may not run for
    # a while if segments are ahead of it, and .state/recording.wav is reused by
    # the very next recording.
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = PENDING_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.wav"
    WAV_FILE.rename(snapshot)

    # Queued, not spawned: dictation shares the one worker with session
    # segments, so the two can never hit Groq at the same moment.
    jobs.submit("dictate", label=snapshot.name, wav_path=str(snapshot))


def keep_failed_audio(wav_path):
    """Move audio we could not transcribe somewhere it will not be overwritten."""
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    dest = FAILED_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
    wav_path.rename(dest)
    lib.log(f"dictate: audio kept at {dest.relative_to(lib.PROJECT_DIR)}")
    return dest


def process_recording(wav_path=None):
    wav_path = Path(wav_path) if wav_path else WAV_FILE
    if not wav_path.exists():
        return

    lib.notify("Dictation", "Transcribing...")
    try:
        cleaned = lib.transcribe_and_clean(wav_path, context={"kind": "dictate"})
    except Exception as exc:
        title, body, retryable = lib.describe_error(exc)
        lib.log(f"dictate: GAVE UP — {title}: {body}", exc)
        lib.record_failure("dictate", exc, wav_path=str(wav_path), kind="dictate")
        kept = wav_path if wav_path.parent == FAILED_DIR else keep_failed_audio(wav_path)
        hint = "Retry with './dictate.py retry'." if retryable else ""
        lib.notify(f"Dictation failed: {title}", f"{body} Audio kept as {kept.name}. {hint}")
        return

    if cleaned is None:
        lib.log("dictate: no speech detected")
        lib.notify("Dictation", "No speech detected.")
        wav_path.unlink(missing_ok=True)
        return

    lib.copy_to_clipboard(cleaned)
    lib.log(f"dictate: transcribed {len(cleaned)} chars to clipboard")
    if wav_path.parent in (FAILED_DIR, PENDING_DIR) or not lib.KEEP_AUDIO:
        wav_path.unlink(missing_ok=True)
    preview = cleaned if len(cleaned) < 120 else cleaned[:117] + "..."
    lib.notify("Copied to clipboard", preview)
    print(cleaned)


def retry_failed():
    stashed = sorted(FAILED_DIR.glob("*.wav")) if FAILED_DIR.exists() else []
    stashed += sorted(PENDING_DIR.glob("*.wav")) if PENDING_DIR.exists() else []
    if not stashed:
        print("No failed dictations waiting.")
        return
    print(f"Retrying {len(stashed)} dictation(s)...\n")
    for wav in stashed:
        print(f"  {wav.name} ... ", end="", flush=True)
        process_recording(wav)
        print("gone (recovered)" if not wav.exists() else "still failing")


def toggle():
    if PID_FILE.exists():
        stop_recording_and_process()
    else:
        start_recording()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["start", "stop", "toggle", "process", "retry"]
    )
    args = parser.parse_args()

    {
        "start": start_recording,
        "stop": stop_recording_and_process,
        "toggle": toggle,
        "process": process_recording,
        "retry": retry_failed,
    }[args.command]()


if __name__ == "__main__":
    main()
