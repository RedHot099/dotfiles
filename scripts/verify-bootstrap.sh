#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
content_roots=(packages desktop integrations)

PYTHONPATH=lib python3 -m unittest discover -s tests -p 'test*.py'
python3 -m compileall -q lib scripts/capture-user-skills.py

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

if rg --hidden -i -I -n --glob '!.git/**' '/home/kuba|crash-reporter-id' "${content_roots[@]}"; then
  echo "Machine-specific path detected" >&2
  exit 1
fi

# The login queue may open 1Password, but no 1Password data or settings ship.
if find "${content_roots[@]}" -ipath '*1password*' ! -path 'integrations/common/*/1password.toml' | grep .; then
  echo "1Password files detected" >&2
  exit 1
fi

PYTHONPATH=lib python3 - <<'PY'
from pathlib import Path
from bootstrap.domain import PlatformId
from bootstrap.repository import compile_repository

compile_repository(Path.cwd(), PlatformId.OMARCHY)
print("Workflow repository compiles.")
PY

./scripts/verify-todoist-integration.sh
qmllint -I /usr/share/omarchy/shell \
  desktop/omarchy/payload/notifications/.config/omarchy/plugins/kuba.notifications/components/NotificationCard.qml \
  desktop/omarchy/payload/core-desktop/.config/omarchy/plugins/bar-orientation/Service.qml \
  desktop/omarchy/payload/core-desktop/.config/omarchy/plugins/bar-orientation-tray/Tray.qml
rg -q 'function snoozeGoogleCalendar' desktop/omarchy/payload/notifications/.config/omarchy/plugins/kuba.notifications/Service.qml
./scripts/test-rclone-onedrive-service.sh integrations/common/payload/cloud-onedrive/.config/systemd/user/rclone-onedrive.service
./scripts/test-rclone-onedrive-service.sh integrations/common/payload/cloud-google-drive/.config/systemd/user/rclone-google-drive.service
./scripts/test-t3code-safety.sh

echo "Bootstrap verification passed."
