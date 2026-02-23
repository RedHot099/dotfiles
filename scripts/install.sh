#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/manifest.txt"
HOME_TREE="$REPO_ROOT/home"

DRY_RUN=false
NO_BACKUP=false
BACKUP_ROOT="${DOTFILES_BACKUP_DIR:-$HOME/.local/state/dotfiles/backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
BACKUP_CREATED=false

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [--no-backup]

Options:
  --dry-run    Show actions without writing files
  --no-backup  Skip backups before overwriting
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --no-backup) NO_BACKUP=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

if [[ ! -f "$MANIFEST" ]]; then
  echo "Missing manifest: $MANIFEST" >&2
  exit 1
fi

copy_with_backup() {
  local src="$1"
  local dst="$2"

  if [[ ! -e "$src" ]]; then
    echo "[skip] Missing source: $src"
    return 0
  fi

  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] apply $src -> $dst"
    return 0
  fi

  if [[ "$NO_BACKUP" == false && -e "$dst" ]]; then
    local rel="${dst#$HOME/}"
    local backup_path="$BACKUP_DIR/$rel"
    mkdir -p "$(dirname "$backup_path")"

    if [[ -d "$dst" ]]; then
      cp -a "$dst" "$backup_path"
    else
      cp -a "$dst" "$backup_path"
    fi

    BACKUP_CREATED=true
  fi

  if [[ -d "$src" ]]; then
    mkdir -p "$dst"
    cp -a "$src/." "$dst/"
  else
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  fi

  echo "[ok] $dst"
}

while IFS= read -r raw || [[ -n "$raw" ]]; do
  line="${raw%%#*}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" ]] && continue

  rel="${line%/}"
  src="$HOME_TREE/$rel"
  dst="$HOME/$rel"
  copy_with_backup "$src" "$dst"
done < "$MANIFEST"

if [[ "$DRY_RUN" == false ]]; then
  if [[ "$NO_BACKUP" == false && "$BACKUP_CREATED" == true ]]; then
    echo "Backup created in: $BACKUP_DIR"
  fi

  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload >/dev/null 2>&1 || true
  fi
fi

echo "Done."
