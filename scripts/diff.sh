#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/manifest.txt"
HOME_TREE="$REPO_ROOT/home"

changes=0

while IFS= read -r raw || [[ -n "$raw" ]]; do
  line="${raw%%#*}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" ]] && continue

  rel="${line%/}"
  local_path="$HOME/$rel"
  repo_path="$HOME_TREE/$rel"

  if [[ ! -e "$repo_path" && ! -e "$local_path" ]]; then
    continue
  fi

  echo "===== $rel ====="
  if [[ -d "$repo_path" || -d "$local_path" ]]; then
    diff -ru "$repo_path" "$local_path" || changes=1
  else
    diff -u "$repo_path" "$local_path" || changes=1
  fi
  echo
done < "$MANIFEST"

if [[ $changes -eq 0 ]]; then
  echo "No differences."
fi
