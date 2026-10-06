# Arch Hyprland bootstrap

This repository configures a fresh Omarchy 4 installation. It performs initial setup only; use `omarchy update` afterward.

## Run setup

```bash
git clone <repository-url> ~/dotfiles
cd ~/dotfiles
./bootstrap setup
```

The English terminal interface uses arrows or `j`/`k` to move, Space to toggle an application or group, `a` and `n` to select or clear visible entries, `/` to search, and Enter to continue.

Setup runs three independent workflows in order:

1. Packages installs selected applications and exact runtime tools.
2. Desktop configures the monitor, Hyprland, Omarchy Shell, workspaces, shortcuts, themes, startup, and Calendar.
3. Integrations configures AI agents, skills, cloud mounts, Todoist, GitHub SSH access, Tailscale, and firewall rules, then runs the login queue.

Run a workflow separately when needed:

```bash
./bootstrap packages plan
./bootstrap packages apply
./bootstrap packages audit
./bootstrap desktop plan
./bootstrap desktop apply
./bootstrap desktop audit
./bootstrap integrations plan
./bootstrap integrations apply
./bootstrap integrations audit
```

`plan` is read-only except for private plan and selection state. `apply` requires an interactive terminal and explicit confirmation. `audit` does not mutate the machine.

## Safety

Repository packages are resolved into one reviewed transaction. AUR packages are pinned to a full commit, their recipes are recorded in the plan, and each recipe is reviewed before an unprivileged build. Only verified local artifacts reach `sudo pacman -U`.

The bootstrap never runs `pacman -Sy`, changes repository configuration, deletes the Pacman lock, uses `--noconfirm`, installs an AUR helper, rolls packages back, or performs a distribution update.

Desktop keeps the Google Calendar Snooze and Todoist widgets and does not install Waybar, Mako, or another idle or lock daemon. Desktop apply reloads an active Hyprland session and fails when `hyprctl configerrors` reports an error.

## Agents, skills, and credentials

The curated agents are Claude Code, Codex, OpenCode, and Cursor Agent. Skills are selected once and linked from one managed canonical tree into `.agents`, Claude, Codex, OpenCode, and Cursor harness roots. Codex `.system`, Cursor `skills-cursor`, and unrelated non-colliding skills remain untouched.

The repository stores no tokens, sessions, browser profiles, rclone configuration, private SSH keys, host fingerprints, or `known_hosts` entries.

The login queue asks before each login, in this order: an SSH key (created with `ssh-keygen` if `~/.ssh/id_ed25519` is missing), GitHub (`gh auth login` with SSH, which uploads the key), and Bitbucket (copies the key and opens the Bitbucket SSH key page). Then come the AI agents, AWS CLI, Docker Hub, 1Password, Tailscale, Google Drive, OneDrive, and Todoist. A declined, cancelled, or failed login stays in the queue and the workflow reports `INCOMPLETE`; run `./bootstrap integrations apply` again to retry it.

Selections, digest-addressed plans, journals, and the global apply lock live under `~/.local/state/arch-hypr-bootstrap/`.

## Repository layout

```text
packages/{common,omarchy}/       Applications and package bindings
desktop/{common,omarchy}/        Hyprland, shell, monitor, and Calendar
integrations/{common,omarchy}/   Agents, skills, cloud, Todoist, and access
lib/bootstrap/                   Compiler, planners, TUI, executor, and audit
scripts/                         Maintenance and verification tools
tests/                           Unit and isolated integration checks
```

Run `./scripts/verify-bootstrap.sh` before committing.
