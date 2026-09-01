#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$DIR/.state/clip-thumbs"
mkdir -p "$TMP"
rm -f "$TMP"/*.png 2>/dev/null || true

files=()
while IFS= read -r line; do
    [[ "$line" == *"binary data"*"png"* || "$line" == *"binary data"*"jpg"* || "$line" == *"binary data"*"jpeg"* ]] || continue
    id="${line%%$'\t'*}"
    thumb="$TMP/$id.png"
    printf '%s\n' "$line" | cliphist decode > "$thumb" 2>/dev/null || true
    [ -s "$thumb" ] && files+=("$thumb")
done < <(cliphist list)

if [ ${#files[@]} -eq 0 ]; then
    notify-send "Clipboard" "No images found."
    exit 0
fi

imv -f \
    -c 'bind <Return> exec wl-copy < "$imv_current_file" && notify-send "Copied to clipboard" "Image $imv_current_index of $imv_file_count"' \
    "${files[@]}"
