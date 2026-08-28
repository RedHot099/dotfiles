#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
launcher="$repo_root/common/payload/t3code/.local/bin/t3code"
cleaner="$repo_root/common/payload/t3code/.local/bin/t3code-clean-state"

if rg -n -- '--no-sandbox|yay -S' "$launcher"; then
  echo "T3 Code launcher bypasses the package or browser sandbox" >&2
  exit 1
fi

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
mkdir -p "$temporary/home/.t3/userdata" "$temporary/outside"
touch "$temporary/outside/must-survive"

if HOME="$temporary/home" T3CODE_USERDATA_DIR="$temporary/outside" "$cleaner" --fresh-profile >/dev/null 2>&1; then
  echo "T3 Code cleaner accepted a userdata path outside the managed tree" >&2
  exit 1
fi
test -f "$temporary/outside/must-survive"

rg -q 't3code-\$UID\.lock' "$launcher"

echo "T3 Code safety checks passed."
