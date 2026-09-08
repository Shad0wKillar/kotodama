#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

HYPR_DIR="$HOME/.config/hypr"
CUSTOM_LUA="$HYPR_DIR/custom.lua"
HYPRLAND_CONF="$HYPR_DIR/hyprland.conf"
KOTODAMA_CONF="$HYPR_DIR/kotodama.conf"

LUA_BEGIN="-- BEGIN KOTODAMA KEYBINDINGS"
LUA_END="-- END KOTODAMA KEYBINDINGS"
CONF_BEGIN="# BEGIN KOTODAMA KEYBINDINGS"
CONF_END="# END KOTODAMA KEYBINDINGS"

strip_block() { # <file> <begin marker> <end marker>
    [ -f "$1" ] || return 1
    # -e and -- are load-bearing: the Lua markers start with "--", which grep and
    # sed would otherwise parse as an option and bail out.
    grep -qF -e "$2" -- "$1" || return 1
    sed -i "\|$2|,\|$3|d" "$1"
}

echo "==> Removing keybindings from Hyprland config..."
# Scan both formats rather than trusting a record of which one install.sh chose —
# the project may have been installed under a config that has since changed.
REMOVED=0
if strip_block "$CUSTOM_LUA" "$LUA_BEGIN" "$LUA_END"; then
    echo "Removed Lua keybindings block from $CUSTOM_LUA"
    REMOVED=1
fi
if strip_block "$HYPRLAND_CONF" "$CONF_BEGIN" "$CONF_END"; then
    echo "Removed keybindings block from $HYPRLAND_CONF"
    REMOVED=1
fi
if [ -f "$KOTODAMA_CONF" ]; then
    rm -f "$KOTODAMA_CONF"
    echo "Removed $KOTODAMA_CONF"
    REMOVED=1
fi
[ "$REMOVED" -eq 0 ] && echo "No kotodama keybindings found (already removed, or never installed by install.sh)."

if command -v hyprctl &>/dev/null; then
    hyprctl reload config-only &>/dev/null && echo "Reloaded Hyprland config." || true
fi

echo "==> Removing Python virtual environment..."
if [ -d .venv ]; then
    rm -rf .venv
    echo "Removed .venv/"
else
    echo "No .venv/ found."
fi

echo "==> System packages"
if [ -f .state/installed-packages.txt ] && [ -s .state/installed-packages.txt ]; then
    mapfile -t PKGS < .state/installed-packages.txt
    echo "install.sh added these packages that weren't on your system before:"
    printf '  - %s\n' "${PKGS[@]}"
    read -r -p "Remove them now with pacman? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        sudo pacman -Rns --noconfirm "${PKGS[@]}"
        echo "Removed."
        rm -f .state/installed-packages.txt
    else
        echo "Left installed."
    fi
else
    echo "No record of packages install.sh added (or none were needed) — nothing to remove."
fi

echo ""
echo "==> Uninstall complete."
echo "Left untouched: .env (your API key), sessions/, screenshots/, and this"
echo "project folder itself ($DIR)."
echo "Delete that folder yourself if you want it fully gone."
