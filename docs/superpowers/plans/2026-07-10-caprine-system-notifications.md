# Caprine System Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Caprine notification click open the relevant conversation, switch Hyprland to workspace 4, and focus Caprine.

**Architecture:** Add one narrowly scoped Mako binding for actionable notifications identified by Caprine's application name. The binding invokes the clicked notification's original action using Mako's `$id`, then dispatches the existing workspace and window focus operations through Hyprland.

**Tech Stack:** Mako 1.11, `makoctl`, Hyprland 0.55, `hyprctl`, Omarchy CLI, Bash-based dotfiles installer

---

### Task 1: Add the Caprine notification binding

**Files:**
- Modify: `home/.config/mako/config`
- Modify: `/home/kuba/.config/mako/config`

- [ ] **Step 1: Verify the Caprine rule does not already exist**

Run:

```bash
rg -n '^\[app-name=Caprine actionable\]$|makoctl invoke -n "\$id"' home/.config/mako/config /home/kuba/.config/mako/config
```

Expected: exit code 1 and no output.

- [ ] **Step 2: Add the minimal rule to the managed file**

Append this exact block to `home/.config/mako/config`:

```ini

# Keep Caprine's conversation action, then reveal its window on workspace 4.
[app-name=Caprine actionable]
on-button-left=exec sh -c 'makoctl invoke -n "$id"; hyprctl dispatch workspace 4; hyprctl dispatch focuswindow "class:^(caprine|Caprine)$"'
```

Semicolons are intentional: workspace switching and focus must still run if a notification unexpectedly lacks a default action.

- [ ] **Step 3: Verify the repository change is limited to Mako**

Run:

```bash
git diff --no-index --check /dev/null home/.config/mako/config
git diff --no-index /dev/null home/.config/mako/config
```

Expected: no whitespace errors; because the managed file is currently untracked, the diff shows its complete contents, including the existing theme include and Calendar rule followed by the new Caprine block.

- [ ] **Step 4: Synchronize only the active Mako file**

Apply the same exact block from Step 2 to `/home/kuba/.config/mako/config`.

Do not run global `make install`: `make diff` shows unrelated active changes that the current repository state would overwrite.

- [ ] **Step 5: Verify managed and active Mako configs match**

Run:

```bash
cmp home/.config/mako/config /home/kuba/.config/mako/config
```

Expected: exit code 0 and no output.

### Task 2: Reload and verify the integration

**Files:**
- Verify: `home/.config/mako/config`
- Verify: `/home/kuba/.config/mako/config`

- [ ] **Step 1: Reload Mako through Omarchy**

Run:

```bash
omarchy restart mako
```

Expected: exit code 0 with no configuration parse error.

- [ ] **Step 2: Confirm Mako owns the notification service**

Run:

```bash
busctl --user list | rg '^org\.freedesktop\.Notifications\s+.*\bmako\b'
```

Expected: one line showing `org.freedesktop.Notifications` owned by `mako`.

- [ ] **Step 3: Confirm the Caprine window remains on workspace 4**

Run:

```bash
hyprctl clients -j | jq -e 'any(.[]; (.class | test("^caprine$"; "i")) and .workspace.id == 4)'
```

Expected: `true` and exit code 0.

- [ ] **Step 4: Confirm Caprine preview and mute settings remain correct**

Run:

```bash
jq -e '.notificationMessagePreview == true and .notificationsMuted == false' /home/kuba/.config/Caprine/config.json
```

Expected: `true` and exit code 0.

- [ ] **Step 5: Perform the end-to-end acceptance check**

From another account, send a Messenger message while Caprine is in the background and another workspace is active. Confirm that:

- the Mako popup contains the sender and message body
- left-click switches to workspace 4
- Caprine is focused and displays the corresponding conversation
- no popup is produced for a message received while Caprine is already focused

- [ ] **Step 6: Commit the managed change and plan**

Run:

```bash
git add home/.config/mako/config docs/superpowers/plans/2026-07-10-caprine-system-notifications.md
git commit -m "Integrate Caprine notifications with Hyprland"
```

Expected: a commit containing only the implementation plan and managed Mako configuration.
