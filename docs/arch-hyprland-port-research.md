# Porting the Omarchy bootstrap to Arch Linux and CachyOS

## Conclusion

The repository can support both Omarchy 4 and an Arch-based Hyprland system, but the desktop layer needs a second implementation. The application catalog, AI agents, skills, cloud mounts, editor settings, and most user services can stay shared. Package installation, Hyprland startup, shell integration, themes, and SSH setup must move behind a platform interface.

For CachyOS, the practical target is its supported `cachyos-hypr-noctalia` desktop. CachyOS installs a modular Lua Hyprland configuration, UWSM, Noctalia, the Hyprland portal, and the usual screenshot and clipboard tools. CachyOS tells existing users to install that package, select the `Hyprland (UWSM)` session, and merge user settings with the files from `/etc/skel`. It also warns that reusing an account from another desktop can create configuration and daemon conflicts. [CachyOS Hyprland guide](https://wiki.cachyos.org/configuration/desktop_environments/hyprland/) [CachyOS Hypr/Noctalia repository](https://github.com/CachyOS/cachyos-hypr-noctalia)

The implementation uses a real second backend, not checks around calls to `omarchy`. The shared executor composes [`common`](../common) with either [`omarchy`](../omarchy) or [`cachy`](../cachy). Omarchy-specific Hyprland APIs and shell plugins remain inside the Omarchy tree. Cachy uses native `hl.*`, UWSM, and Noctalia commands.

The recommended boundary is:

```text
feature catalog and profiles
        |
        +-- shared features: apps, tools, AI, skills, cloud, editors
        |
        +-- platform.omarchy4
        |     packages, o.*, Omarchy Shell, Omarchy themes, SSH helper
        |
        +-- platform.arch-hyprland
              pacman/AUR, native hl.*, UWSM, Noctalia, OpenSSH
                    |
                    +-- platform.cachyos
                          cachyos-hypr-noctalia baseline and UFW policy
```

## Supported target

The first non-Omarchy target should have this contract:

- Arch Linux or CachyOS with systemd.
- Hyprland with Lua configuration support. Current Hyprland uses `hyprland.lua`, supports modular `require()`, and exposes native `hl.*` configuration functions. [Hyprland configuration start page](https://wiki.hypr.land/Configuring/Start/) [Hyprland sample Lua configuration](https://github.com/hyprwm/Hyprland/blob/main/example/hyprland.lua)
- UWSM as the session manager. Hyprland recommends UWSM on systemd distributions, and Arch ships it in `extra`. UWSM manages the graphical session, activation environment, XDG autostart, and clean shutdown. [Hyprland systemd startup](https://wiki.hypr.land/Useful-Utilities/Systemd-start/) [UWSM documentation](https://github.com/Vladimir-csp/uwsm) [Arch `uwsm` package](https://archlinux.org/packages/extra/any/uwsm/)
- Noctalia v5 as the shell on CachyOS. Noctalia owns bars, panels, the launcher, notifications, the lock screen, idle behavior, OSDs, wallpapers, and desktop widgets. It does not own window management or application services. [Noctalia repository](https://github.com/noctalia-dev/noctalia)
- The CachyOS baseline package when `/etc/os-release` identifies CachyOS. Its official configuration already splits `monitors.lua`, `variables.lua`, `inputs.lua`, `binds.lua`, `windowrules.lua`, `workspaces.lua`, and the remaining visual settings. [CachyOS configuration repository](https://github.com/CachyOS/cachyos-hypr-noctalia/tree/master/etc/skel/.config/hypr)

Generic Arch support should install the same components explicitly. CachyOS support should treat `cachyos-hypr-noctalia` as the baseline and add only this repository's overrides.

## Feature migration matrix

| Area | Current Omarchy implementation | Arch and CachyOS implementation | Work and risk |
| --- | --- | --- | --- |
| Platform detection | `omarchy version` must report major version 4. Plans store `omarchy_major`. | Read `/etc/os-release`, `hyprctl version`, `uwsm --version`, and `noctalia --version`. Record `platform`, distro ID, and component versions in the plan. Reject unsupported Hyprland Lua or Noctalia versions before planning. | Change the plan schema and tests. This is a high-impact executor change. |
| Repository packages | `omarchy pkg add` installs catalog `packages`. Omarchy repositories make some AUR-origin names available as binary packages. | Use `pacman` for packages found by `pacman -Si`. On CachyOS, install `cachyos-hypr-noctalia` first. Resolve every feature package against the active repository instead of assuming Omarchy's provider. Arch documents `pacman` as the official repository package manager. [Arch pacman documentation](https://wiki.archlinux.org/title/Pacman) | Add a package-provider action. Reclassify names such as `visual-studio-code-bin`, `cursor-bin`, `spotify`, and `typora` per platform. Never run a partial upgrade. |
| AUR packages | `omarchy pkg aur add` hides the AUR helper. | Add an explicit AUR provider. Prefer a helper already present on the machine. Otherwise offer a reviewed manual `makepkg -si` flow or let the user install a helper. Arch states that AUR packages are user-produced, require `base-devel`, and that helpers are unsupported. [Arch User Repository](https://wiki.archlinux.org/title/Arch_User_Repository) [AUR helpers](https://wiki.archlinux.org/title/AUR_helpers) | Package review is a user boundary. The plan must identify AUR actions and must not silently install an arbitrary helper. |
| Base desktop | Omarchy provides Hyprland, portals, the shell, screenshot tools, fonts, and defaults. | CachyOS uses `cachyos-hypr-noctalia`. Generic Arch needs explicit features for Hyprland, UWSM, Noctalia, `xdg-desktop-portal-hyprland`, `xdg-desktop-portal`, `wl-clipboard`, `grim`, `slurp`, a screenshot editor, a terminal, a file manager, fonts, audio, and polkit integration. CachyOS publishes its dependency list. [CachyOS desktop package metadata](https://github.com/CachyOS/CachyOS-PKGBUILDS/blob/master/cachyos-hypr-noctalia/.SRCINFO) | Add a hidden `desktop.arch-hyprland-base` feature and a CachyOS specialization. Audit the portal and graphical session, not only package presence. |
| Hyprland root config | `hyprland.lua` loads `/usr/share/omarchy/default/hypr/bootstrap.lua`, `default.hypr.omarchy`, and Omarchy toggles. | Start from the platform's native `hyprland.lua`. On CachyOS, keep the package layout and add one repository-owned module such as `require("user.bootstrap")`. Generic Arch can own the full modular root. Use only native `hl.*`. | Split the current payload into common native modules and Omarchy-specific modules. Never copy `/etc/skel` into an established home without a reviewed merge. |
| Omarchy `o.*` helpers | `o.bind`, `o.window`, and `o.exec_on_start` wrap native behavior and attach Omarchy metadata. | Replace them with `hl.bind`, `hl.window_rule`, `hl.on`, `hl.exec_cmd`, and `hl.dsp.*`. CachyOS's own binds already use this division. [CachyOS binds](https://github.com/CachyOS/cachyos-hypr-noctalia/blob/master/etc/skel/.config/hypr/config/binds.lua) | Mechanical for window rules and most binds. Command-launching binds need replacement helpers. |
| Monitors | The wizard writes `~/.config/hypr/monitors.lua`; a known ultrawide profile also sets layout and gaps. | Keep the detector and renderer, but emit native `hl.monitor` calls into the platform's monitor module. On CachyOS, also set `MONITOR1`, `PRIMARY_MONITOR`, and workspace assignments in a repository-owned override instead of editing package defaults. CachyOS documents connector, mode, scale, and monitor variables. [CachyOS Hypr/Noctalia README](https://github.com/CachyOS/cachyos-hypr-noctalia/blob/master/README.md) | Low risk for one monitor. Add fixtures for two outputs, disconnected outputs, fractional scale, and changed connector names. |
| Input and cursor | Native `hl.config` plus `o.window` rules for terminal touchpad speed. NVIDIA and cursor variables are set through `hl.env`. | Keep the native input table. Convert terminal rules to `hl.window_rule`. Put session-wide cursor and NVIDIA variables in `~/.config/uwsm/env` or `env-hyprland` so UWSM exports them before applications start. UWSM documents those environment layers. [UWSM environment documentation](https://github.com/Vladimir-csp/uwsm#4-environments-and-shell-profile) | Validate NVIDIA variables against detected hardware. Do not force them on AMD or Intel systems. |
| Window rules and workspaces | Omarchy helpers assign Chrome, editors, media, chat, Steam, and Chromium to workspaces 1 through 6. | Express the same matches with `hl.window_rule` and declare persistent workspaces with `hl.workspace_rule`. Merge them after CachyOS defaults so user rules have clear ownership. | Add live class/title fixtures from `hyprctl clients -j`. Rules tied to Chrome web-app classes need integration tests. |
| Keybindings and launch helpers | Binds call `omarchy-launch-*`, `omarchy-cmd-terminal-cwd`, `omarchy capture`, `omarchy agent`, Omarchy audio helpers, and Omarchy Shell IPC. | Create small platform-neutral commands for launch-or-focus, web apps, terminal TUIs, pop-out sizing, and the chosen agent. Use `uwsm app --` for applications and `noctalia msg` for the launcher, lock, screenshots, notifications, volume, microphone, brightness, and session controls. Noctalia documents this as its stable IPC form. [Noctalia IPC](https://docs.noctalia.dev/noctalia/ipc/) | This is the largest behavior port. Each replacement command needs a contract test and a live Hyprland smoke test. Avoid reproducing features that Noctalia already exposes. |
| UWSM and autostart | Hyprland starts `session-apps.target`; custom systemd user services launch applications in sequence. | Keep the user units, attach them to `graphical-session.target`, and retain `After=graphical-session.target` or `wayland-session-waitenv.service` where needed. Launch graphical clients with `uwsm app --`. UWSM recommends units or XDG autostart and discourages leaving applications as compositor child processes. [UWSM applications and autostart](https://github.com/Vladimir-csp/uwsm#3-applications-and-slices) | Mostly portable. Replace the Omarchy autostart hook with either an XDG autostart entry or one native `hl.on("hyprland.start", ...)` hook. Test clean logout and relogin, not only startup. |
| Shell and bar | `~/.config/omarchy/shell.json` selects Omarchy widgets and custom QML plugins. | Add a declarative `~/.config/noctalia/config.toml` overlay. Map stock menu, workspace, clock, keyboard, weather, update, tray, network, audio, monitor, power, and notification functions to Noctalia widgets and control-center entries. Noctalia's config file is user-owned, while GUI overrides live in state and take precedence. [Noctalia configuration ownership](https://docs.noctalia.dev/noctalia/configuration/) [Noctalia bar widgets](https://docs.noctalia.dev/v5/bar/widgets/) | Do not copy the full CachyOS Noctalia config. Own a small overlay and audit the merged config with `noctalia config export`. |
| Todoist | `kuba.tasks` is an Omarchy QML bar widget and panel. `omarchy-todoist` wraps the official `td` CLI and keeps a private cache. | Keep the `td` CLI, auth probe, helper protocol, cache rules, and tests. Rewrite only the UI as a Noctalia v5 Luau plugin with a bar widget and panel. Noctalia plugins support widgets, panels, services, shared state, and IPC. [Noctalia plugin development](https://docs.noctalia.dev/noctalia/plugins/development/) [Noctalia declarative plugin UI](https://docs.noctalia.dev/noctalia/plugins/development/declarative-ui/) | Medium work. The v5 plugin API is marked beta, so declare a tested `plugin_api` and add a compatibility test against the installed Noctalia version. |
| AI agent widget | Omarchy provides `omarchy.agents`, and the selected agent is stored under `.config/omarchy/defaults/agent`. | Keep agent CLIs and settings shared. Store the default in repository-owned state, then add a small Noctalia plugin or launcher entry that opens the selected agent with `uwsm app --` and a terminal. | UI rewrite only. Do not make AI installation depend on Noctalia. |
| Notifications and Calendar snooze | The repository disables stock Omarchy notifications and ships a cloned renderer with Google Calendar snooze and middle-click behavior. | Use Noctalia's notification daemon and action buttons first. Noctalia supports external Freedesktop actions, history, filters, and notification IPC. [Noctalia notifications](https://docs.noctalia.dev/noctalia/services/notifications/) Its public plugin API does not document interception or replacement of external notification cards. Exact Calendar snooze parity therefore needs a prototype. If Chrome exposes Snooze as a Freedesktop action, invoke that action. Otherwise this feature needs an upstream Noctalia extension or a separate notification service, not an ordinary plugin. | Highest uncertainty. Treat this as a required discovery spike with a captured Chrome notification and DBus action list. Do not promise parity until the spike passes. Noctalia's own calendar may replace some browser-calendar use, but its credentials remain manual and secret-owned. [Noctalia control-center calendar](https://docs.noctalia.dev/noctalia/control-center/) |
| Screenshots, audio, lock, and idle | Omarchy CLI and Omarchy Shell implement these operations. | Use Noctalia IPC for screenshots, audio, microphone, lock, session actions, and DND. Noctalia also owns idle and lock behavior, so remove any Omarchy-only calls rather than adding another idle daemon. [Noctalia media and UI IPC](https://docs.noctalia.dev/noctalia/ipc/media-and-ui/) | Low to medium. Verify clipboard output, file output, fullscreen capture, and lock after suspend. |
| Themes and wallpapers | Pinned Omarchy theme repositories install under `.config/omarchy/themes`; `omarchy theme set` writes generated terminal and Neovim files to Omarchy state. | Convert Akane, All Hallows Eve, and Void into Noctalia custom palettes plus wallpapers. Use Noctalia templates for Alacritty, Foot, Ghostty, Kitty, Neovim, GTK, and other applications. Noctalia renders built-in, community, and user templates whenever the palette changes. [Noctalia app theming](https://docs.noctalia.dev/noctalia/theming/app-theming/) [Noctalia template reference](https://docs.noctalia.dev/noctalia/theming/templates/) | The theme repositories are not portable as-is. Extract color intent and assets, then pin the resulting palette data in this repository. Remove every `.local/state/omarchy/current/theme` include from the Arch payload. |
| Terminals and Neovim | Layout, fonts, keybindings, and scroll settings are portable. Color includes and the Neovim `theme.lua` symlink point at Omarchy runtime state. | Keep behavioral settings. Replace color includes with Noctalia-generated template files. Point Neovim at either a generated colorscheme choice or a stable repository-owned module. | Add syntax checks for every generated terminal file and start each installed terminal once in a nested test session. |
| Applications and web apps | Feature metadata installs applications. Omarchy helpers launch and focus them. | Keep feature choices and portable settings. Resolve package providers per platform. Replace web-app and focus helpers with repository-owned commands built on `uwsm app`, desktop entries, and `hyprctl -j clients`. | Most app features stay unchanged. Browser application IDs and AUR availability need live tests. |
| Cloud mounts | rclone auth and systemd user mount units are already independent of Omarchy. | Keep the units, but require `fuse3`, use explicit config and cache paths, and attach mounts to `graphical-session.target`. rclone recommends `Type=notify` for systemd mounts after the mount is ready and requires explicit paths where systemd has no `HOME`. [rclone mount](https://rclone.org/commands/rclone_mount/) Google Drive and OneDrive still require interactive `rclone config`. [Google Drive](https://rclone.org/drive/) [OneDrive](https://rclone.org/onedrive/) | Low risk. Change the units to `Type=notify` if the packaged rclone supports it, then test mount readiness and logout cleanup. Google Drive now requires a user-owned client ID because rclone's shared ID is retiring during 2026. |
| SSH from GitHub keys | The executor fetches public keys and calls `omarchy setup security sshd`, which installs OpenSSH, enables `sshd`, and configures the firewall. | Keep key fetch, validation, deduplication, and audit. Replace the Omarchy action with `openssh` installation, atomic append to `~/.ssh/authorized_keys`, mode `0700` on `.ssh`, mode `0600` on the file, `sshd -t`, and enablement of `sshd.service`. GitHub's public user-key API is unauthenticated. [GitHub public keys API](https://docs.github.com/en/rest/users/keys#list-public-keys-for-a-user) Arch documents the required key file and permissions. [Arch SSH keys](https://wiki.archlinux.org/title/SSH_keys) | Firewall handling must be a separate capability. CachyOS enables UFW by default, so add an idempotent UFW SSH rule there. [CachyOS firewall guide](https://wiki.cachyos.org/configuration/post_install_setup/#configuring-firewall-ufw) Generic Arch must not assume a firewall manager. Offer UFW, firewalld, or no rule with a clear warning. |
| AI agents and skills | `mise` installs Claude, Codex, OpenCode, optional agents, Node 24, and Python 3.14. A canonical reviewed skill tree is linked into each agent. | Keep this implementation. Move the default-agent preference out of the Omarchy namespace. Keep credentials manual and keep auth stores out of the repository. | Low risk. Add a platform-independent test that selects AI without any desktop shell feature. |
| Audit | Audit knows Omarchy theme state, Omarchy version, package presence, user units, auth, files, and SSH. | Split audit probes into shared and platform probes. The Arch backend checks package ownership, Hyprland Lua syntax, `hyprctl configerrors`, the active UWSM unit, portals, Noctalia config validation and IPC status, user units, SSH, and firewall capability. | `plan` and `audit` must remain read-only. Live graphical probes should return `WARN`, not `FAIL`, when no Hyprland session exists. |
| Updates | Bootstrap deliberately delegates later updates to `omarchy update`. | Keep bootstrap one-shot. Do not add an update command. Document that CachyOS and Arch retain their own full-system update process. Pacman does not support partial upgrades, and AUR packages remain the user's update responsibility. [Arch system maintenance](https://wiki.archlinux.org/title/System_maintenance) [Arch User Repository](https://wiki.archlinux.org/title/Arch_User_Repository#Upgrading_packages) | No executor work beyond removing the Omarchy-specific message from non-Omarchy plans. |

## Target repository structure

The catalog needs platform predicates and provider-owned payloads. A small extension is enough:

```text
platforms/
  omarchy4.toml
  arch-hyprland.toml
  cachyos-hyprland.toml

payload/
  shared/
  platform-omarchy4/
  platform-arch-hyprland/
  platform-cachyos/

features/
  core-desktop/
    feature.toml
    omarchy4.toml
    arch-hyprland.toml
```

`feature.toml` should continue to own the user-facing choice and its shared dependencies. A platform fragment should own only provider names, platform files, commands, units, and probes. This keeps `app.signal`, `agent.codex`, `cloud.google-drive`, and similar features identical across platforms.

The planner should resolve these values before it creates actions:

```text
PlatformFacts
  id: omarchy4 | arch-hyprland | cachyos-hyprland
  distro_id
  versions: hyprland, uwsm, shell
  capabilities: pacman, aur-provider, noctalia, ufw, graphical-session
```

Plans should include the resolved platform and a digest of its feature fragments. `apply` must reject a plan generated for another platform. The catalog loader should keep its current checks for dependency cycles, duplicate owners, and unsafe targets, then add checks that every selected feature has a provider for the active platform.

The Hyprland payload should favor extension points over whole-file ownership. On CachyOS, the bootstrap can install `~/.config/hypr/user/bootstrap.lua` and add one guarded `require("user.bootstrap")` to the root config. The user module can then require repository-owned monitor, input, binding, window-rule, workspace, and autostart modules. This limits conflicts when `cachyos-hypr-noctalia` updates its defaults. CachyOS's v4-to-v5 migration changed file names and Noctalia IPC calls, which shows why copied baseline files would age badly. [CachyOS migration guide](https://wiki.cachyos.org/configuration/desktop_environments/hyprland/#migrating-from-v4-dots-to-v5-updating-your-dots)

## Implementation phases

### Phase 1: separate the executor from Omarchy

1. Replace `omarchy_major` with `PlatformFacts` and a platform registry.
2. Add provider actions for repository packages, AUR packages, themes, SSH, and shell validation.
3. Keep the Omarchy backend behavior unchanged.
4. Prove that existing Omarchy plans remain deterministic and idempotent.

Exit condition: all current tests pass through `platform.omarchy4`, and a plan cannot run on a different platform.

### Phase 2: deliver the native desktop core

1. Add `platform.arch-hyprland` with pacman, UWSM, native Hyprland Lua, and Noctalia.
2. Add the CachyOS baseline adapter for `cachyos-hypr-noctalia`.
3. Port monitor, input, cursor, window, workspace, binding, and session-autostart behavior.
4. Replace each `omarchy-*` command used by a binding with either a repository helper or Noctalia IPC.

Exit condition: a clean CachyOS VM reaches the UWSM session with the expected monitor, six workspace assignments, keybindings, portals, Noctalia, and sequential session applications.

### Phase 3: port shell features and themes

1. Write the minimal Noctalia config overlay.
2. Port Todoist as a versioned Noctalia plugin.
3. Add the default-agent widget or launcher entry.
4. Convert the three themes to Noctalia palettes and templates.
5. Remove Omarchy state paths from terminal and Neovim configuration on the Arch backend.

Exit condition: Todoist reads and mutates tasks, every theme updates the shell and installed terminals, and the Noctalia merged config validates.

### Phase 4: resolve notification parity

1. Capture a real Google Calendar notification on CachyOS and inspect its Freedesktop actions.
2. Test stock Noctalia action buttons and keyboard-accessible notification IPC.
3. If the notification includes a Snooze action, add a focused helper for that action.
4. If it does not, propose the smallest Noctalia API addition upstream. Do not replace Noctalia's notification daemon unless upstream integration is impossible.

Exit condition: the same user-visible snooze action works by mouse and `SUPER+PERIOD`, or the documentation names the unsupported behavior instead of claiming full parity.

### Phase 5: shared services and hardening

1. Enable cloud, AI, skill, editor, app, and research profiles on both backends.
2. Replace the SSH Omarchy helper with the native OpenSSH action and capability-based firewall action.
3. Add a generic Arch VM fixture after the CachyOS path is stable.
4. Document distro-owned updates and AUR maintenance.

Exit condition: every feature in the migration matrix has a passing audit or an explicit manual-auth `WARN`.

## Verification plan

Keep the existing temporary-home gate and add platform fixtures. The required checks are:

- Catalog tests for both platforms, including missing providers, duplicate platform target owners, and plans applied to the wrong platform.
- Deterministic plan snapshots for Omarchy, CachyOS, generic Arch, one monitor, and two monitors.
- Two isolated applies for every platform payload. The second apply must change zero files.
- Syntax checks with `luac -p`, `noctalia config validate`, systemd unit verification, TOML parsing, and shell checks.
- A read-only host audit that snapshots packages, enabled units, and target files before and after `plan` and `audit`.
- A CachyOS virtual-machine test that starts the `Hyprland (UWSM)` session, waits for `graphical-session.target`, runs `hyprctl configerrors`, checks the portal and Noctalia IPC, and opens one application through `uwsm app --`.
- Live monitor fixtures from `hyprctl -j monitors all` and window fixtures from `hyprctl -j clients`.
- Noctalia plugin tests against the supported plugin API. The Noctalia plugin documentation labels the API beta, so the test must fail clearly when the installed version is outside the supported range. [Noctalia plugin workflow](https://docs.noctalia.dev/noctalia/plugins/development/workflow/)
- Cloud tests that verify rclone remote names before enabling mount units and confirm that the unit stops with the graphical session.
- SSH tests that use a temporary home for key merging, validate permissions, run `sshd -t` against a test configuration, and inspect firewall actions without changing the host firewall.

The active home must remain outside automated apply tests. `hyprctl reload` and `hyprctl configerrors` belong only in the live VM test or an explicitly requested apply to the current machine.

## Decisions to make before coding

Three choices affect the design enough to settle first:

1. Support CachyOS first, then generic Arch. This is the recommended order because CachyOS supplies a coherent Hyprland, UWSM, and Noctalia baseline. Generic Arch requires the repository to choose more desktop components.
2. Use Noctalia v5 as the only non-Omarchy shell. Supporting both Noctalia and Waybar would double the shell, notification, lock, theme, and plugin work.
3. Treat exact Google Calendar snooze behavior as a gated feature. The public Noctalia plugin API covers widgets and panels, but it does not document replacement of external notification cards. The implementation should follow evidence from a real notification rather than assume that the Omarchy clone can be translated directly.

With those decisions, most of the repository remains useful. The difficult work is concentrated in one platform backend, two small Noctalia plugins, theme conversion, and the notification experiment.
