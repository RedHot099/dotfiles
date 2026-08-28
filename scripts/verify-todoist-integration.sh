#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_dir="$repo_root/omarchy/payload/todoist/.config/omarchy/plugins/kuba.tasks"
helper="$repo_root/common/payload/todoist-helper/.local/bin/todoist-helper"
live=false

if [[ "${1:-}" == "--live" ]]; then
  live=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $(basename "$0") [--live]" >&2
  exit 2
fi

python3 -m json.tool "$plugin_dir/manifest.json" >/dev/null
python3 -m json.tool "$repo_root/omarchy/payload/core-desktop/.config/omarchy/shell.json" >/dev/null
test -x "$helper"

python3 - "$repo_root/omarchy/payload/core-desktop/.config/omarchy/shell.json" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1], encoding="utf-8"))
right = [entry["id"] for entry in config["bar"]["layout"]["right"]]
agents = right.index("omarchy.agents")
assert right[agents + 1] == "kuba.tasks", right
assert right.count("kuba.tasks") == 1, right
PY

qmllint -I /usr/share/omarchy/shell \
  "$plugin_dir/Panel.qml" \
  "$plugin_dir/Service.qml" \
  "$plugin_dir/TaskView.js"

if rg -n 'Qt\.callLater' "$plugin_dir/Panel.qml" "$plugin_dir/Service.qml"; then
  echo "Todoist plugin must not queue callbacks that outlive a hot reload." >&2
  exit 1
fi

if rg -n 'visible:[[:space:]]*entryField\.visible' "$plugin_dir/Panel.qml"; then
  echo "Todoist text editor visibility must depend on editor mode, not its hidden child." >&2
  exit 1
fi

python3 -m unittest -v tests.test_omarchy_todoist
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner \
  -input "$repo_root/tests/qml" \
  -import /usr/share/omarchy/shell \
  -o -,txt

if [[ "$live" == true ]]; then
  "$helper" doctor
  test -x "$HOME/.local/bin/todoist-helper"
  test -f "$HOME/.config/omarchy/plugins/kuba.tasks/Panel.qml"
  python3 - "$HOME/.config/omarchy/shell.json" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1], encoding="utf-8"))
right = [entry["id"] for entry in config["bar"]["layout"]["right"]]
assert right[right.index("omarchy.agents") + 1] == "kuba.tasks", right
PY
fi

echo "Todoist integration verification passed."
