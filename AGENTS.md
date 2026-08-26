# Omarchy 4 bootstrap guide

This repository configures a fresh Omarchy 4 installation. The public interface is `./bootstrap plan`, `./bootstrap apply`, and `./bootstrap audit`.

## Ownership

- Treat `/usr/share/omarchy` as read-only reference material.
- Store only user-owned files under `payload/`.
- Put feature metadata in `features/<id>/feature.toml`.
- Put named selections in `profiles/*.toml`.
- Keep package names, files, services, repositories, and authentication probes with the feature that owns them.
- Leave system updates to `omarchy update`. Do not add an update command to `bootstrap`.

Read [docs/omarchy4-bootstrap-playbook.md](docs/omarchy4-bootstrap-playbook.md) before changing the execution model or deleting a migration guardrail.

## Safe workflow

1. Inspect `git status --short`. Preserve unrelated user changes.
2. Make the smallest catalog, payload, or executor change that satisfies the request.
3. Run `./scripts/verify-bootstrap.sh`.
4. For Hyprland changes, run `luac -p` through the verification script. Run `hyprctl reload` and `hyprctl configerrors` only when the user asks to apply the resulting plan to the active home directory.
5. Inspect `git diff --check` and the changed files before reporting completion.

Planning must only write its requested plan file. Auditing must not write through the bootstrap. Neither command may modify packages, services, credentials, or the target home directory. Third-party authentication status commands may read credential stores and contact their services. Use a temporary target home for apply tests.

## Add a feature

Create `features/<id>/feature.toml`. Declare its public label, group, dependencies, providers, owned payload, units, repositories, and authentication probes. The catalog loader must reject unknown dependencies, cycles, unsafe targets, and duplicate target owners.

Keep optional applications visible. Keep technical dependencies hidden. A selected feature must lock its required dependencies through `requires`.

Add a profile only when users need one choice to select several top-level applications. A profile contains feature IDs, not installation commands.

The feature is complete when its plan is deterministic, an isolated second apply changes zero files, and audit reports the expected state.

## Payload rules

- Use paths relative to the target home directory.
- Use `$HOME`, `%h`, or relative paths inside portable configuration. Do not store a username-specific home path.
- Keep secrets, browser profiles, rclone configuration, auth stores, sessions, histories, logs, caches, and databases out of the repository.
- Keep Omarchy 4 Hyprland overrides in Lua.
- Do not add Waybar, Mako, hypridle, hyprlock, or copied Omarchy default files.
- Use Omarchy Shell stock plugins when they provide the required behavior. A user clone needs a named behavior that differs from upstream.

`kuba.notifications` remains because it adds Google Calendar snooze behavior. `kuba.tasks` remains because Omarchy has no stock Todoist widget. The stock `omarchy.agents` plugin replaces the old `kuba.agents` clone.

## Agents and skills

Run `scripts/capture-user-skills.py` to refresh the reviewed canonical skill tree. The generator reads only direct, real directories under `~/.agents/skills` and `~/.codex/skills`. It rejects Omarchy skills, Codex `.system`, duplicate IDs with different content, and secret-like files.

Portable agent settings use allowlists under `payload/ai-development`. Do not copy an agent configuration directory wholesale.

## Verification

`scripts/verify-bootstrap.sh` is the required gate. It runs Python tests, syntax checks, static ownership checks, a temporary-home apply twice, a read-only audit, Todoist tests, notification checks, and rclone unit checks.

An audit finding has one of these meanings:

- `PASS` means the selected state matches.
- `WARN` means a manual login or a simulated external action remains.
- `FAIL` means the selected real-machine state does not match.

The decision log for this migration is [.audit/omarchy4-bootstrap.tsv](.audit/omarchy4-bootstrap.tsv).
