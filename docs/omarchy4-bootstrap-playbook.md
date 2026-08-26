# Rebuild the repository for Omarchy 4

This migration replaces the home-directory copy workflow with a one-shot bootstrap for a fresh, updated Omarchy 4 installation. The bootstrap configures the machine once. Later system updates use `omarchy update`.

## Definition of done

The migration is complete when all of these statements are true:

- `./bootstrap plan` produces a deterministic plan for the current ultrawide desktop and for an unknown-monitor fixture.
- `./bootstrap apply` converges a temporary home directory to that plan without writing to the active home directory.
- A second `apply` makes no changes.
- `./bootstrap audit` performs no writes and reports `PASS`, `WARN`, or `FAIL` with a nonzero exit status for `FAIL`.
- The default selection contains `core-desktop` and `ai-development`.
- Optional applications remain unselected until the user chooses them.
- Required dependencies stay selected and cannot be disabled.
- The repository contains only Omarchy 4 Lua overrides and user-owned Omarchy Shell configuration. It contains no copied Omarchy defaults or legacy Waybar, Mako, hyprlock, or hypridle setup.
- Claude, Codex, and OpenCode are available as core agents. Their portable configuration and every reviewed user-owned skill are reproducible without secrets, caches, sessions, or bundled system skills.
- Level 1 tests and the level 2 temporary-home checks pass.

## Scope and rigor

The current worktree has 40 changed or untracked entries. The migration affects package selection, Hyprland, Omarchy Shell, user services, cloud mounts, agents, skills, editors, terminals, and documentation. This is a high-rigor migration because a wrong installer can overwrite user configuration or enable unwanted services.

The implementation must not mutate the active home directory while it is being built. Package installation and live service changes are outside automated verification. The final handoff may run only read-only planning and audit against the current machine.

## Workflow

1. Record the current repository and machine baseline without changing either.
2. Add the verification scripts and the `plan`, `apply`, and `audit` command contract.
3. Add the catalog model for profiles, applications, dependencies, hardware, and owned paths.
4. Implement the current ultrawide profile and the unknown-monitor wizard data model.
5. Port user-owned Omarchy 4 configuration and remove legacy ownership from the target tree.
6. Add package choices, core agents, portable agent settings, and the reviewed skill index.
7. Add communication, gaming, research, cloud, and session-autostart features.
8. Apply every supported selection to a temporary home directory twice and audit the result.
9. Remove the old Makefile, manifest, capture scripts, install scripts, and legacy home mirror in one reviewed change.
10. Run read-only planning and audit against the current host.

## Throughput checkpoint

After the first vertical slice, `core-desktop` must plan, apply, and audit in a temporary home directory. If the slice needs a generic provider framework or more than one runtime dependency, simplify the design before adding another feature.

## Verification levels

Level 1 runs without a network connection, credentials, a package mutation, or a graphical session. It checks catalog parsing, dependency resolution, path ownership, hardware fixtures, skill exclusions, shell code, and Python code.

Level 2 uses a temporary home directory and non-mutating host probes. It checks idempotence, interruption recovery, manual-auth boundaries, the current desktop fixture, and the absence of bootstrap writes during planning and audit. Third-party authentication status commands may read credential stores and may contact their services.

## Delivery rule

Do not add a compatibility wrapper for the old commands. Keep the old flow only until the replacement passes the temporary-home checks, then delete it in the same migration.
