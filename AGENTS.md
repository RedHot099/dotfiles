# Arch Hyprland bootstrap guide

The public interface is `./bootstrap setup` and `./bootstrap <packages|desktop|integrations> <plan|apply|audit>`.

## Ownership

- Treat `/usr/share/omarchy`, `/etc/skel`, package configuration, mirrors, and keyrings as read-only.
- Keep package intent and bindings under `packages/{common,omarchy,cachy}`.
- Keep Hyprland, shell, monitor, and Calendar under `desktop/{common,omarchy,cachy}`.
- Keep agents, skills, cloud, Todoist, and access under `integrations/{common,omarchy,cachy}`.
- Do not add profiles, Gum, schema-2 CLI adapters, or a distribution update command.

Read `docs/workflow-rearchitecture-plan.md` before changing workflow boundaries, the executor, package policy, or managed fragments.

## Safe workflow

1. Inspect `git status --short` and preserve unrelated changes.
2. Make the smallest workflow-owned change that satisfies the request.
3. Run `./scripts/verify-bootstrap.sh`.
4. For a real Desktop apply, require a successful `hyprctl reload` and empty `hyprctl configerrors`.
5. Run `git diff --check` and inspect every changed file.

Planning writes only private selection and digest-addressed plan state. Audit is read-only. A real apply requires the current home, a non-root user, an interactive terminal, and explicit confirmation.

## Payload and package rules

- Use target-home-relative paths and portable `$HOME`, `%h`, or relative references.
- Keep secrets, auth stores, sessions, histories, caches, databases, and browser profiles outside the repository.
- Use Lua for Hyprland. Cachy payloads use native `hl.*`; Omarchy APIs stay in `desktop/omarchy`.
- Preserve CachyOS-owned root configuration with allowlisted fragments.
- Do not add Waybar, Mako, or another idle or lock daemon.
- Pin every AUR package to a full commit and every mise selector exactly.
- Never add `pacman -Sy`, `--noconfirm`, integrity bypasses, repository edits, AUR helpers, rollback, or package removal.
- Route privileged changes through fixed argv arrays and keep system units allowlisted.

## Agents and skills

Run `scripts/capture-user-skills.py` to refresh `integrations/common/skills/private`. It reads direct real directories under `~/.agents/skills` and `~/.codex/skills`, rejecting packaged/system skills, conflicting IDs, and secret-like files.

Protect Codex `.system`, Cursor `skills-cursor`, and unrelated non-colliding user skills. Never copy complete agent configuration directories.

## Verification

`scripts/verify-bootstrap.sh` is required. It runs Python tests, compiles both platforms, checks Lua and shell syntax, validates Todoist/QML and rclone units, and runs T3 Code safety checks.
