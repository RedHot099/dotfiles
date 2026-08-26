# Omarchy 4 migration map

This document records how the old home-directory mirror maps to the Omarchy 4 bootstrap.

## Kept as user-owned payload

- Hyprland monitor, input, binding, workspace, NVIDIA, cursor, and autostart behavior moved to Lua-only payloads.
- Neovim, VS Code, T3 Code, terminal, GTK, cursor, and branding settings moved to feature-owned payloads.
- Session application scripts and user services moved to `session-autostart`.
- The Todoist helper and `kuba.tasks` moved to the hidden `todoist` dependency of `core-desktop`.
- The `kuba.notifications` clone remains because it adds Google Calendar snooze behavior that Omarchy 4 does not provide.
- OneDrive moved to `cloud.onedrive`. Google Drive uses the same rclone policy through `cloud.google-drive`.
- Akane, All Hallows Eve, and Void are pinned by repository URL and commit instead of copying their Git checkouts.
- User skills moved to one hashed canonical tree with adapters for Claude, Codex, and OpenCode.

## Replaced by Omarchy 4

- `kuba.agents` became the stock `omarchy.agents` plugin.
- Waybar, Mako, hypridle, and hyprlock ownership returned to Omarchy Shell.
- Copied Omarchy autostart and default Hyprland files returned to the packaged defaults.
- Runtime theme state is recreated by `omarchy theme set`, not copied.
- Transient Omarchy toggles, hook samples, caches, histories, and generated state are not payload.

## Removed

- All legacy Hyprland `.conf` files from the old desktop generation.
- The manifest-based `capture`, `diff`, and `install` workflow.
- The 1Password package choice and keybinding.
- The obsolete Caprine notification patch. Omarchy 4 notification click-to-focus behavior covers Caprine, while the retained `caprine-safe` launcher only clears `ELECTRON_RUN_AS_NODE`.
- Disabled Waybar-related user units.

The current dirty worktree was the migration source. The replacement was verified against a temporary home before the old mirror was removed.
