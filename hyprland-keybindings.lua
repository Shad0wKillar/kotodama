-- Kotodama dictation + screenshot tools keybindings — Lua config manager version.
--
-- Only for Hyprland running the Lua config manager (`hyprctl eval "return 1"`
-- prints 1). If it instead says "eval is only supported with the lua config
-- manager", use hyprland-keybindings.conf.
--
-- Copy this block into your own ~/.config/hypr/custom.lua (or wherever your
-- Hyprland Lua config loads user binds from). Assumes this project lives at
-- ~/dev/personal/kotodama — adjust kotodamaDir below if you put it elsewhere.

local mainMod = "SUPER"
local kotodamaDir = os.getenv("HOME") .. "/dev/personal/kotodama"
local kotodamaPy = kotodamaDir .. "/.venv/bin/python"

-- Commands go through the shell, so quote every path: without this a project
-- directory containing a space silently breaks every bind below.
local function q(s) return '"' .. s .. '"' end
local function script(name) return q(kotodamaDir .. "/" .. name) end
local function py(name) return q(kotodamaPy) .. " " .. script(name) end

hl.bind(mainMod .. " + D", hl.dsp.exec_cmd(py("dictate.py") .. " toggle"), { description = "Dictation: record / transcribe to clipboard" })
hl.bind(mainMod .. " + A", hl.dsp.exec_cmd(script("screenshot.sh")), { description = "Screenshot: annotate and copy" })
hl.bind(mainMod .. " + SHIFT + V", hl.dsp.exec_cmd(script("clip-picker.sh")), { description = "Browse recent screenshots (clipboard history)" })

hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(py("session.py") .. " toggle"), { description = "Session: start / end (record + screenshot)" })
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd(py("session.py") .. " screenshot"), { description = "Session: add screenshot" })
hl.bind(mainMod .. " + SHIFT + I", hl.dsp.exec_cmd(py("session.py") .. " split"), { description = "Session: split transcript segment" })
hl.bind(mainMod .. " + O", hl.dsp.exec_cmd(py("session_browser.py")), { description = "Session: browse and copy" })
