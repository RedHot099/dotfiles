#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

export PYTHONDONTWRITEBYTECODE=1
cd "$repo_root"

./bootstrap plan --out "$temporary/plan.json" >"$temporary/plan.txt"

snapshot() {
  local output="$1"
  python3 - "$temporary/plan.json" >"$output" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

plan = json.load(open(sys.argv[1]))
home = Path(plan["target_home"])
rows = []
for action in plan["actions"]:
    data = action["data"]
    if action["kind"] in {"user-file", "generated-file", "managed-fragment"}:
        path = home / data["target"]
        if path.is_symlink():
            value = "link:" + os.readlink(path)
        elif path.is_file():
            value = "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            value = "missing"
        rows.append(("file", data["target"], value))
    elif action["kind"] == "pinned-git":
        path = home / data["target"]
        result = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1", "--branch"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rows.append(("git", data["target"], result.stdout if result.returncode == 0 else "missing"))
packages = subprocess.run(["pacman", "-Qq"], check=True, text=True, stdout=subprocess.PIPE).stdout
units = subprocess.run(["systemctl", "--user", "list-unit-files", "--state=enabled", "--no-legend"], check=True, text=True, stdout=subprocess.PIPE).stdout
rows.extend((("packages", "pacman", hashlib.sha256(packages.encode()).hexdigest()), ("units", "systemd-user", hashlib.sha256(units.encode()).hexdigest())))
print(json.dumps(rows, sort_keys=True, separators=(",", ":")))
PY
  git status --porcelain=v1 >>"$output"
}

snapshot "$temporary/before"
set +e
./bootstrap audit --plan "$temporary/plan.json" >"$temporary/audit.txt"
audit_status=$?
set -e
snapshot "$temporary/after"

cmp "$temporary/before" "$temporary/after"
cat "$temporary/plan.txt"
cat "$temporary/audit.txt"
printf 'Audit exit status: %s\n' "$audit_status"
echo "Read-only host verification passed."
