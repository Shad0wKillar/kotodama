#!/usr/bin/env python3
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

import jobs
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
    if not WAV_FILE.exists():
        lib.log("stop_recording_segment: pw-record produced no file at all")
        return None
    size = WAV_FILE.stat().st_size
    if size < 1000:
        lib.log(f"stop_recording_segment: discarding {size}-byte WAV (nothing captured)")
        WAV_FILE.unlink(missing_ok=True)
        return None
    return WAV_FILE


def queue_finalize(session_id, index, wav_snapshot_path):
    """Hand the slow API work to the single queue worker.

    Queued rather than spawned directly: three quick Super+Shift+I presses used
    to mean three concurrent transcribe+cleanup pairs racing each other into the
    per-minute token limit. Now they line up and run one at a time.
    """
    jobs.submit(
        "session",
        label=f"{session_id}/{int(index):03d}",
        session_id=session_id,
        index=str(index),
        wav_path=str(wav_snapshot_path),
    )


def finalize_current_segment(session_id, sdir):
    """Stop recording and move the audio somewhere durable before touching the API."""
    wav = stop_recording_segment()
    if wav is None:
        return None
    idx = next_index(sdir / "transcripts", ".txt")
    # Park the audio inside the session itself, not .state — it is the backup,
    # and it survives whatever the API does next.
    audio_dir = sdir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    snapshot = audio_dir / f"{idx:03d}.wav"
    wav.rename(snapshot)
    lib.log(f"segment {session_id}/{idx}: audio saved to {snapshot.relative_to(lib.PROJECT_DIR)}")
    queue_finalize(session_id, idx, snapshot)
    return idx


def toggle_session():
    sid = current_session_id()
    if sid is None:
        new_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        sdir = session_dir(new_id)
        (sdir / "screenshots").mkdir(parents=True, exist_ok=True)
        (sdir / "transcripts").mkdir(parents=True, exist_ok=True)
        (sdir / "audio").mkdir(parents=True, exist_ok=True)
        CURRENT_SESSION_FILE.write_text(new_id)
        start_recording_segment()
        lib.log(f"session {new_id}: started")
        take_screenshot(sdir / "screenshots" / "001.png")
        lib.notify("Session started", f"{new_id} - recording + screenshot 1")
    else:
        sdir = session_dir(sid)
        idx = finalize_current_segment(sid, sdir)
        CURRENT_SESSION_FILE.unlink(missing_ok=True)
        lib.log(f"session {sid}: ended")
        if idx is None:
            lib.notify("Session ended", f"{sid} - no final segment (silence/empty)")
        else:
            lib.notify("Session ended", f"{sid} - finalizing transcript {idx}...")


def add_screenshot():
    sid = current_session_id()
    if sid is None:
        lib.notify("No active session", "Press Super+R first to start one.")
        return
    sdir = session_dir(sid)
    (sdir / "screenshots").mkdir(parents=True, exist_ok=True)
    idx = next_index(sdir / "screenshots", ".png")
    take_screenshot(sdir / "screenshots" / f"{idx:03d}.png")
    lib.notify("Screenshot added", f"{sid} - screenshot {idx}")


def split_transcript():
    sid = current_session_id()
    if sid is None:
        lib.notify("No active session", "Press Super+R first to start one.")
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
    label = f"{session_id}/{int(index):03d}"

    if not wav_path.exists():
        lib.log(f"finalize {label}: audio missing at {wav_path} — nothing to do")
        return

    try:
        cleaned = lib.transcribe_and_clean(
            wav_path, context={"session_id": session_id, "index": str(index), "kind": "session"}
        )
    except Exception as exc:
        title, body, retryable = lib.describe_error(exc)
        lib.log(f"finalize {label}: GAVE UP — {title}: {body}", exc)
        lib.record_failure(
            "finalize",
            exc,
            session_id=session_id,
            index=str(index),
            wav_path=str(wav_path),
            kind="session",
        )
        hint = "Audio kept — run './session.py retry'." if retryable else "Audio kept."
        lib.notify(f"Transcript {int(index)} failed: {title}", f"{body} {hint}")
        return  # audio deliberately left in place

    if cleaned is None:
        lib.log(f"finalize {label}: no speech detected (audio kept for inspection)")
        lib.notify(f"Transcript {int(index)} empty", "No speech detected. Audio kept.")
        return

    out_file = sdir / "transcripts" / f"{int(index):03d}.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(cleaned)
    lib.log(f"finalize {label}: saved {out_file.name} ({len(cleaned)} chars)")

    if not lib.KEEP_AUDIO:
        wav_path.unlink(missing_ok=True)

    preview = cleaned if len(cleaned) < 100 else cleaned[:97] + "..."
    lib.notify(f"Transcript {int(index)} saved", preview)


def pending_segments(session_id=None):
    """Audio files with no matching transcript — i.e. everything still owed."""
    pending = []
    for audio_dir in sorted(SESSIONS_DIR.glob("*/audio")):
        sid = audio_dir.parent.name
        if session_id and sid != session_id:
            continue
        for wav in sorted(audio_dir.glob("*.wav")):
            if not (audio_dir.parent / "transcripts" / f"{wav.stem}.txt").exists():
                pending.append((sid, wav.stem, wav))
    return pending


def list_pending(session_id=None):
    pending = pending_segments(session_id)
    if not pending:
        print("Nothing pending — every saved recording has a transcript.")
        return
    print(f"{len(pending)} recording(s) without a transcript:\n")
    for sid, idx, wav in pending:
        mb = wav.stat().st_size / 1_048_576
        peak = lib.peak_amplitude(wav)
        note = "  (silent!)" if peak is not None and peak < lib.SILENCE_THRESHOLD else ""
        print(f"  {sid}  segment {idx}  {mb:5.2f} MB  peak={peak}{note}")
        history = lib.read_failures(sid, idx)
        if history:
            last = history[-1]
            print(
                f"      last failure: {last.get('title')} — {last.get('detail')} "
                f"({last.get('phase')}, {last.get('time')}, {len(history)} attempt(s) logged)"
            )
    print("\nRe-run them with:  ./session.py retry")
    print("Full detail:       ./session.py failures")


def retry_pending(session_id=None):
    pending = pending_segments(session_id)
    if not pending:
        print("Nothing to retry.")
        return
    print(f"Retrying {len(pending)} segment(s)...\n")
    ok = 0
    for sid, idx, wav in pending:
        print(f"  {sid} segment {idx} ... ", end="", flush=True)
        finalize(sid, idx, wav)
        if (session_dir(sid) / "transcripts" / f"{idx}.txt").exists():
            print("done")
            ok += 1
        else:
            print("still failing (see .state/kotodama.log)")
    print(f"\n{ok}/{len(pending)} recovered.")


def show_failures(session_id=None, limit=20):
    """Everything that has ever failed, newest last, straight from failures.jsonl."""
    records = lib.read_failures(session_id)
    if not records:
        print("No failures recorded. (.state/failures.jsonl is empty or absent.)")
        return
    shown = records[-limit:]
    print(f"{len(records)} failure record(s); showing last {len(shown)}:\n")
    for r in shown:
        head = f"{r.get('time')}  {r.get('phase'):>9}  {r.get('title')}"
        if r.get("label") or r.get("session_id"):
            head += f"  [{r.get('label') or r.get('session_id')}"
            if r.get("index"):
                head += f"/{r.get('index')}"
            head += "]"
        print(head)
        print(f"    {r.get('exception')}"
              + (f" HTTP {r['http_status']}" if r.get("http_status") else "")
              + (f"  attempt {r['attempt']}/{lib.MAX_ATTEMPTS}" if r.get("attempt") else "")
              + f"  retryable={r.get('retryable')}")
        if r.get("groq_message"):
            print(f"    groq: {r['groq_message']}")
        if r.get("wav_peak") is not None:
            print(f"    audio: {r.get('wav_bytes', 0) / 1_048_576:.2f} MB  peak={r['wav_peak']}")
        rate = r.get("rate_state") or {}
        if rate.get("remaining_tokens") is not None:
            print(f"    tokens left at the time: {rate['remaining_tokens']}/{rate.get('limit_tokens')}")
        print()
    print(f"Raw records: {lib.FAILURE_LOG}")
    print(f"Full log:    {lib.LOG_FILE}")


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
    p_pending = sub.add_parser("pending", help="list recordings with no transcript")
    p_pending.add_argument("session_id", nargs="?")
    p_retry = sub.add_parser("retry", help="re-transcribe recordings with no transcript")
    p_retry.add_argument("session_id", nargs="?")
    p_fail = sub.add_parser("failures", help="show why transcriptions failed")
    p_fail.add_argument("session_id", nargs="?")
    p_fail.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "toggle":
        toggle_session()
    elif args.command == "screenshot":
        add_screenshot()
    elif args.command == "split":
        split_transcript()
    elif args.command == "finalize":
        finalize(args.session_id, args.index, args.wav_path)
    elif args.command == "pending":
        list_pending(args.session_id)
    elif args.command == "retry":
        retry_pending(args.session_id)
    elif args.command == "failures":
        show_failures(args.session_id, args.limit)


if __name__ == "__main__":
    main()
