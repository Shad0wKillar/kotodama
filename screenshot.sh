#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$DIR/screenshots"
mkdir -p "$OUT_DIR"

OUT_PATH="${1:-$OUT_DIR/%Y%m%d-%H%M%S.png}"

REGION="$(slurp)" || exit 0
[ -z "$REGION" ] && exit 0

grim -g "$REGION" - | satty \
  --filename - \
  --output-filename "$OUT_PATH" \
  --copy-command wl-copy \
  --actions-on-enter save-to-clipboard,save-to-file,exit \
  --actions-on-escape exit \
  --initial-tool brush \
  --fullscreen current-screen
