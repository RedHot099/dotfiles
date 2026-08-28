#!/usr/bin/env bash
set -euo pipefail

SERVICE_FILE="${1:-$HOME/.config/systemd/user/rclone-onedrive.service}"

if [[ ! -f "$SERVICE_FILE" ]]; then
  echo "missing service file: $SERVICE_FILE" >&2
  exit 1
fi

if rg -n '^Requisite=graphical-session\.target$' "$SERVICE_FILE" >/dev/null; then
  echo "service must not require graphical-session.target" >&2
  exit 1
fi

if ! rg -n '^After=graphical-session\.target$' "$SERVICE_FILE" >/dev/null; then
  echo "service should start after graphical-session.target when available" >&2
  exit 1
fi

if ! rg -n '^WantedBy=graphical-session\.target$' "$SERVICE_FILE" >/dev/null; then
  echo "service should be installed into graphical-session.target" >&2
  exit 1
fi

if ! rg -n '^Type=notify$' "$SERVICE_FILE" >/dev/null; then
  echo "rclone mount should notify systemd when it is ready" >&2
  exit 1
fi

if ! rg -n '^Exec(StartPre|Stop)=%h/\.local/bin/rclone-mount-helper ' "$SERVICE_FILE" >/dev/null; then
  echo "service should use the reviewed mount helper" >&2
  exit 1
fi

if rg -n '/usr/bin/(bash|sh) -[lc]' "$SERVICE_FILE" >/dev/null; then
  echo "service must not hide mount operations in a shell command" >&2
  exit 1
fi

echo "rclone onedrive service checks passed"
