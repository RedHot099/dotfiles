# Omarchy Dotfiles

This repository stores your personal Omarchy and IDE preferences so you can quickly reproduce your setup on a fresh system.

## Scope
Managed by `manifest.txt`:
- `~/.config/hypr/`
- `~/.config/nvim/`
- `~/.config/Code/User/settings.json`
- `~/.config/Code/User/keybindings.json`
- `~/.config/Code/User/mcp.json`
- `~/.config/Code/User/chatLanguageModels.json`
- `~/.vscode/argv.json`

## Repository Layout
- `home/` - files mirrored in `$HOME`-relative structure
- `scripts/capture.sh` - capture current local config into this repo
- `scripts/install.sh` - apply repo config to local system (with backups)
- `scripts/diff.sh` - compare repo state vs current local state
- `scripts/bootstrap-omarchy.sh` - convenience wrapper for install

## Usage

### 1) Capture current setup
```bash
./scripts/capture.sh
```

### 2) Apply setup on a new system
```bash
./scripts/install.sh
```

Options:
```bash
./scripts/install.sh --dry-run
./scripts/install.sh --no-backup
```

Backups are stored by default in:
- `~/.local/state/dotfiles/backups/<timestamp>`

### 3) Check differences
```bash
./scripts/diff.sh
```

## Makefile shortcuts
```bash
make capture
make diff
make dry-run
make install
make bootstrap
```
