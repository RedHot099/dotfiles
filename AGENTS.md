# Arch Hyprland bootstrap guide

This repository configures Omarchy 4 and the supported CachyOS Hyprland Noctalia image. The public interface is `./bootstrap plan`, `./bootstrap apply`, and `./bootstrap audit`.

## Ownership

- Treat `/usr/share/omarchy`, `/etc/skel`, package configuration, mirror lists, and keyrings as read-only inputs.
- Store public feature metadata in `common/catalog/features/<id>.toml`.
- Store profiles in `common/catalog/profiles/<id>.toml`.
- Put portable implementations and payloads under `common/`.
- Put complete platform-specific implementations and payloads under `omarchy/` or `cachy/`.
- Put platform package bindings in `<platform>/packages.toml`.
- Leave system updates to the installed distribution. Do not add an update command to `bootstrap`.

Read [the parallel-platform extension plan](docs/parallel-platform-extension-plan.md) before changing the execution model, package boundary, managed fragments, or migration guardrails.

## Safe workflow

1. Inspect `git status --short`. Preserve unrelated user changes.
2. Make the smallest catalog, payload, or executor change that satisfies the request.
3. Run `./scripts/verify-bootstrap.sh`.
4. For Hyprland changes, use the Lua syntax check in the verification script. Run `hyprctl reload` and `hyprctl configerrors` only when the user asks to apply the plan to the active home.
5. Run `git diff --check` and inspect every changed file before reporting completion.

Planning writes only its requested plan file. Audit is read-only through the bootstrap. Neither command changes packages, services, credentials, or the target home. Authentication probes may read local credential stores and contact their service.

Use a temporary target home for apply tests. A real system apply requires the current home, a non-root user, a terminal, and explicit approval.

## Add a feature

1. Add the public definition to `common/catalog/features/<id>.toml`.
2. Add one portable implementation under `common/implementations/`, or add one complete implementation to both platform trees.
3. Add each package requirement to both platform `packages.toml` files with an allowlisted repository or an exact AUR commit.
4. Add the feature to a profile only when one user choice must select several top-level features.

Keep optional applications visible and technical dependencies hidden. Express required dependencies through `requires`.

A feature is complete when both workspaces load, its plan is deterministic, a second isolated apply changes zero files, and audit reports the expected state or a visible platform-unavailable reason.

## Payload rules

- Use paths relative to the target home.
- Use `$HOME`, `%h`, or relative paths in portable configuration.
- Keep secrets, browser profiles, rclone configuration, auth stores, sessions, histories, logs, caches, and databases outside the repository.
- Keep Hyprland configuration in Lua.
- Use native `hl.*` APIs in Cachy payloads and Omarchy APIs only in `omarchy/`.
- Preserve CachyOS-owned root configuration with allowlisted managed fragments.
- Do not add Waybar, Mako, copied distribution defaults, or a second idle or lock daemon.

Omarchy keeps `kuba.notifications` for Google Calendar Snooze and `kuba.tasks` for Todoist. Cachy reports those shell features as unavailable until their Noctalia contracts are pinned and tested.

## Packages and privileged actions

- Use typed package requirements. Keep concrete package sources in platform bindings.
- Pin every AUR package to a full commit.
- Keep mise selectors exact.
- Route privileged changes through fixed argv arrays in the executor.
- Keep `sshd.service` as the only allowlisted system unit until a reviewed feature adds another unit.
- Keep UFW separate from SSH access.

Never add `pacman -Sy`, `--noconfirm`, integrity bypasses, repository edits, automatic AUR helpers, or package rollback.

## Agents and skills

Run `scripts/capture-user-skills.py` to refresh the reviewed canonical skill tree. The generator reads direct real directories under `~/.agents/skills` and `~/.codex/skills`. It rejects packaged skills, Codex `.system`, conflicting duplicate IDs, and secret-like files.

Portable agent settings use allowlists under `common/payload/ai-development`. Do not copy an agent configuration directory wholesale.

## Verification

`scripts/verify-bootstrap.sh` is the required gate. It runs Python tests, schema parity, syntax and ownership checks, an isolated apply twice, read-only audit, Todoist and QML tests, rclone checks, and T3 Code safety checks.

- `PASS` means that the selected state matches.
- `WARN` means that a manual login, unavailable feature, or simulated system action remains.
- `FAIL` means that the selected real-machine state does not match.

The migration decision log is [.audit/omarchy4-bootstrap.tsv](.audit/omarchy4-bootstrap.tsv).
