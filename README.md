# Arch Hyprland bootstrap

This repository configures a fresh Hyprland desktop on either Omarchy 4 or the supported CachyOS Noctalia image. One catalog defines the choices. Separate platform trees implement the desktop-specific behavior.

The bootstrap installs and configures the selected state once. Use `omarchy update` on Omarchy or the supported full-system update workflow on CachyOS for later updates.

## Run the interactive setup

Clone the repository on the target machine. Run:

```bash
./bootstrap
```

The English terminal wizard detects the platform, monitor, and installed programs. It labels choices as repository, AUR, or mise sources. Use the keyboard to choose the programs to install.

The default selection contains `core-desktop` and `ai-development`. The known ultrawide NVIDIA profile also selects `session-autostart`.

## Review and apply a plan

Create a plan without changing the target home, packages, or services:

```bash
./bootstrap plan --out .bootstrap/plan.json
```

Planning can read package metadata and fetch pinned AUR recipes. It writes only the requested plan file.

Review the plan, then apply it:

```bash
./bootstrap apply --plan .bootstrap/plan.json
```

Apply rejects a plan when the platform, home, repository configuration, workspace content, package source, package version, or AUR recipe has changed. Each AUR recipe receives a separate terminal review and approval before its unprivileged build.

Audit the selected state without changing it:

```bash
./bootstrap audit --plan .bootstrap/plan.json
```

`PASS` means that the selected state matches. `WARN` identifies a manual login, an unavailable platform feature, or a simulated system action. `FAIL` identifies drift on the target machine.

## Select profiles and features

Profiles select related top-level features. Dependencies remain hidden in the catalog.

```bash
./bootstrap plan \
  --profile communication-media \
  --profile research \
  --select cloud.onedrive \
  --select cloud.google-drive
```

The repository provides these profiles:

- `core-desktop`
- `ai-development`
- `communication-media`
- `gaming`
- `research`
- `cloud`

Run `./bootstrap plan --help` for monitor, agent, target-home, and fixture options.

## Supported platforms

Omarchy support targets major version 4. The Omarchy implementation retains the Todoist widget, the Google Calendar notification behavior, and the three pinned themes.

CachyOS support targets the current `cachyos-hypr-noctalia` desktop contract:

- Hyprland 0.55 or 0.56
- UWSM 0.24 or newer, below 1.0
- Noctalia major version 5

The Cachy implementation installs native `hl.*` Lua overrides, six persistent workspaces, monitor settings, UWSM environment files, and session units. It preserves the CachyOS-owned Hyprland root and inserts one managed `require()` block.

Three Cachy features report an explicit `WARN` instead of claiming parity:

- the Todoist bar plugin, because the Noctalia v5 plugin API is still beta;
- Akane, All Hallows Eve, and Void themes, because their Noctalia palettes and merged-state behavior are not validated;
- Google Calendar Snooze, because a compatible Freedesktop notification action has not been captured.

The automated gate verifies the Cachy payload in an isolated home. A real CachyOS graphical-session test is still required before treating the Cachy path as production-validated.

## Packages and AUR safety

Each platform maps stable package requirements to an allowlisted repository or an exact AUR commit.

For repository packages, planning records the resolved repository, version, and transaction members. Apply resolves the transaction again and stops when it differs. The bootstrap never runs `pacman -Sy`, never changes `pacman.conf`, never deletes `db.lck`, and never passes `--noconfirm` or package-integrity bypasses.

For AUR packages, planning stores every tracked recipe file and its SHA-256 digest. Apply displays those files, asks for approval, checks out the exact commit again, and builds as the target user with a clean environment. Only the resulting local package crosses the `sudo pacman -U` boundary. The bootstrap does not install or use `yay` or `paru`.

The bootstrap does not roll back packages. Pacman and rolling-release dependencies make blind downgrade unsafe.

## Hardware and desktop configuration

The `desktop-ultrawide-nvidia` profile configures the Microstep MAG 341C OLED at 3440x1440 and about 175 Hz. For an unknown display, provide monitor arguments to `plan` or use the interactive wizard.

The generated monitor configuration is part of the plan. The repository does not commit detected hardware automatically.

## Agents and skills

The default AI profile installs Claude, Codex, OpenCode, GitHub CLI, the selected editors, Node, Python, and the reviewed skill tree. Optional choices include Gemini, Grok, Crush, GitHub Copilot, and Cursor Agent. All mise selectors use exact versions.

The repository stores 83 reviewed user-owned skills in one canonical tree. Relative links expose the same content to the supported agents. The capture tool excludes packaged skills, Codex system skills, caches, sessions, histories, and secret-like files.

Authentication remains manual. The repository stores no tokens and has no 1Password integration.

## SSH and cloud storage

Remote SSH access is optional. Planning fetches the public GitHub keys, displays their fingerprints, and stores the approved key bytes in the plan. Apply installs OpenSSH, merges the keys into `authorized_keys`, validates the server configuration, and enables `sshd.service`. The UFW rule is a separate opt-in feature.

OneDrive and Google Drive are separate rclone choices. Their user units start with the graphical session and activate only after the named local remote exists. The reviewed mount helper validates paths and unmounts only the exact mount target.

## File safety and state

User-file writes use descriptor-based path checks, random staging names, atomic replacement, and `fsync`. The executor rejects parent symlinks and escaping relative links.

The per-user lock, journals, and backups live under:

```text
~/.local/state/arch-hypr-bootstrap/
```

Backups cover files owned by the bootstrap. They do not claim to restore package transactions or arbitrary distribution state.

The repository treats `/usr/share/omarchy`, `/etc/skel`, package repositories, mirror lists, and keyrings as read-only inputs.

## Verify changes

Run the required gate:

```bash
./scripts/verify-bootstrap.sh
```

The gate runs Python tests, schema-1 parity checks, Lua and shell syntax checks, isolated apply twice for idempotence, read-only audit, Todoist and QML tests, rclone unit checks, and T3 Code safety checks.

## Repository layout

```text
bootstrap                  Public command
lib/bootstrap/             Domain, platform detection, planner, executor, and audit
common/catalog/            Public features and profiles
common/implementations/    Portable feature implementations
common/payload/            Portable user-owned files
omarchy/                   Omarchy package bindings, implementations, and payload
cachy/                     Cachy package bindings, implementations, and payload
scripts/                   Capture, maintenance, and verification tools
tests/                     Level 1 and isolated level 2 checks
```

Use `scripts/refresh-theme-pins.py` only to review upstream Omarchy theme commits during repository maintenance. It does not update an installed system.
