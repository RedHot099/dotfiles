#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/manifest.txt"
HOME_TREE="$REPO_ROOT/home"

if [[ ! -f "$MANIFEST" ]]; then
  echo "Missing manifest: $MANIFEST" >&2
  exit 1
fi

while IFS= read -r raw || [[ -n "$raw" ]]; do
  line="${raw%%#*}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" ]] && continue

  rel="${line%/}"
  src="$HOME/$rel"
  dst="$HOME_TREE/$rel"

  if [[ ! -e "$src" ]]; then
    echo "[skip] Missing source: $src"
    continue
  fi

  if [[ -d "$src" ]]; then
    mkdir -p "$dst"
    cp -a "$src/." "$dst/"
  else
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  fi

  echo "[ok] captured $rel"
done < "$MANIFEST"

echo "Capture complete."
