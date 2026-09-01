#!/usr/bin/env python3
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import lib

SESSIONS_DIR = lib.PROJECT_DIR / "sessions"
CURRENT_SESSION_FILE = lib.STATE_DIR / "current_session"
PID_FILE = lib.STATE_DIR / "recording.pid"
WAV_FILE = lib.STATE_DIR / "recording.wav"
SCREENSHOT_SCRIPT = lib.PROJECT_DIR / "screenshot.sh"


def current_session_id():
    if CURRENT_SESSION_FILE.exists():
        return CURRENT_SESSION_FILE.read_text().strip()
    return None


def session_dir(session_id):
    return SESSIONS_DIR / session_id


def next_index(dir_path, suffix):
    dir_path.mkdir(parents=True, exist_ok=True)
    existing = sorted(dir_path.glob(f"*{suffix}"))
    if not existing:
        return 1
    return int(existing[-1].stem) + 1


def take_screenshot(target_path):
    subprocess.run([str(SCREENSHOT_SCRIPT), str(target_path)], check=False)


def start_recording_segment():
    lib.STATE_DIR.mkdir(exist_ok=True)
    pid = lib.start_pw_record(WAV_FILE)
    PID_FILE.write_text(str(pid))


def stop_recording_segment():
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text())
    lib.stop_pw_record(pid)
    PID_FILE.unlink(missing_ok=True)
    if not WAV_FILE.exists() or WAV_FILE.stat().st_size < 1000:
        WAV_FILE.unlink(missing_ok=True)
        return None
    return WAV_FILE


def spawn_finalize(session_id, index, wav_snapshot_path):
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "finalize",
            session_id,
            str(index),
            str(wav_snapshot_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def finalize_current_segment(session_id, sdir):
    wav = stop_recording_segment()
    if wav is None:
        return None
    idx = next_index(sdir / "transcripts", ".txt")
    snapshot = lib.STATE_DIR / f"session-{session_id}-{idx}.wav"
    wav.rename(snapshot)
    spawn_finalize(session_id, idx, snapshot)
    return idx


def toggle_session():
    sid = current_session_id()
    if sid is None:
        new_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        sdir = session_dir(new_id)
        (sdir / "screenshots").mkdir(parents=True, exist_ok=True)
        (sdir / "transcripts").mkdir(parents=True, exist_ok=True)
        CURRENT_SESSION_FILE.write_text(new_id)
        start_recording_segment()
        take_screenshot(sdir / "screenshots" / "001.png")
        lib.notify("Session started", f"{new_id} - recording + screenshot 1")
    else:
        sdir = session_dir(sid)
        idx = finalize_current_segment(sid, sdir)
        CURRENT_SESSION_FILE.unlink(missing_ok=True)
        if idx is None:
            lib.notify("Session ended", f"{sid} - no final segment (silence/empty)")
        else:
            lib.notify("Session ended", f"{sid} - finalizing transcript {idx}...")


def add_screenshot():
    sid = current_session_id()
    if sid is None:
        lib.notify("No active session", "Press Super+Z first to start one.")
        return
    sdir = session_dir(sid)
    (sdir / "screenshots").mkdir(parents=True, exist_ok=True)
    idx = next_index(sdir / "screenshots", ".png")
    take_screenshot(sdir / "screenshots" / f"{idx:03d}.png")
    lib.notify("Screenshot added", f"{sid} - screenshot {idx}")


def split_transcript():
    sid = current_session_id()
    if sid is None:
        lib.notify("No active session", "Press Super+Z first to start one.")
        return
    sdir = session_dir(sid)
    idx = finalize_current_segment(sid, sdir)
    if idx is None:
        lib.notify("Segment empty", "No speech in that segment, starting next...")
    else:
        lib.notify("Transcript saved", f"{sid} - segment {idx}, starting next...")
    start_recording_segment()


def finalize(session_id, index, wav_path):
    wav_path = Path(wav_path)
    sdir = session_dir(session_id)
    try:
        cleaned = lib.transcribe_and_clean(wav_path)
    except Exception:
        lib.notify("Transcript failed", f"{session_id} segment {index}: network error.")
        return
    finally:
        wav_path.unlink(missing_ok=True)

    if cleaned is None:
        lib.notify("Transcript empty", f"{session_id} segment {index}: no speech detected.")
        return

    out_file = sdir / "transcripts" / f"{int(index):03d}.txt"
    out_file.write_text(cleaned)
    preview = cleaned if len(cleaned) < 100 else cleaned[:97] + "..."
    lib.notify(f"Transcript {index} saved", preview)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("toggle")
    sub.add_parser("screenshot")
    sub.add_parser("split")
    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("session_id")
    p_finalize.add_argument("index")
    p_finalize.add_argument("wav_path")

    args = parser.parse_args()

    if args.command == "toggle":
        toggle_session()
    elif args.command == "screenshot":
        add_screenshot()
    elif args.command == "split":
        split_transcript()
    elif args.command == "finalize":
        finalize(args.session_id, args.index, args.wav_path)


if __name__ == "__main__":
    main()
