#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper="$HOME/.local/bin/omarchy-todoist"
td_bin="$(command -v td)"
task_id=""
deleted=false

cleanup() {
  if [[ -n "$task_id" && "$deleted" == false ]]; then
    "$td_bin" task delete "id:$task_id" --yes >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

request() {
  local payload="$1"
  local response
  response="$($helper request "$payload")"
  jq -e '.ok == true' >/dev/null <<<"$response"
  printf '%s' "$response"
}

quick_payload="$(jq -nc '{version:1,requestId:"live-create",operation:"quickAdd",content:"[Omarchy integration test]"}')"
quick_response="$(request "$quick_payload")"
task_id="$(jq -r '.operation.createdTaskId // empty' <<<"$quick_response")"
[[ -n "$task_id" ]] || { echo "Todoist did not return the created task id." >&2; exit 1; }

tomorrow="$(date -d tomorrow +%F)"
request "$(jq -nc --arg id "$task_id" --arg due "$tomorrow" '{version:1,requestId:"live-due",operation:"setDue",taskId:$id,due:$due}')" >/dev/null
request "$(jq -nc --arg id "$task_id" '{version:1,requestId:"live-priority",operation:"setPriority",taskId:$id,priority:"p1"}')" >/dev/null

task_view="$($td_bin task view "id:$task_id" --json --full)"
jq -e --arg due "$tomorrow" '
  (.due.date | startswith($due)) and
  ((.priority == "p1") or (.priority == 4))
' >/dev/null <<<"$task_view"

request "$(jq -nc --arg id "$task_id" '{version:1,requestId:"live-complete",operation:"complete",taskId:$id}')" >/dev/null
request "$(jq -nc --arg id "$task_id" '{version:1,requestId:"live-reopen",operation:"reopen",taskId:$id}')" >/dev/null

reopened="$($td_bin task view "id:$task_id" --json --full)"
jq -e '.isCompleted == false or .checked == false or (.completedAt == null)' >/dev/null <<<"$reopened"

"$td_bin" task delete "id:$task_id" --yes >/dev/null
deleted=true
"$helper" snapshot >/dev/null

echo "Live Todoist round-trip passed; the exact test task was deleted."
