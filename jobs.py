#!/usr/bin/env python3
"""Single-worker job queue for everything that talks to Groq.

Without this, each finalized segment spawned its own detached process, so
pressing Super+Shift+I three times in a minute fired three concurrent
transcribe+cleanup pairs at Groq — six calls at once, easily over the
8000-tokens-per-minute ceiling on the cleanup model. Now every segment is
queued and drained by exactly one worker, one call at a time, and the worker
paces itself using Groq's own remaining-token headers.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import lib

QUEUE_DIR = lib.STATE_DIR / "queue"
LOCK_FILE = lib.STATE_DIR / "worker.lock"


def enqueue(kind, label="", **payload):
    """Write a job file atomically, so a worker never reads a half-written one."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = f"{stamp}-{os.getpid()}.json"
    job = {
        "kind": kind,
        "label": label,
        "enqueued_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    tmp = QUEUE_DIR / f".{name}.tmp"
    tmp.write_text(json.dumps(job))
    tmp.rename(QUEUE_DIR / name)
    lib.log(f"queue: enqueued {kind} {label} ({name})")
    return QUEUE_DIR / name


def queued_jobs():
    if not QUEUE_DIR.exists():
        return []
    return sorted(QUEUE_DIR.glob("*.json"))


def spawn_worker():
    """Start a worker. Exits immediately and harmlessly if one already runs."""
    lib.STATE_DIR.mkdir(exist_ok=True)
    log_fh = open(lib.LOG_FILE, "a")
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "worker"],
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    log_fh.close()


def submit(kind, label="", **payload):
    """Queue work and make sure a worker is draining it. Returns immediately."""
    enqueue(kind, label=label, **payload)
    spawn_worker()


def _handle(job):
    kind = job.get("kind")
    if kind == "session":
        import session

        session.finalize(job["session_id"], job["index"], job["wav_path"])
    elif kind == "dictate":
        import dictate

        dictate.process_recording(job["wav_path"])
    else:
        lib.log(f"queue: unknown job kind {kind!r} — dropping")


def run_worker():
    lib.STATE_DIR.mkdir(exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lib.log("queue: a worker is already running — exiting, it will pick this up")
        lock.close()
        return

    lib.log("queue: worker started")
    processed = 0
    try:
        while True:
            jobs = queued_jobs()
            if not jobs:
                break
            path = jobs[0]
            try:
                job = json.loads(path.read_text())
            except Exception as exc:
                lib.log(f"queue: unreadable job {path.name} — dropping", exc)
                path.unlink(missing_ok=True)
                continue

            lib.log(f"queue: running {job.get('kind')} {job.get('label', '')} ({path.name})")
            # Wait out the token window *before* the call, not after failing it.
            lib.pace_for_rate_limit()
            try:
                _handle(job)
            except Exception as exc:
                lib.log(f"queue: job {path.name} raised out of its handler", exc)
                lib.record_failure(
                    "worker",
                    exc,
                    kind=job.get("kind"),
                    label=job.get("label"),
                    session_id=job.get("session_id"),
                    index=job.get("index"),
                    wav_path=job.get("wav_path"),
                )
            path.unlink(missing_ok=True)
            processed += 1
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        lib.log(f"queue: worker finished after {processed} job(s)")
        # Close the shutdown race: a job enqueued while we were on our way out
        # would otherwise sit here with nobody running.
        if queued_jobs():
            lib.log("queue: work arrived during shutdown — relaunching")
            spawn_worker()


def show_status():
    jobs = queued_jobs()
    running = True
    lock = open(LOCK_FILE, "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_UN)
        running = False
    except BlockingIOError:
        running = True
    finally:
        lock.close()

    print(f"worker running : {'yes' if running else 'no'}")
    print(f"jobs queued    : {len(jobs)}")
    for path in jobs:
        try:
            job = json.loads(path.read_text())
        except Exception:
            print(f"  {path.name}  (unreadable)")
            continue
        print(f"  {job.get('enqueued_at', '?')}  {job.get('kind')}  {job.get('label', '')}")

    try:
        rate = json.loads(lib.RATE_STATE_FILE.read_text())
        print(
            f"token budget   : {rate.get('remaining_tokens')}/{rate.get('limit_tokens')} "
            f"left as of last call, window resets in {rate.get('reset_seconds', 0):.1f}s"
        )
    except Exception:
        print("token budget   : not observed yet")

    held = lib.cooldown_remaining()
    if held > 0:
        try:
            reason = json.loads(lib.COOLDOWN_FILE.read_text()).get("reason", "")
        except Exception:
            reason = ""
        print(f"cooldown       : HELD for another {held:.0f}s — {reason}")
    else:
        print("cooldown       : none")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("worker", help="drain the queue (one worker at a time)")
    sub.add_parser("status", help="show queue depth and token budget")
    args = parser.parse_args()
    if args.command == "worker":
        run_worker()
    else:
        show_status()


if __name__ == "__main__":
    main()
