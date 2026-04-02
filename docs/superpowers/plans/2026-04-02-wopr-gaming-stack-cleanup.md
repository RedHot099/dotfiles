# W.O.P.R Gaming Stack Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the current Arch/Omarchy gaming-mode setup using `W.O.P.R` as a reference, while keeping the working gaming stack and removing keybindings and stale installation artifacts.

**Architecture:** Use the existing local setup as the source of truth, then remove narrow configuration artifacts first, inspect package and runtime residue second, and only remove packages after dependency checks. Keep changes reversible and verify each cleanup pass with targeted searches and package queries.

**Tech Stack:** Arch Linux, pacman, Hyprland, shell scripts, udev, Steam/Gamescope/MangoHud/GameMode

---

### Task 1: Audit live gaming-mode artifacts

**Files:**
- Inspect: `~/.config/hypr/bindings.conf`
- Inspect: `~/.local/share/steam-launcher/enter-gamesmode`
- Inspect: `~/.local/share/steam-launcher/leave-gamesmode`
- Inspect: `/etc/udev/rules.d/99-gaming-performance.rules`
- Inspect: `~/.config/environment.d/*.conf`

- [ ] **Step 1: Record current gaming-related config and runtime files**

Run: `sed -n '1,220p' ~/.config/hypr/bindings.conf && printf '\n---\n' && sed -n '1,220p' /etc/udev/rules.d/99-gaming-performance.rules 2>/dev/null && printf '\n---\n' && find ~/.local/share/steam-launcher ~/.config/environment.d /etc/environment.d /etc/udev/rules.d -maxdepth 2 \\( -type f -o -type l \\) 2>/dev/null | sort`
Expected: Gaming-mode bindings, launcher scripts, and any gaming-specific `udev` or environment files are visible for removal decisions.

- [ ] **Step 2: Record installed gaming-related packages**

Run: `pacman -Qq | rg '^(steam|gamescope|mangohud|gamemode|lib32-gamemode|gum|mesa|lib32-mesa|nvidia-utils|lib32-nvidia-utils|vulkan-radeon|lib32-vulkan-radeon|libva-mesa-driver|lib32-libva-mesa-driver|mesa-vdpau|lib32-mesa-vdpau|xf86-video-amdgpu)$'`
Expected: The currently installed gaming stack is listed.

- [ ] **Step 3: Check for removable orphan packages**

Run: `pacman -Qdtq 2>/dev/null`
Expected: Either no output or a shortlist of orphan packages for manual review.

- [ ] **Step 4: Commit audit baseline**

```bash
git add docs/superpowers/specs/2026-04-02-wopr-gaming-stack-cleanup-design.md docs/superpowers/plans/2026-04-02-wopr-gaming-stack-cleanup.md
git commit -m "Add gaming stack cleanup execution plan"
```

### Task 2: Remove Hyprland gaming-mode keybindings and stale launcher references

**Files:**
- Modify: `home/.config/hypr/bindings.conf`
- Inspect: `~/.config/hypr/bindings.conf`

- [ ] **Step 1: Remove the dedicated gaming-mode binding block from repo-managed Hypr config**

Edit `home/.config/hypr/bindings.conf` to delete only this block:

```conf
# Gaming Mode bindings - added by installation script
windowrule = float on, match:class com.omarchy.gamingmode
windowrule = size 800 600, match:class com.omarchy.gamingmode
windowrule = center on, match:class com.omarchy.gamingmode
windowrule = pin on, match:class com.omarchy.gamingmode
unbind = SUPER ALT, S
bindd = SUPER SHIFT, S, Screenshot to clipboard, exec, omarchy-cmd-screenshot smart clipboard
bindd = SUPER ALT, S, Steam Gaming Mode, exec, ghostty --class=com.omarchy.gamingmode -e /home/kuba/.local/share/steam-launcher/enter-gamesmode
bindd = SUPER SHIFT, R, Exit Gaming Mode, exec, /home/kuba/.local/share/steam-launcher/leave-gamesmode
# End Gaming Mode bindings
```

- [ ] **Step 2: Apply repo config back to the live Hypr config**

Run: `./scripts/install.sh`
Expected: The managed Hypr config is copied into `~/.config/hypr/` and `hyprctl reload` is attempted.

- [ ] **Step 3: Verify no gaming-mode keybinding block remains**

Run: `rg -n 'steam-launcher|com\\.omarchy\\.gamingmode|Steam Gaming Mode|Exit Gaming Mode' home/.config/hypr ~/.config/hypr`
Expected: No matches in the active or repo-managed Hypr bindings.

- [ ] **Step 4: Commit the config cleanup**

```bash
git add home/.config/hypr/bindings.conf
git commit -m "Remove gaming mode Hypr bindings"
```

### Task 3: Remove retired launcher files and gaming-mode support artifacts

**Files:**
- Remove: `~/.local/share/steam-launcher/enter-gamesmode`
- Remove: `~/.local/share/steam-launcher/leave-gamesmode`
- Remove: `/etc/udev/rules.d/99-gaming-performance.rules`
- Inspect: `~/.config/environment.d/90-sdl-controller-filter.conf`

- [ ] **Step 1: Inspect gaming-specific support files before deletion**

Run: `sed -n '1,220p' /etc/udev/rules.d/99-gaming-performance.rules 2>/dev/null && printf '\n---\n' && sed -n '1,220p' ~/.config/environment.d/90-sdl-controller-filter.conf 2>/dev/null`
Expected: Enough context to confirm whether files are tied to gaming-mode setup or should be preserved.

- [ ] **Step 2: Remove retired launcher scripts and obsolete `udev` rule if they are only tied to gaming mode**

Run: `rm -f ~/.local/share/steam-launcher/enter-gamesmode ~/.local/share/steam-launcher/leave-gamesmode && sudo rm -f /etc/udev/rules.d/99-gaming-performance.rules && rmdir ~/.local/share/steam-launcher 2>/dev/null || true`
Expected: The launcher files and old `udev` rule are removed.

- [ ] **Step 3: Reload `udev` after rule removal**

Run: `sudo udevadm control --reload`
Expected: No error output.

- [ ] **Step 4: Verify no broken references remain**

Run: `rg -n 'steam-launcher|enter-gamesmode|leave-gamesmode|99-gaming-performance\\.rules|gaming-mode\\.conf' ~ /etc 2>/dev/null`
Expected: No remaining live references, except unrelated documentation or shell history.

- [ ] **Step 5: Commit artifact cleanup**

```bash
git add -A
git commit -m "Remove retired gaming mode artifacts"
```

### Task 4: Reconcile gaming packages and remove stale package residue

**Files:**
- Inspect only: package database

- [ ] **Step 1: Confirm reverse dependencies before package removal**

Run: `for pkg in xf86-video-amdgpu libva; do echo "=== $pkg ==="; pactree -r "$pkg" 2>/dev/null || true; done`
Expected: Reverse dependency output is small enough to determine whether each package is safe to remove.

- [ ] **Step 2: Remove stale packages only if they are not required**

Run: `sudo pacman -Rns --print xf86-video-amdgpu libva`
Expected: A dry-run style package removal plan showing what would be removed.

If the output shows only stale GPU-helper residue, run:

Run: `sudo pacman -Rns --noconfirm xf86-video-amdgpu libva`
Expected: The stale packages are removed cleanly.

- [ ] **Step 3: Remove orphan packages if any remain after cleanup**

Run: `orphans=$(pacman -Qdtq 2>/dev/null || true); if [[ -n "$orphans" ]]; then sudo pacman -Rns --noconfirm $orphans; fi`
Expected: No orphan packages remain.

- [ ] **Step 4: Verify required gaming stack remains installed**

Run: `pacman -Q steam gamescope mangohud gamemode lib32-gamemode gum mesa lib32-mesa nvidia-utils lib32-nvidia-utils vulkan-radeon lib32-vulkan-radeon`
Expected: All required packages are still installed.

- [ ] **Step 5: Commit package cleanup notes if repo state changed**

```bash
git status --short
```

Expected: Only intended repo changes remain.

### Task 5: Final verification

**Files:**
- Verify: `home/.config/hypr/bindings.conf`
- Verify: `~/.config/hypr/bindings.conf`

- [ ] **Step 1: Re-run targeted cleanup verification**

Run: `rg -n 'Steam Gaming Mode|steam-launcher|enter-gamesmode|leave-gamesmode|com\\.omarchy\\.gamingmode|99-gaming-performance\\.rules' home ~/.config /etc/udev/rules.d 2>/dev/null`
Expected: No active config or system references remain.

- [ ] **Step 2: Confirm launcher directory and old rule are gone**

Run: `test ! -e ~/.local/share/steam-launcher && test ! -e /etc/udev/rules.d/99-gaming-performance.rules`
Expected: Command exits successfully with no output.

- [ ] **Step 3: Confirm package manager is clean**

Run: `pacman -Qdtq 2>/dev/null`
Expected: No output.

- [ ] **Step 4: Commit final cleanup state**

```bash
git add -A
git commit -m "Finalize gaming stack cleanup"
```
