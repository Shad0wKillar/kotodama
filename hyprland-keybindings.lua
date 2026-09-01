-- Kotodama dictation + screenshot tools keybindings.
--
-- Copy this block into your own ~/.config/hypr/custom.lua (or wherever your
-- Hyprland Lua config loads user binds from). Assumes this project lives at
-- ~/dev/personal/kotodama — adjust kotodamaDir below if you put it elsewhere.

local mainMod = "SUPER"
local kotodamaDir = os.getenv("HOME") .. "/dev/personal/kotodama"
local kotodamaPy = kotodamaDir .. "/.venv/bin/python"

hl.bind(mainMod .. " + D", hl.dsp.exec_cmd(kotodamaPy .. " " .. kotodamaDir .. "/dictate.py toggle"), { description = "Dictation: record / transcribe to clipboard" })
hl.bind(mainMod .. " + A", hl.dsp.exec_cmd(kotodamaDir .. "/screenshot.sh"), { description = "Screenshot: annotate and copy" })
hl.bind(mainMod .. " + SHIFT + V", hl.dsp.exec_cmd(kotodamaDir .. "/clip-picker.sh"), { description = "Browse recent screenshots (clipboard history)" })

hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(kotodamaPy .. " " .. kotodamaDir .. "/session.py toggle"), { description = "Session: start / end (record + screenshot)" })
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd(kotodamaPy .. " " .. kotodamaDir .. "/session.py screenshot"), { description = "Session: add screenshot" })
hl.bind(mainMod .. " + SHIFT + I", hl.dsp.exec_cmd(kotodamaPy .. " " .. kotodamaDir .. "/session.py split"), { description = "Session: split transcript segment" })
hl.bind(mainMod .. " + O", hl.dsp.exec_cmd(kotodamaPy .. " " .. kotodamaDir .. "/session_browser.py"), { description = "Session: browse and copy" })
