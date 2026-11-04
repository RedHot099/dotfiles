# Arch Hyprland bootstrap guide

The bootstrap supports Omarchy 4 only.

The public interface is `./bootstrap setup` and `./bootstrap <packages|desktop|integrations> <plan|apply|audit>`.

## Ownership

- Treat `/usr/share/omarchy`, `/etc/skel`, package configuration, mirrors, and keyrings as read-only.
- Keep package intent and bindings under `packages/{common,omarchy}`.
- Keep Hyprland, shell, monitor, and Calendar under `desktop/{common,omarchy}`.
- Keep agents, cloud, Todoist, and access under `integrations/{common,omarchy}`.
- Do not add profiles, Gum, schema-2 CLI adapters, or a distribution update command.

Read `docs/workflow-rearchitecture-plan.md` before changing workflow boundaries, the executor, or package policy.

## Safe workflow

1. Inspect `git status --short` and preserve unrelated changes.
2. Make the smallest workflow-owned change that satisfies the request.
3. Run `./scripts/verify-bootstrap.sh`.
4. For a real Desktop apply, require a successful `hyprctl reload` and empty `hyprctl configerrors`.
5. Run `git diff --check` and inspect every changed file.

Planning writes only private selection and digest-addressed plan state. Audit is read-only. A real apply requires the current home, a non-root user, and either a confirmation in a terminal or an explicit plan digest (`apply --plan`).

## Install or update a host

Use this runbook when the user asks you to install, update, or check the configuration on a host. Run it on that host, from its checkout. Every command takes `--json` and prints one report on stdout; branch on its `status` and follow its `next_actions`. Exit codes: 0 done, 1 drift or declined, 2 failure, 3 action needed.

1. Checkout: `git status --short` is empty and the branch is `main`; then `git pull --ff-only`. A dirty checkout or another branch is the user's to resolve: stop and report it, leaving stash, reset, and branch switches to them.
2. For `packages`, then `desktop`, then `integrations` (the later two read what Packages installed):
   1. `./bootstrap <workflow> plan --json`. It uses the saved selection, or the catalog defaults on a new host. Change it with `--add ID` or `--remove ID` only on the user's word. `NEEDS_PACKAGES` gives the Packages plan to run first; `NEEDS_SESSION` means the user must log in to Hyprland.
   2. Show the user the report before applying when it lists `selection.new_items`, `changes.files.local-edit` or `unmanaged`, `changes.new_ssh_keys`, or `changes.aur_builds`. Otherwise go on.
   3. `./bootstrap <workflow> apply --plan <digest> --json`. Naming the digest approves exactly that plan.
      - `READY`: done.
      - `NEEDS_TERMINAL`: nothing changed; the plan touches packages, system services, the firewall, or SSH keys. Run the `--in-terminal` command from `next_actions`, tell the user a terminal opened that asks for their sudo password (and pacman's confirmation), then run `./bootstrap <workflow> status --plan <digest> --wait 900 --json` until the status is neither `HANDED_OFF` nor `RUNNING`.
      - `CONFLICT`: files changed outside the bootstrap. Show the list; add `--discard-local` only when the user approves (each file is backed up).
      - `INCOMPLETE`: queued logins (`needs-login`, `waiting-for-login`) need the user in a terminal: offer the handoff command. `needs-session` waits for a Hyprland login.
      - `STALE`: plan again. `BLOCKED`: back to step 1. `FAIL`: report the message. `INTERRUPTED` (from `status`) or a failure fixed later: apply the same digest again; it resumes from its journal.
3. Verify: `./bootstrap <workflow> audit --plan <digest> --json` reports `CLEAN`, and a fresh `plan --json` shows no created or updated files and empty `terminal_required`. For Desktop the `hyprland-reload` finding passes only with a running session and no `hyprctl configerrors`.
4. Undo the file changes of one apply with `./bootstrap <workflow> restore --plan <digest> --json`. Packages stay installed.

The sudo password belongs to the user's terminal alone: sudo reads it there. Keep it out of your commands, files, and logs; that rules out `sudo -S`, askpass helpers, piped answers, `--noconfirm`, and sudoers changes.

## Payload and package rules

- Use target-home-relative paths and portable `$HOME`, `%h`, or relative references.
- Keep secrets, auth stores, sessions, histories, caches, databases, and browser profiles outside the repository.
- Use Lua for Hyprland. Keep Omarchy APIs out of `common` trees.
- Do not add Waybar, Mako, or another idle or lock daemon.
- Pin every AUR package to a full commit and every mise selector exactly.
- Never add `pacman -Sy`, `--noconfirm`, integrity bypasses, repository edits, AUR helpers, rollback, or package removal.
- Route privileged changes through fixed argv arrays and keep system units allowlisted.

## Agents and skills

Agent skills, global agent instructions (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`) and pstack model teams come from the separate `RedHot099/fleet` repository. dotfiles does not install, change, or remove them, and never runs fleet's code.

## Verification

`scripts/verify-bootstrap.sh` is required. It runs Python tests, compiles the repository, checks Lua and shell syntax, validates Todoist/QML and rclone units, and runs T3 Code safety checks.
