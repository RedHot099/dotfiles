# W.O.P.R-Informed Gaming Stack Cleanup Design

## Goal

Use the `W.O.P.R` repository as a reference to audit and clean up the current Arch/Omarchy gaming-mode setup without adopting its keybindings or forcing a full reinstall.

## Current State

The system already has the core gaming stack installed:

- `steam`
- `gamescope`
- `mangohud`
- `gamemode`
- `gum`
- `nvidia-utils` and `lib32-nvidia-utils`
- `mesa` and `lib32-mesa`
- `vulkan-radeon` and `lib32-vulkan-radeon`

The host has a hybrid GPU layout:

- NVIDIA GeForce RTX 4070 Ti SUPER
- AMD Raphael iGPU

There is already a local gaming-mode implementation present:

- `~/.local/share/steam-launcher/enter-gamesmode`
- `~/.local/share/steam-launcher/leave-gamesmode`
- Hyprland window rules and keybindings for gaming mode in `~/.config/hypr/bindings.conf`

## Desired Outcome

Keep a working gaming software stack on the machine while removing configuration and package clutter that came from earlier gaming-mode setup attempts.

The cleanup must:

- remove gaming-mode keybindings from Hyprland
- preserve or improve package coverage required for the detected GPUs
- remove stale scripts, rules, or environment overrides when they are clearly tied to old gaming-mode installs
- avoid deleting unrelated Omarchy or personal desktop customizations

## Recommended Approach

Use the existing local setup as the base, not the upstream `W.O.P.R` installer.

Apply cleanup in four phases:

1. Audit existing gaming-related files, configs, packages, and services.
2. Remove configuration artifacts that are clearly tied to the old launcher workflow, especially Hyprland keybindings and obsolete support files.
3. Reconcile installed packages against current hardware and actual runtime needs, removing only packages that are unnecessary or duplicated for this system.
4. Verify that no broken references remain in configs, scripts, or package state.

## Scope

In scope:

- Hyprland gaming-mode keybindings and window-rule block cleanup
- `steam-launcher` script review and cleanup
- gaming-mode-specific `udev` rules if present
- gaming-mode-specific environment overrides if present
- package reconciliation for Steam, Gamescope, MangoHud, GameMode, Vulkan, Mesa, and GPU-related runtime support
- orphan and residue cleanup when it does not endanger the existing Omarchy desktop setup

Out of scope:

- redesigning the overall desktop workflow
- replacing the user's preferred Steam launch path unless the current one is clearly broken
- broad removal of unrelated user applications or general development packages
- adding new keybindings

## Design Decisions

### Configuration handling

Remove the dedicated gaming-mode keybinding block from Hyprland, but keep non-keybinding functionality only if it remains useful and independently callable.

If launcher scripts are still useful without keybindings, they may remain callable manually. If they are only there to support the removed binding workflow, they should be deleted together with their references.

### Package handling

Treat installed packages in three buckets:

- required: directly needed for the current gaming stack and detected GPUs
- optional-but-useful: beneficial utilities that are harmless to keep
- stale: packages that appear to be legacy leftovers from older gaming-mode attempts or unused GPU paths

Only remove packages from the stale bucket after checking reverse dependencies and confirming they are not serving the current machine.

### Cleanup safety

Prefer targeted removal over blanket deletion.

Any cleanup action must satisfy both conditions:

- there is a clear link to the gaming-mode setup being retired or simplified
- the remaining system still has a valid launch and driver path for Steam gaming

## Verification Plan

After cleanup, verify:

- no gaming-mode keybinding block remains in Hyprland config
- no broken references to deleted scripts remain under the managed dotfiles or live config
- required gaming packages are installed for the current NVIDIA + AMD system
- no obsolete `udev` rule or environment override remains for retired gaming-mode behavior
- package manager state is consistent after removals

Verification commands should include package queries, targeted ripgrep searches, and file existence checks.

## Risks

- removing a package that is indirectly relied on by the current launch path
- leaving stale references in Hyprland or helper scripts after deleting files
- removing a workaround that is still needed for the user's specific Steam behavior

## Mitigations

- inspect reverse dependencies before removing suspect packages
- search configs for every deleted file path and feature name
- prefer disabling or deleting narrow artifacts first, then re-verify before broader package cleanup
