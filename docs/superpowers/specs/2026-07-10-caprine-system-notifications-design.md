# Caprine System Notifications Design

## Goal

Integrate Caprine's native message notifications with the Omarchy desktop so that a click opens the relevant conversation, switches Hyprland to workspace 4, and focuses the existing Caprine window.

## Current State

- Caprine 2.61.0 runs through the user-owned `~/.local/bin/caprine-safe` launcher.
- Hyprland assigns the Caprine window to workspace 4.
- Mako owns `org.freedesktop.Notifications` and displays system notifications.
- Caprine already creates native notifications only while its window is not focused.
- Caprine is configured to show the sender and message preview (`notificationMessagePreview: true`) and notifications are not muted (`notificationsMuted: false`).
- Caprine's default notification action opens the corresponding conversation, but it does not reliably switch Hyprland to the workspace containing the application.

## Desired Behavior

When a new Messenger message arrives while Caprine is in the background:

1. Mako displays a notification containing the sender and full message preview supplied by Caprine.
2. A left click invokes Caprine's original default notification action so the correct conversation is selected.
3. Hyprland switches to workspace 4 and focuses the existing Caprine window.

No system notification is required while Caprine is already focused. Right-click dismissal and other global Mako behavior remain unchanged.

## Recommended Approach

Add a narrowly scoped Mako criterion for actionable notifications whose application name is `Caprine`. Override only its left-click binding with an `exec` action that:

1. calls `makoctl invoke -n "$id"` to preserve Caprine's default notification action
2. dispatches a switch to workspace 4 through `hyprctl`
3. focuses the existing window matching the Caprine class

The Mako `exec` action exposes the clicked notification ID as the `id` environment variable. This allows the rule to invoke the exact notification that was clicked rather than whichever notification happens to be first.

## Configuration Ownership

The change belongs in the managed user configuration:

- repository: `home/.config/mako/config`
- active system: `~/.config/mako/config`

Omarchy's stock files under `~/.local/share/omarchy` remain read-only. The repository-first installation flow will keep the active configuration and dotfiles mirror synchronized.

## Data Flow

```text
Messenger message
  -> Caprine creates an Electron native notification
  -> Mako displays sender and message body
  -> user left-clicks the notification
  -> Mako invokes Caprine's default action for that notification ID
  -> Caprine selects the relevant conversation
  -> Hyprland switches to workspace 4 and focuses Caprine
```

## Failure Handling

- If the notification has no default action, `makoctl invoke` may fail, but workspace switching and focusing should still run.
- If Caprine is no longer running, the workspace switch remains harmless and the focus command has no matching window.
- The rule is limited to actionable Caprine notifications so unrelated applications retain their default behavior.
- The installed Caprine package is not modified, so package updates cannot overwrite the integration.

## Verification

1. Validate the managed file difference with `make dry-run`.
2. Install the managed configuration with `make install`.
3. Reload Mako through `omarchy restart mako` and confirm it is running.
4. Confirm Mako accepts the configuration without parse errors.
5. Send a message to the logged-in Messenger account while Caprine is on workspace 4 and another workspace is active.
6. Confirm the notification shows the sender and message body.
7. Click it and confirm Hyprland switches to workspace 4, focuses Caprine, and Caprine opens the corresponding conversation.
8. Confirm no notification is produced while the Caprine window is focused.

## Scope

In scope:

- the Caprine-specific Mako click binding
- synchronization of the managed Mako configuration to the active system
- validation of Mako and the end-to-end click flow

Out of scope:

- modifying Caprine's installed application archive
- adding a notification history service or Waybar module
- changing notification appearance, sound, grouping, or timeout
- changing Caprine's workspace assignment or startup chain
