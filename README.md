# kotodama

Hotkey-driven voice dictation and annotated screenshots for Linux/Hyprland, using Groq's
free-tier cloud Whisper + LLM API. No local GPU/CPU load — everything heavy runs on Groq's
servers, this machine just captures mic audio and makes two API calls.

Two workflows:

- **Standalone tools** — quick one-off dictation or screenshot, straight to clipboard.
- **Session/bundle tool** — links multiple screenshots and multiple transcript segments
  together into one folder, so you can capture a bunch of screenshots and notes about them
  and retrieve them as a linked set later.

## Requirements

- Arch Linux (or any distro with the packages below available)
- **Hyprland 0.55+ with the Lua config** (`hyprctl eval` / `hl.bind` / `hl.dsp.exec_cmd`
  must work — check with `hyprctl eval "return 1"`). If your Hyprland uses the older
  hyprlang `hyprland.conf` format instead, the keybindings need translating to
  `bind = SUPER, D, exec, ...` syntax instead of the Lua shown below.
- Wayland session (`$XDG_SESSION_TYPE` = `wayland`)
- A free [Groq](https://console.groq.com) account (no credit card required)

## Quick install

```sh
git clone https://github.com/Shad0wKillar/kotodama.git ~/dev/personal/kotodama
cd ~/dev/personal/kotodama
./install.sh
```

This does everything below in one shot: installs the system packages, installs `uv` if
missing, sets up the Python environment, creates your `.env` from the template, and adds
the keybindings to `~/.config/hypr/custom.lua` (creating it if needed) — then reloads
Hyprland. It's safe to re-run; it skips whatever's already done.

**It will not work yet after this** — you still need to add your own Groq API key. The
script tells you this at the end and won't let you miss it; see
[Get a free Groq API key](#4-get-a-free-groq-api-key) below for how.

To remove everything it added — the keybindings block, the `.venv`, and (optionally, it
asks first) any system packages it installed that weren't already on your machine — run
`./uninstall.sh`. It leaves your `.env`, `sessions/`, `screenshots/`, and the project
folder itself alone; delete those yourself if you want a full wipe.

The sections below explain each step manually, in case you'd rather do it by hand or want
to understand what the script is doing.

## 1. Install system packages

Everything needed is in Arch's official `extra` repo — no AUR required.

```sh
sudo pacman -S grim slurp satty imv wl-clipboard cliphist rofi pipewire libnotify
```

| Package | Used for |
|---|---|
| `grim` + `slurp` | screen region capture |
| `satty` | screenshot pen/text annotation editor |
| `imv` | viewing/copying screenshots (arrow keys to browse, Enter to copy) |
| `wl-clipboard` | `wl-copy`/`wl-paste` — setting/reading the Wayland clipboard |
| `cliphist` | clipboard history (used to tell multiple recent screenshots apart) |
| `rofi` | the picker menus (session browser, clipboard screenshot picker) |
| `pipewire` | provides `pw-record`, used to capture microphone audio |
| `libnotify` | `notify-send` — the status notifications each tool sends |

`cliphist` needs a watcher running to actually record clipboard history. If your Hyprland
config doesn't already start one, add this to your autostart:

```sh
wl-paste --watch cliphist store
```

## 2. Install `uv` (Python package/venv manager)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 3. Get this project and set up the Python environment

```sh
# put it wherever you like — the keybindings below assume ~/dev/personal/kotodama
git clone https://github.com/Shad0wKillar/kotodama.git ~/dev/personal/kotodama
cd ~/dev/personal/kotodama
uv sync
```

`uv sync` reads `uv.lock` (committed to this repo) and builds `.venv/` with the **exact
pinned versions** of every dependency, transitive ones included — no version drift. A
plain `requirements.txt` is also included for reference/pip users, but `uv.lock` is the
source of truth.

## 4. Get a free Groq API key

1. Go to [console.groq.com](https://console.groq.com) and sign up (free, no card).
2. Click **API Keys** in the left sidebar → **Create API Key**.
3. Copy the key (starts with `gsk_...`).

Then create your `.env` file:

```sh
cp .env.example .env
# edit .env and paste your key in:
#   GROQ_API_KEY=gsk_...
```

Groq's free tier covers this comfortably for personal use. The limits that actually
bind, read straight off the API response headers (`x-ratelimit-*`):

| Endpoint | Limit | Window |
|---|---|---|
| `whisper-large-v3-turbo` (transcription) | 2000 requests | per day |
| `openai/gpt-oss-120b` (cleanup) | 1000 requests | per day |
| `openai/gpt-oss-120b` (cleanup) | 8000 tokens | **per minute** |

The 8000 tokens/minute on the cleanup model is the one you can realistically trip — a
burst of long segments finalizing at once can hit it, which returns HTTP 429. kotodama
handles that by backing off for exactly as long as Groq's `retry-after` header asks, then
retrying (see [Reliability](#reliability-and-recovering-failed-transcripts)). Check your
own current limits any time at
[console.groq.com/settings/limits](https://console.groq.com/settings/limits) — free-tier
terms change.

## 5. Wire up the keybindings

Copy the contents of [`hyprland-keybindings.lua`](./hyprland-keybindings.lua) into your
own Hyprland Lua config (e.g. `~/.config/hypr/custom.lua`, if your setup auto-loads that
— ML4W dotfiles do this via `require("custom")`). It assumes the project lives at
`~/dev/personal/kotodama`; edit the `kotodamaDir` line if you put it elsewhere.

Then reload Hyprland's config: `hyprctl reload config-only` (or just log out/in).

## Keybindings

| Key | Action |
|---|---|
| `Super+D` | Dictation: record → transcribe → clean up → clipboard |
| `Super+A` | Screenshot: select a region, annotate (pen/text/arrows), copy + save |
| `Super+Shift+V` | Browse recent screenshots sitting in clipboard history |
| `Super+R` | **Session**: toggle — start (record + screenshot 1) / end (finalize last segment) |
| `Super+I` | **Session**: add another screenshot to the current session |
| `Super+Shift+I` | **Session**: finalize current transcript segment, start a new one (same screenshots) |
| `Super+O` | **Session**: browse a session's screenshots/transcripts, copy one |

Every recording-based key (`D`, `R`, `Shift+I`) is a start/stop **toggle on the same key**
— press once to start, press again to stop that segment.

## Usage

**Quick dictation:** press `Super+D`, talk, press `Super+D` again. A notification says
"Transcribing...", then the cleaned-up text lands on your clipboard — paste it wherever.

**Quick annotated screenshot:** press `Super+A`, drag to select a region, use satty's
toolbar (or its default pen tool) to draw/type on it, press Enter to copy it and save it
to `screenshots/`. Escape cancels without saving.

**Bundling a screenshot + note session:**
1. `Super+R` — starts recording and opens the screenshot tool for shot #1. Select a
   region, annotate if you want, Enter to save it.
2. Talk about it.
3. `Super+I` any time to grab another screenshot into the same session (recording keeps
   going the whole time).
4. `Super+Shift+I` if you want to close out what you just said as its own note and start
   a fresh one — useful when you're moving on to commenting on a different part of the
   same screenshot(s) without taking a new picture.
5. `Super+R` again when you're done — stops recording and finalizes the last note.
6. Later, `Super+O` → pick that session from the list → pick "screenshots" to flip through
   them (arrow keys, Enter copies the one shown) or pick a transcript segment to copy its
   text directly.

## How the session/bundle tool works

`Super+R` starts a new folder under `sessions/<timestamp>/` with `screenshots/` and
`transcripts/` subfolders, begins recording, and takes the first screenshot. While a
session is open:

- `Super+I` adds another screenshot to it (recording keeps going uninterrupted).
- `Super+Shift+I` finalizes what's been said so far as one transcript segment and
  immediately starts recording the next segment — use this for "one screenshot, several
  separate notes about it."
- `Super+R` again ends the session (stops recording, finalizes the last segment).

Each screenshot and transcript is a numbered file (`001.png`, `002.txt`, ...) inside that
session's folder — the folder itself *is* the link between them. `Super+O` opens a picker:
choose a session, then either open all its screenshots in `imv` (arrow keys to flip
between them, Enter to copy the one showing and close), or pick a transcript segment to
copy directly. Any copy action closes the picker; a "← back" option lets you navigate
without copying anything.

Clipboards only ever hold one item at a time — there's no "copy all 3 screenshots at
once." The session folder is the actual bundle; the picker just makes retrieving from it
fast.

## How work reaches Groq: one queue, one worker

Every transcription — session segments and standalone `Super+D` dictations alike — is
**queued**, never fired off directly. Splitting three segments in quick succession used to
spawn three independent processes that all hit Groq at once: six concurrent calls, and an
easy way to blow through the 8000-tokens-per-minute ceiling on the cleanup model and start
collecting 429s.

Now each finalized segment drops a job file into `.state/queue/` and a single worker drains
it **one call at a time**, in the order the segments were recorded. If a worker is already
running, a second one exits immediately rather than competing for the same jobs — enforced
with an `flock` on `.state/worker.lock`, so it holds even across separate keypresses and
separate processes.

Recording is completely unaffected: it never waits on the queue. Press `Super+Shift+I` as
fast as you like — each press stops one recording, starts the next, and leaves a job
behind. Only the network calls are serialized.

The worker also **paces itself against Groq's own accounting**. Every response's
`x-ratelimit-remaining-tokens` header is recorded, and if the remaining budget drops below
`KOTODAMA_TOKEN_RESERVE` (1500), the worker sleeps until the window rolls over before
starting the next job — using the reset time Groq reports rather than a guess.

### When the limit is hit anyway: stop, wait a full window, retry

Pacing is preventive, not a guarantee — a single long segment can still exhaust the
minute. When Groq answers **429**, there is nothing clever to do: the minute's tokens are
gone and no amount of backing off a few seconds will conjure more. So kotodama treats a
429 differently from every other error:

1. **Stop.** A hold is written to `.state/cooldown_until` and *every* Groq call respects
   it — not just the call that failed. The whole queue parks.
2. **Wait a full window** — 60 seconds by default (`KOTODAMA_RATE_LIMIT_WAIT`), even when
   Groq's `retry-after` header suggests less. If it asks for *longer* than a window, the
   longer value wins.
3. **Retry automatically.** Up to `KOTODAMA_RATE_LIMIT_ATTEMPTS` (5) full-window waits, so
   it will keep patiently trying for about five minutes before giving up — and if it does
   give up, the audio is still on disk for `./session.py retry`.

The hold lives on disk rather than in memory deliberately: if the process that hit the
limit exits, the next job would otherwise start up and 429 straight into the same wall.

Rate-limit waits are counted **separately** from ordinary retries. `KOTODAMA_MAX_ATTEMPTS`
(3) is reserved for genuinely flaky failures — timeouts, 5xx — so a couple of rate-limit
holds can never quietly burn through the budget meant for transient network trouble.

A real trace, with the wait shortened to 12s to keep the log readable — note that job
`002` sits and waits for `001` to finish, and neither starts until the hold expires:

```
01:28:08  cooldown: holding every Groq call for 12s — 429 on stt 001.wav
01:28:08  queue: enqueued session RL/001
01:28:08  queue: worker started
01:28:08  queue: running session RL/001
01:28:08  cooldown: 12s left before the next Groq call is allowed
01:28:08  queue: enqueued session RL/002
01:28:08  queue: a worker is already running — exiting, it will pick this up
01:28:22  finalize RL/001: saved 001.txt        <- 14s later, after the hold
01:28:23  queue: running session RL/002          <- only now does 002 begin
01:28:25  finalize RL/002: saved 002.txt
01:28:25  queue: worker finished after 2 job(s)
```

You get a desktop notification when a hold starts, so a stalled transcript is never a
mystery. `./jobs.py status` shows any active hold and how long is left.

```sh
./jobs.py status     # is a worker running, what's queued, how much budget is left
```

```
worker running : yes
jobs queued    : 2
  2026-09-09T01:24:05  session  20260909-012402/002
  2026-09-09T01:24:08  session  20260909-012402/003
token budget   : 7290/8000 left as of last call, window resets in 5.3s
```

## Reliability and recovering failed transcripts

Transcription needs the network, so it can fail. When it does, **the audio is never
thrown away** — every segment's WAV is written to `sessions/<id>/audio/00N.wav` *before*
the first API call, and it stays there until a transcript exists for it.

Check what's outstanding and re-run it:

```sh
./session.py pending          # list recordings that have no transcript yet
./session.py retry            # re-transcribe all of them
./session.py retry 20260909-003933    # or just one session
./dictate.py retry            # same, for failed Super+D dictations
```

`pending` also prints each recording's peak amplitude, so a segment that failed because
the mic captured nothing is obvious at a glance (it'll be flagged `(silent!)`).

There are two logs, and they answer different questions.

`.state/kotodama.log` is the running narrative — every enqueue, every job start, every
retry, every rate-limit pause, with full tracebacks. `tail -f .state/kotodama.log` while
you work if something's off.

`.state/failures.jsonl` is one JSON record per failed attempt — the file to read when you
want to know *why*. Every attempt is recorded, not just the final one, and each record
carries the phase it died in (`stt`, `cleanup`, `finalize`, `worker`), the HTTP status,
**Groq's own error message**, whether it was considered retryable, which models were in
play, the size and peak amplitude of the audio, and how much token budget was left at that
moment.

```sh
./session.py failures                    # readable summary, newest last
./session.py failures 20260909-003933    # just one session
jq -r '[.time,.phase,.title,.groq_message]|@tsv' .state/failures.jsonl   # or slice it yourself
```

```
2026-09-09T01:24:26    cleanup  Model not found  [20260909-012402/1]
    NotFoundError HTTP 404  attempt 1/3  retryable=False
    groq: The model `nope-does-not-exist` does not exist or you do not have access to it.
    audio: 0.15 MB  peak=18114
    tokens left at the time: 7134/8000
```

`./session.py pending` shows the last failure reason inline against each recording that is
still owed a transcript, so the common case needs no log reading at all.

Three behaviours worth knowing:

- **Retries are automatic.** Transient failures (timeouts, 5xx) retry up to
  `KOTODAMA_MAX_ATTEMPTS` (3) with exponential backoff; rate limits get their own
  full-window holds as described above. Permanent failures — bad API key, nonexistent
  model — fail immediately instead of burning attempts on something that cannot succeed.
- **A failed cleanup never costs you the transcript.** If speech-to-text succeeded but
  the cleanup LLM call failed, the *raw* transcript is saved rather than discarded.
- **Silent segments are skipped without an API call**, and their audio is kept so you can
  listen and confirm it really was silence.

Audio is roughly 2 MB per minute. Set `KOTODAMA_KEEP_AUDIO=0` in `.env` to delete it once
a transcript succeeds; failed segments are kept regardless.

## Configuration

Optional overrides in `.env`:

```sh
GROQ_STT_MODEL=whisper-large-v3-turbo       # transcription model
GROQ_CLEANUP_MODEL=openai/gpt-oss-120b      # cleanup/formatting model
```

Run `uv run python -c "from groq import Groq; [print(m.id) for m in Groq().models.list().data]"`
to see what's currently available on your account — Groq's model lineup changes over time.

Silence detection (skips calling the API entirely on silent/empty recordings, since
Whisper hallucinates stock phrases like "Thank you." on silence) lives in
`lib.is_silent()` — a peak-amplitude threshold, `400` out of the 16-bit range by default.
Raise it if a noisy room is triggering false transcriptions, lower it if quiet speech is
getting dropped as "no speech detected."

## Project layout

```
jobs.py                the job queue + single worker (all Groq calls go through it)
dictate.py           standalone dictation (Super+D)
screenshot.sh         standalone screenshot + annotate (Super+A)
clip-picker.sh         browse recent screenshots from clipboard history (Super+Shift+V)
session.py             session start/end, add-screenshot, split-transcript (Super+R/I/Shift+I)
session_browser.py     session picker/browser (Super+O)
lib.py                 shared: recording, Groq transcription+cleanup, clipboard, notify
sessions/              your captured session data (gitignored — personal content)
  <id>/screenshots/    001.png, 002.png, ...
  <id>/transcripts/    001.txt, 002.txt, ...
  <id>/audio/          001.wav, ... — source audio, kept so any segment can be re-run
screenshots/           standalone screenshot output (gitignored)
.state/                gitignored runtime area:
  queue/               pending job files
  worker.lock          flock that keeps exactly one worker alive
  kotodama.log         narrative log of everything that happened
  failures.jsonl       one structured record per failed attempt
  ratelimit.json       last observed token budget
  cooldown_until       active rate-limit hold, if any
  pending-audio/       dictation audio waiting on the queue
  failed-dictations/   dictation audio that failed, awaiting ./dictate.py retry
.env                   your Groq API key (gitignored, never commit this)
```

## Troubleshooting

**A transcript never appeared, or "Transcript N failed"**: nothing is lost. Run
`./session.py pending` to see the recording that's still owed a transcript, then
`./session.py retry`. `.state/kotodama.log` has the real reason it failed.

**"Dictation failed — network timed out"**: the script gives up after ~25s if Groq is
unreachable rather than hanging silently. Check your connection and try again.

**Whole system briefly freezes/stutters specifically while a recording is processing, and
it's worse with Bluetooth audio devices connected**: on some Intel WiFi/Bluetooth combo
chips (this was hit on an Intel 8265, likely affects other Intel combo cards too), the
firmware's WiFi/BT coexistence logic can crash under sustained network traffic while
Bluetooth is active, causing a real kernel-level stall (confirmed via `dmesg` showing
`softlockup`/`hard LOCKUP` alongside `iwlwifi ... Microcode SW error` and
`Bluetooth: ... SCO packet for unknown connection handle`). This isn't specific to this
tool — any app doing sustained network I/O while BT is active can trigger it — but
dictation is the one thing that visibly sits there waiting long enough to expose it. Fix,
if you hit this:

```sh
echo "options iwlwifi bt_coex_active=0" | sudo tee /etc/modprobe.d/iwlwifi.conf
```

Then reboot. Verify with `cat /sys/module/iwlwifi/parameters/bt_coex_active` (should read
`N` afterward).
