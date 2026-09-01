#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

import lib

PID_FILE = lib.STATE_DIR / "recording.pid"
WAV_FILE = lib.STATE_DIR / "recording.wav"


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
        lib.notify("Dictation", "No audio captured.")
        return

    # Hand the slow network work off to a fully detached process so the
    # hotkey invocation itself returns immediately, no matter what's
    # invoking us (Hyprland's exec_cmd, a shell, etc).
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "process"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def process_recording():
    if not WAV_FILE.exists():
        return

    lib.notify("Dictation", "Transcribing...")
    try:
        cleaned = lib.transcribe_and_clean(WAV_FILE)
    except Exception:
        lib.notify("Dictation failed", "Network timed out. Check your connection and try again.")
        return
    finally:
        WAV_FILE.unlink(missing_ok=True)

    if cleaned is None:
        lib.notify("Dictation", "No speech detected.")
        return

    lib.copy_to_clipboard(cleaned)
    preview = cleaned if len(cleaned) < 120 else cleaned[:117] + "..."
    lib.notify("Copied to clipboard", preview)
    print(cleaned)


def toggle():
    if PID_FILE.exists():
        stop_recording_and_process()
    else:
        start_recording()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "toggle", "process"])
    args = parser.parse_args()

    {
        "start": start_recording,
        "stop": stop_recording_and_process,
        "toggle": toggle,
        "process": process_recording,
    }[args.command]()


if __name__ == "__main__":
    main()
