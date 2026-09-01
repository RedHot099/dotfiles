#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
content_roots=(common omarchy cachy packages desktop integrations)

PYTHONPATH=lib python3 -m unittest discover -s tests -p 'test*.py'
python3 -m compileall -q lib scripts/capture-user-skills.py
PYTHONPATH=lib ./scripts/verify-schema2-parity.py

if ! command -v luac >/dev/null 2>&1; then
  echo "luac is required to verify Hyprland payloads" >&2
  exit 1
fi
while IFS= read -r -d '' lua_file; do
  luac -p "$lua_file"
done < <(find "${content_roots[@]}" -type f -name '*.lua' -print0)

if command -v shellcheck >/dev/null 2>&1; then
  mapfile -t shell_files < <(find bootstrap "${content_roots[@]}" -type f -perm -u+x -exec file {} \; | awk -F: '/shell script/{print $1}')
  shellcheck "${shell_files[@]}"
fi

if find "${content_roots[@]}" -path '*/.config/waybar*' -o -path '*/.config/mako*' -o -path '*/.config/hypr/hypridle.conf' -o -path '*/.config/hypr/hyprlock.conf' | grep -q .; then
  echo "Legacy Omarchy payload detected" >&2
  exit 1
fi

if rg --hidden -i -I -n --glob '!.git/**' '/home/kuba|1password|crash-reporter-id' "${content_roots[@]}"; then
  echo "Machine-specific path or excluded application detected" >&2
  exit 1
fi

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
printf '{"omarchy_major":4,"packages":[],"commands":[]}' >"$temporary/facts.json"

./bootstrap plan \
  --hardware generic \
  --target-home "$temporary/home" \
  --facts "$temporary/facts.json" \
  --out "$temporary/plan.json" >/dev/null

./bootstrap apply --plan "$temporary/plan.json" --simulate-system >"$temporary/first.txt"
./bootstrap apply --plan "$temporary/plan.json" --simulate-system >"$temporary/second.txt"
grep -qx 'Changed: 0' "$temporary/second.txt"
./bootstrap audit --plan "$temporary/plan.json" --facts "$temporary/facts.json" >"$temporary/audit.txt"
! grep -q '^FAIL' "$temporary/audit.txt"

./scripts/verify-todoist-integration.sh
qmllint -I /usr/share/omarchy/shell \
  omarchy/payload/notifications/.config/omarchy/plugins/kuba.notifications/components/NotificationCard.qml
rg -q 'function snoozeGoogleCalendar' omarchy/payload/notifications/.config/omarchy/plugins/kuba.notifications/Service.qml
./scripts/test-rclone-onedrive-service.sh common/payload/cloud-onedrive/.config/systemd/user/rclone-onedrive.service
./scripts/test-rclone-onedrive-service.sh common/payload/cloud-google-drive/.config/systemd/user/rclone-google-drive.service
./scripts/test-t3code-safety.sh

echo "Bootstrap verification passed."
