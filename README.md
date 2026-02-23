# Omarchy Dotfiles

Repozytorium trzyma Twoje preferencje dla bazowego Omarchy i IDE.

## Zakres
Pliki zarządzane przez `manifest.txt`:
- `~/.config/hypr/`
- `~/.config/nvim/`
- `~/.config/Code/User/settings.json`
- `~/.config/Code/User/keybindings.json`
- `~/.config/Code/User/mcp.json`
- `~/.config/Code/User/chatLanguageModels.json`
- `~/.vscode/argv.json`

## Struktura
- `home/` - docelowe pliki w układzie względem `$HOME`
- `scripts/capture.sh` - zrzut aktualnego stanu z systemu do repo
- `scripts/install.sh` - wdrożenie repo na system (z backupem)
- `scripts/diff.sh` - porównanie repo vs aktualny system

## Użycie

### 1) Zrzut aktualnego stanu
```bash
./scripts/capture.sh
```

### 2) Wdrożenie na nowym systemie
```bash
./scripts/install.sh
```

Opcje:
```bash
./scripts/install.sh --dry-run
./scripts/install.sh --no-backup
```

Backup trafia domyślnie do:
- `~/.local/state/dotfiles/backups/<timestamp>`

### 3) Sprawdzenie różnic
```bash
./scripts/diff.sh
```
