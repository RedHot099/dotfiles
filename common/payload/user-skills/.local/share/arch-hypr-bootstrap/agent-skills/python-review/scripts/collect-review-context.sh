#!/usr/bin/env bash

set -euo pipefail

base_ref="master"
head_ref="HEAD"
context_lines="3"
working_tree_mode="auto"

usage() {
  cat <<'EOF'
Usage: collect-review-context.sh [--base <ref>] [--head <ref>] [--context <n>] [--working-tree <auto|yes|no>]

Collect git review context for branch review, optionally including the current working tree.

Options:
  --base <ref>              Base branch or commit-ish. Default: master
  --head <ref>              Head branch or commit-ish. Default: HEAD
  --context <n>             Unified diff context lines. Default: 3
  --working-tree <mode>     Include local changes from the current checkout.
                            auto: include only when --head resolves to the current HEAD commit
                            yes:  require and include the current working tree
                            no:   ignore the current working tree
                            Default: auto
  --help                    Show this help text
EOF
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ $# -ge 2 ]] || fail "--base requires a value"
      base_ref="$2"
      shift 2
      ;;
    --head)
      [[ $# -ge 2 ]] || fail "--head requires a value"
      head_ref="$2"
      shift 2
      ;;
    --context)
      [[ $# -ge 2 ]] || fail "--context requires a value"
      context_lines="$2"
      shift 2
      ;;
    --working-tree)
      [[ $# -ge 2 ]] || fail "--working-tree requires a value"
      working_tree_mode="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$context_lines" =~ ^[0-9]+$ ]] || fail "--context must be a non-negative integer"
case "$working_tree_mode" in
  auto|yes|no)
    ;;
  *)
    fail "--working-tree must be one of: auto, yes, no"
    ;;
esac

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "current directory is not inside a git repository"
cd "$repo_root"

resolve_ref() {
  local candidate="$1"
  git rev-parse --verify --quiet "${candidate}^{commit}" 2>/dev/null || true
}

resolved_head="$(resolve_ref "$head_ref")"
[[ -n "$resolved_head" ]] || fail "could not resolve head ref '$head_ref'"
current_head="$(git rev-parse --verify HEAD 2>/dev/null)" || fail "could not resolve current HEAD"

resolved_base="$(resolve_ref "$base_ref")"
if [[ -z "$resolved_base" && "$base_ref" == "master" ]]; then
  fallback_base="origin/master"
  resolved_base="$(resolve_ref "$fallback_base")"
  if [[ -n "$resolved_base" ]]; then
    base_ref="$fallback_base"
  fi
fi
[[ -n "$resolved_base" ]] || fail "could not resolve base ref '$base_ref'"

merge_base="$(git merge-base "$resolved_base" "$resolved_head" 2>/dev/null)" || fail "could not compute merge-base between '$base_ref' and '$head_ref'"

include_working_tree="no"
case "$working_tree_mode" in
  no)
    include_working_tree="no"
    ;;
  auto)
    if [[ "$resolved_head" == "$current_head" ]]; then
      include_working_tree="yes"
    fi
    ;;
  yes)
    [[ "$resolved_head" == "$current_head" ]] || fail "--working-tree yes requires --head to resolve to the current HEAD commit"
    include_working_tree="yes"
    ;;
esac

print_untracked_name_status() {
  git ls-files --others --exclude-standard | while IFS= read -r path; do
    printf 'A\t%s\n' "$path"
  done
}

print_untracked_diffstat() {
  git ls-files --others --exclude-standard | while IFS= read -r path; do
    git diff --no-index --stat -- /dev/null "$path" || true
  done
}

print_untracked_diff() {
  git ls-files --others --exclude-standard | while IFS= read -r path; do
    git diff --no-index --unified="$context_lines" -- /dev/null "$path" || true
  done
}

printf '=== REVIEW_RANGE ===\n'
printf 'repo_root: %s\n' "$repo_root"
printf 'base_ref: %s\n' "$base_ref"
printf 'base_commit: %s\n' "$resolved_base"
printf 'head_ref: %s\n' "$head_ref"
printf 'head_commit: %s\n' "$resolved_head"
printf 'merge_base: %s\n' "$merge_base"
printf 'diff_range: %s...%s\n' "$base_ref" "$head_ref"
printf 'working_tree_mode: %s\n' "$working_tree_mode"
printf 'working_tree_included: %s\n' "$include_working_tree"
printf '\n'

printf '=== COMMITS ===\n'
git log --reverse --oneline --no-decorate "${merge_base}..${resolved_head}"
printf '\n'

printf '=== CHANGED_FILES ===\n'
git diff --find-renames --name-status "$merge_base" "$resolved_head"
printf '\n'

printf '=== DIFFSTAT ===\n'
git diff --find-renames --stat "$merge_base" "$resolved_head"
printf '\n'

printf '=== DIFF ===\n'
git diff --find-renames --unified="$context_lines" "$merge_base" "$resolved_head"

if [[ "$include_working_tree" == "yes" ]]; then
  printf '\n'

  printf '=== WORKTREE_STATUS ===\n'
  if git status --short | grep -q '.'; then
    git status --short
  else
    printf '(clean)\n'
  fi
  printf '\n'

  printf '=== WORKTREE_CHANGED_FILES ===\n'
  git diff --find-renames --name-status HEAD
  print_untracked_name_status
  printf '\n'

  printf '=== WORKTREE_DIFFSTAT ===\n'
  git diff --find-renames --stat HEAD
  print_untracked_diffstat
  printf '\n'

  printf '=== WORKTREE_DIFF ===\n'
  git diff --find-renames --unified="$context_lines" HEAD
  print_untracked_diff
fi
