# Omarchy 4 bootstrap

This repository configures a fresh, updated Omarchy 4 installation. It installs selected applications, applies user-owned configuration, restores agent skills, and verifies the result. Later system updates remain the responsibility of `omarchy update`.

## Run the interactive setup

Clone the repository on a fresh Omarchy 4 machine, then run:

```bash
./bootstrap
```

The English terminal wizard detects the monitor and installed programs. It marks installed choices, keeps required dependencies selected, and lets you choose optional applications with the keyboard. Installed optional applications are not selected automatically.

The default selection contains `core-desktop` and `ai-development`. `core-desktop` explicitly includes the Todoist widget, calendar notification behavior, and pinned themes. The current ultrawide NVIDIA profile also selects `session-autostart`.

## Review a plan before applying it

Create a plan without changing system configuration:

```bash
./bootstrap plan --out .bootstrap/plan.json
```

Apply the reviewed plan:

```bash
./bootstrap apply --plan .bootstrap/plan.json
```

Audit the selected state without writing files, installing packages, or changing services:

```bash
./bootstrap audit --plan .bootstrap/plan.json
```

`audit` prints `PASS`, `WARN`, or `FAIL`. It returns a nonzero status when any finding is `FAIL`.

The `plan` command writes the requested JSON plan (by default `.bootstrap/plan.json`) but does not change `$HOME`, packages, or services. `audit` does not write through the bootstrap; authentication status commands may read credential stores and, depending on the third-party CLI, contact its service.

## Select profiles and applications without the wizard

Profiles select related top-level applications. Dependencies remain internal to the catalog.

```bash
./bootstrap plan \
  --profile communication-media \
  --profile research \
  --select cloud.onedrive \
  --select cloud.google-drive
```

Available profiles are:

- `core-desktop`, selected by default.
- `ai-development`, selected by default.
- `communication-media`.
- `gaming`.
- `research`.
- `cloud`.

Run `./bootstrap plan --help` for monitor, agent, target-home, and fixture options.

## Hardware behavior

The known `desktop-ultrawide-nvidia` profile configures the Microstep MAG 341C OLED at 3440x1440 and about 175 Hz. Unknown monitors open a wizard for the primary output, mode, scale, and position. The generated monitor configuration belongs to the plan and is never committed automatically.

## Agents and skills

The AI profile installs Claude, Codex, and OpenCode. The wizard asks which one Omarchy should use by default. Optional agent entries cover Gemini, Grok, Crush, GitHub Copilot, and Cursor Agent.

The repository stores 83 reviewed user-owned skills in one canonical tree. Relative symlinks expose the same tree to Claude, Codex, and OpenCode. The capture tool excludes Omarchy-provided skills, Codex system skills, caches, sessions, histories, and secret-like files.

Authentication remains manual. The bootstrap runs official login commands and stores no tokens. It has no 1Password integration.

## Cloud storage

OneDrive and Google Drive are independent choices. Both use rclone. The bootstrap installs the unit files but enables a mount only after its remote passes the authentication probe.

## Safety

File writes use atomic replacement. Existing target files receive a per-plan backup under:

```text
~/.local/state/omarchy-bootstrap/backups/<plan-digest>/
```

Completed work is journaled under `~/.local/state/omarchy-bootstrap/`. A failed action offers `Retry`, `Skip feature`, or `Abort`. Skipping a feature also skips features that depend on it.

The repository never writes `/usr/share/omarchy`. It carries only user-owned overrides and justified shell plugins.

The bootstrap targets a freshly updated Omarchy 4 system. Pacman/AUR packages and agent CLIs marked `@latest` intentionally resolve when the plan is applied, so they follow the current Omarchy repositories rather than recreating an old package snapshot. Major development runtimes and theme repository commits are pinned where configuration compatibility depends on them.

## Verify changes

Run the complete offline and temporary-home checks:

```bash
./scripts/verify-bootstrap.sh
```

The check covers dependency resolution, deterministic plans, path ownership, idempotence, skill hashes, Lua syntax, Todoist, rclone units, and read-only audit behavior.

## Repository layout

```text
bootstrap                  Public command
lib/                       Planner, executor, audit, and terminal UI
features/                  Feature metadata and dependencies
profiles/                  Named feature selections
payload/                   Portable user-owned files
scripts/                   Capture, pin maintenance, and verification tools
tests/                     Level 1 and level 2 checks
```

Use `scripts/refresh-theme-pins.py` only to review upstream theme commits during repository maintenance. It does not update the installed system.
