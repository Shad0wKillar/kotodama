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
- **Hyprland**, in either config format — the Lua config manager (`hl.bind` /
  `hl.dsp.exec_cmd`) or the classic hyprlang `hyprland.conf`. `install.sh` detects which
  one you're running and writes the matching keybindings; check for yourself with
  `hyprctl eval "return 1"` (prints `1` on the Lua config manager, or an
  "only supported with the lua config manager" error on hyprlang).
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
the keybindings in whichever format your Hyprland reads — then reloads Hyprland and warns
you about any key another bind already claims. It's safe to re-run; it skips whatever's
already done, and rewrites the keybindings so re-running after moving the project fixes
the paths.

**It will not work yet after this** — you still need to add your own Groq API key. The
script tells you this at the end and won't let you miss it; see
[Get a free Groq API key](#4-get-a-free-groq-api-key) below for how.

To remove everything it added — the keybindings (either format), the `.venv`, and
(optionally, it asks first) any system packages it installed that weren't already on your
machine — run `./uninstall.sh`. It leaves your `.env`, `sessions/`, `screenshots/`, and the project
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

Groq's free tier (as of writing) covers this comfortably for personal use: 8 hours of
audio transcription per day, and 100k tokens/day for the cleanup LLM — both reset daily,
no card on file. Verify your own limits at any time at
[console.groq.com/settings/limits](https://console.groq.com/settings/limits), since
free-tier terms can change.

## 5. Wire up the keybindings

First find out which config format your Hyprland reads:

```sh
hyprctl eval "return 1"
```

**Prints `1`** — you're on the Lua config manager. Copy
[`hyprland-keybindings.lua`](./hyprland-keybindings.lua) into your own Hyprland Lua config
(e.g. `~/.config/hypr/custom.lua`, if your setup auto-loads that — ML4W dotfiles do this
via `require("custom")`).

**Says `eval is only supported with the lua config manager`** — you're on the classic
hyprlang format, and a `custom.lua` would be read by nothing at all. Save
[`hyprland-keybindings.conf`](./hyprland-keybindings.conf) as `~/.config/hypr/kotodama.conf`
and add one line to `~/.config/hypr/hyprland.conf`:

```
source = ~/.config/hypr/kotodama.conf
```

Either way, edit the two path variables at the top to wherever you cloned this project —
they assume `~/dev/personal/kotodama`.

Then reload Hyprland's config: `hyprctl reload config-only` (or just log out/in), and
check the binds actually landed with `hyprctl binds | grep kotodama`.

Note that `Super+O` collides with a bind some setups ship by default (ML4W uses it for
`layoutmsg swapsplit`). If two binds share a key, both fire — rebind whichever you care
less about.

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
dictate.py           standalone dictation (Super+D)
screenshot.sh         standalone screenshot + annotate (Super+A)
clip-picker.sh         browse recent screenshots from clipboard history (Super+Shift+V)
session.py             session start/end, add-screenshot, split-transcript (Super+R/I/Shift+I)
session_browser.py     session picker/browser (Super+O)
lib.py                 shared: recording, Groq transcription+cleanup, clipboard, notify
sessions/              your captured session data (gitignored — personal content)
screenshots/           standalone screenshot output (gitignored)
.state/                runtime lock files / temp audio (gitignored)
.env                   your Groq API key (gitignored, never commit this)
```

## Troubleshooting

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
