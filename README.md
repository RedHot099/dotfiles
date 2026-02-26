# Omarchy Dotfiles

This repository stores personal Omarchy preferences so a fresh system can be configured quickly with the same setup.

## What These Dotfiles Configure
- Hyprland configuration: `~/.config/hypr/`
- Neovim configuration: `~/.config/nvim/`
- VS Code user config:
  - `~/.config/Code/User/settings.json`
  - `~/.config/Code/User/keybindings.json`
  - `~/.config/Code/User/mcp.json`
  - `~/.config/Code/User/chatLanguageModels.json`
- VS Code runtime args: `~/.vscode/argv.json`
- Cursor/theme integration:
  - `~/.icons/default/index.theme`
  - `~/.config/environment.d/cursor.conf`
  - `~/.config/gtk-3.0/settings.ini`
  - `~/.config/gtk-4.0/settings.ini`
  - `~/.local/share/icons/Maverick Pointy Dark/`

Managed paths are defined in `manifest.txt`.

## Makefile Usage
```bash
make capture
make diff
make dry-run
make install
make bootstrap
```

- `make capture` - sync current local config into this repo
- `make diff` - compare repo state with current local state
- `make dry-run` - preview install actions
- `make install` - apply repo config to the system
- `make bootstrap` - convenience wrapper for install

Backups are created under `~/.local/state/dotfiles/backups/<timestamp>`.
