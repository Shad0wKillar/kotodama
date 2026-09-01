#!/usr/bin/env python3
import subprocess

import lib

SESSIONS_DIR = lib.PROJECT_DIR / "sessions"

BACK_TO_SESSIONS = "<- back to sessions"
QUIT = "<- quit"


def rofi_pick(options, prompt):
    if not options:
        return None
    proc = subprocess.run(
        ["rofi", "-dmenu", "-p", prompt],
        input="\n".join(options).encode(),
        capture_output=True,
    )
    choice = proc.stdout.decode().strip()
    return choice or None


def session_summary(sdir):
    n_shots = len(list((sdir / "screenshots").glob("*.png"))) if (sdir / "screenshots").exists() else 0
    n_texts = len(list((sdir / "transcripts").glob("*.txt"))) if (sdir / "transcripts").exists() else 0
    return f"{sdir.name}  —  {n_shots} screenshot(s), {n_texts} transcript(s)"


def view_and_copy_screenshots(shots):
    lib.notify("Screenshots", "Left/Right arrows to browse, Enter to copy the shown one and close, q to close without copying")
    subprocess.run(
        [
            "imv",
            "-f",
            "-c",
            'bind <Return> exec wl-copy < "$imv_current_file" && kill $imv_pid',
            *[str(p) for p in shots],
        ]
    )


def copy_transcript(path):
    text = path.read_text()
    lib.copy_to_clipboard(text)
    preview = text if len(text) < 120 else text[:117] + "..."
    lib.notify("Copied to clipboard", preview)


def browse_session(sid, sdir):
    """Returns 'back' if the user asked to go back to the session list,
    or 'done' once an actual copy action has been taken."""
    while True:
        shots = sorted((sdir / "screenshots").glob("*.png")) if (sdir / "screenshots").exists() else []
        texts = sorted((sdir / "transcripts").glob("*.txt")) if (sdir / "transcripts").exists() else []

        options = []
        if shots:
            options.append(f"screenshots ({len(shots)}) - view & copy")
        for p in texts:
            preview = p.read_text().strip().replace("\n", " ")
            preview = preview if len(preview) < 60 else preview[:57] + "..."
            options.append(f"transcript {p.stem}: {preview}")
        options.append(BACK_TO_SESSIONS)

        choice = rofi_pick(options, sid)
        if not choice or choice == BACK_TO_SESSIONS:
            return "back"

        if choice.startswith("screenshots"):
            view_and_copy_screenshots(shots)
        else:
            stem = choice.split()[1].rstrip(":")
            copy_transcript(sdir / "transcripts" / f"{stem}.txt")
        return "done"


def main():
    while True:
        if not SESSIONS_DIR.exists():
            lib.notify("Sessions", "No sessions yet.")
            return
        sessions = sorted(SESSIONS_DIR.iterdir(), reverse=True)
        if not sessions:
            lib.notify("Sessions", "No sessions yet.")
            return

        labels = [session_summary(s) for s in sessions] + [QUIT]
        choice = rofi_pick(labels, "session")
        if not choice or choice == QUIT:
            return

        sid = choice.split()[0]
        result = browse_session(sid, SESSIONS_DIR / sid)
        if result == "done":
            return
        # else "back" -> loop and show the session list again


if __name__ == "__main__":
    main()
