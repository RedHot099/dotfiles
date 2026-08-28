#!/usr/bin/env bash

set -euo pipefail

context_lines="3"

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

resolve_ref() {
  local candidate="$1"
  git rev-parse --verify --quiet "${candidate}^{commit}" 2>/dev/null || true
}

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

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "current directory is not inside a git repository"
cd "$repo_root"

base_ref="master"
base_commit="$(resolve_ref "$base_ref")"
if [[ -z "$base_commit" ]]; then
  base_ref="origin/master"
  base_commit="$(resolve_ref "$base_ref")"
fi
[[ -n "$base_commit" ]] || fail "could not resolve base ref 'master' or fallback 'origin/master'"

head_ref="HEAD"
head_commit="$(resolve_ref "$head_ref")"
[[ -n "$head_commit" ]] || fail "could not resolve current HEAD"

merge_base="$(git merge-base "$base_commit" "$head_commit" 2>/dev/null)" || fail "could not compute merge-base between '$base_ref' and HEAD"
branch_name="$(git branch --show-current)"
if [[ -z "$branch_name" ]]; then
  branch_name="detached@$(git rev-parse --short "$head_commit")"
fi

printf '=== JIRA_TASK_RANGE ===\n'
printf 'repo_root: %s\n' "$repo_root"
printf 'base_ref: %s\n' "$base_ref"
printf 'base_commit: %s\n' "$base_commit"
printf 'head_ref: %s\n' "$head_ref"
printf 'head_commit: %s\n' "$head_commit"
printf 'merge_base: %s\n' "$merge_base"
printf 'diff_range: %s...HEAD\n' "$base_ref"
printf 'working_tree_included: yes\n'
printf '\n'

printf '=== BRANCH ===\n'
printf '%s\n' "$branch_name"
printf '\n'

printf '=== COMMITS ===\n'
git log --reverse --oneline --no-decorate "${merge_base}..${head_commit}"
printf '\n'

printf '=== CHANGED_FILES ===\n'
git diff --find-renames --name-status "$merge_base" "$head_commit"
printf '\n'

printf '=== DIFFSTAT ===\n'
git diff --find-renames --stat "$merge_base" "$head_commit"
printf '\n'

printf '=== DIFF ===\n'
git diff --find-renames --unified="$context_lines" "$merge_base" "$head_commit"
printf '\n'

printf '=== WORKTREE_STATUS ===\n'
worktree_status="$(git status --short)"
if [[ -n "$worktree_status" ]]; then
  printf '%s\n' "$worktree_status"
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
