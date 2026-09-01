#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

MARKER_BEGIN="-- BEGIN KOTODAMA KEYBINDINGS"
MARKER_END="-- END KOTODAMA KEYBINDINGS"

echo "==> Removing keybindings from Hyprland config..."
CUSTOM_LUA="$HOME/.config/hypr/custom.lua"
if [ -f "$CUSTOM_LUA" ] && grep -q "$MARKER_BEGIN" "$CUSTOM_LUA"; then
    sed -i "/$MARKER_BEGIN/,/$MARKER_END/d" "$CUSTOM_LUA"
    echo "Removed keybindings block from $CUSTOM_LUA"
else
    echo "No keybindings block found in $CUSTOM_LUA (already removed, or never installed by install.sh)."
fi

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
