# Parallel Omarchy and CachyOS bootstrap plan

## Decision

The repository will keep one public CLI and three explicit ownership trees:

```text
common/   shared feature definitions, profiles, portable payloads, and intents
omarchy/  complete Omarchy 4 implementations and payloads
cachy/    complete CachyOS Hyprland implementations and payloads
```

The resolver will compose `common + exactly one platform`. It must never load both platform trees and must never fall back to the other platform when an implementation is missing.

This keeps the user-facing commands unchanged:

```bash
./bootstrap plan --out .bootstrap/plan.json
./bootstrap apply --plan .bootstrap/plan.json
./bootstrap audit --plan .bootstrap/plan.json
```

`--platform omarchy|cachy` will be an assertion for fixtures and automation, not a way to override detected facts. A mismatch will stop before the plan is written or any action is executed.

The first release will support Omarchy 4 and the current CachyOS Hyprland Noctalia edition. It will not claim support for generic Arch yet.

## Why this shape

The current `Feature` type mixes a user-visible choice with Omarchy package commands, Omarchy theme state, Omarchy Shell files, and Omarchy SSH setup. Extending that type with conditionals would spread platform knowledge through every feature.

The chosen design separates three kinds of knowledge:

- `common` defines what the user wants and stores files that are byte-for-byte portable.
- A platform feature implementation defines how that result is produced on one supported system.
- The executor handles a closed set of typed actions and does not contain feature-specific branches.

Platform differences are complete implementation records, not arbitrary field patches. A feature either has one common implementation or one complete implementation in each supported platform tree. This avoids merge-order rules and makes missing support visible during catalog validation.

## Target repository layout

```text
bootstrap
lib/
  bootstrap_cli.py
  bootstrap/
    domain.py
    platform.py
    catalog.py
    planner.py
    executor.py
    audit.py
    files.py
    packages.py
    tools.py
    fragments.py

common/
  catalog/
    features/<id>.toml
    profiles/<id>.toml
  implementations/<id>.toml
  payload/<feature>/...
  hardware/<profile>/...

omarchy/
  platform.toml
  implementations/<id>.toml
  payload/<feature>/...

cachy/
  platform.toml
  implementations/<id>.toml
  payload/<feature>/...

tests/
  fixtures/
    common/
    omarchy/
    cachy/
    package-state/
    monitors/
    clients/
  snapshots/
    omarchy/
    cachy/
```

The current top-level `features/`, `profiles/`, and `payload/` directories will disappear after the Omarchy catalog produces the same normalized actions from the new paths. There will be no compatibility loader or duplicate source of truth.

## Catalog model

### Public feature

`common/catalog/features/<id>.toml` owns only the stable product definition:

```toml
schema = 2
id = "themes"
label = "Custom themes"
description = "Akane, All Hallows Eve, and Void"
group = "Desktop"
default = false
visible = false
requires = []
```

It may define labels, grouping, defaults, visibility, dependencies, commands used for audit, and availability policy. It may not name a platform package manager, Omarchy Shell, Noctalia, or a platform state path.

### Common implementation

`common/implementations/<id>.toml` exists only when the implementation is identical on both systems. It may own portable files, user units, typed authentication probes, and package requirements whose provider is resolved separately per platform.

Good common candidates include:

- agent CLI selections and portable allowlisted settings;
- reviewed user skills;
- rclone user units and helpers;
- Todoist CLI protocol, cache, and tests;
- application settings without theme-runtime references;
- GitHub SSH key parsing and atomic merge behavior;
- monitor and workspace intent before platform rendering.

### Platform implementation

`omarchy/implementations/<id>.toml` and `cachy/implementations/<id>.toml` are complete records. They do not patch a common implementation. When behavior differs, both platform files describe the full packages, payload, services, repositories, theme adapter, and audit probes for that feature.

Examples:

- `themes` has an Omarchy implementation using pinned Omarchy themes and a Cachy implementation using reviewed Noctalia palettes and templates.
- `todoist` shares the CLI helper, while separate hidden UI features own the Omarchy Shell and Noctalia plugins.
- `core-desktop` has separate Hyprland roots, shell configuration, launch commands, and session contracts.
- `ssh-access` shares key material handling, while platform actions own package installation, service activation, and firewall capability checks.

### Composition rules

`load_workspace(root, platform)` will enforce all of these rules before planning:

1. Load `common` and exactly one selected platform tree.
2. Reject unknown feature IDs, dependency cycles, missing implementations, and duplicate implementations.
3. Require exactly one implementation for each selected feature.
4. Require exactly one package binding for every package requirement.
5. Reject duplicate file owners, including ancestor and descendant conflicts.
6. Reject duplicate package owners. Two features may not claim the same repository package, AUR package base, or pinned tool. The current catalog fails this: `features/app.t3code/feature.toml:7` and `features/app.t3code-nightly/feature.toml:7` both claim `t3code-nightly-bin`, and today's loader accepts it and emits two identical install actions for one package.
7. Confine source paths to their declared tree and target paths to the target home.
8. Reject raw shell commands, unknown action kinds, unsafe package or unit names, non-HTTPS remote sources, and every moving reference. A moving reference is a Git branch or tag, a `@latest` tool selector, or any version range that can resolve differently on two runs.
9. Reject a feature that opens a listening port unless it is `visible = true`. No such feature may enter the dependency closure of a default-selected feature through `requires`.
10. Reject Omarchy references in common payloads. Match `/usr/share/omarchy`, a `.config/omarchy/` path prefix, an `omarchy-` filename prefix, and the Lua identifier boundary `\bo\.\w`. Do not match the bare substring `o.`, which occurs constantly in ordinary prose and code.
11. Reject Cachy-specific Noctalia state and IPC calls in common payloads.
12. Hash every loaded manifest and payload byte into `workspace_digest`.

Rule 10 forces two renames, because the first draft assigned reviewed user skills and the Todoist CLI to common while those payloads live at `payload/todoist/.local/bin/omarchy-todoist` and `payload/user-skills/.local/share/omarchy-bootstrap/`. The rule and the assignment cannot both hold as written. Phase 2 performs the renames.

## Domain and public interfaces

The CLI will remain thin. These are the intended internal entry points:

```python
facts = detect_platform(host_probe)
workspace = load_workspace(repo_root, facts.platform)
selection = select_features(workspace.public_catalog, terminal)
plan = plan_install(workspace, facts, selection, target_home)
write_plan_atomically(output_path, plan)

plan = read_plan(plan_path)
facts = detect_platform(host_probe)
result = apply_install(repo_root, plan, facts, policy)

findings = audit_install(repo_root, plan, facts)
```

Core domain types:

```python
class PlatformId(StrEnum):
    OMARCHY = "omarchy"
    CACHY = "cachy"

@dataclass(frozen=True)
class PlatformFacts:
    platform: PlatformId
    os_id: str
    architecture: str
    uid: int
    target_home: str
    omarchy_major: int | None
    hyprland_version: str | None
    uwsm_version: str | None
    shell_name: str
    shell_version: str | None
    pacman_config_digest: str
    repositories: tuple[str, ...]
    capabilities: frozenset[str]

@dataclass(frozen=True)
class Workspace:
    platform: PlatformId
    public_catalog: Mapping[FeatureId, PublicFeature]
    implementations: Mapping[FeatureId, FeatureImplementation]
    package_bindings: Mapping[PackageRequirementId, PackageBinding]
    source_digest: Sha256

@dataclass(frozen=True)
class ExecutionPlan:
    schema: Literal[2]
    platform: PlatformFingerprint
    workspace_digest: Sha256
    target_home: AbsolutePath
    selected: tuple[FeatureId, ...]
    dependencies: Mapping[FeatureId, tuple[FeatureId, ...]]
    actions: tuple[PlannedAction, ...]
    digest: Sha256
```

`PlannedAction` will be a closed union. Initial variants are repository packages, reviewed AUR build, pinned tool, user file, generated file, managed fragment, pinned Git asset, user unit, system unit, manual authentication, Omarchy theme, Noctalia theme, authorized SSH keys, revoked SSH key, firewall rule, and verification probe.

Three of those variants are new relative to the first draft, and each closes a hole the draft did not see:

- `pinned tool` covers `mise`. Nine features install their program through it today, including every agent CLI and the whole `ai-development` default, yet it had no typed action and no trust rule. See [Tool and runtime provisioning](#tool-and-runtime-provisioning).
- `managed fragment` inserts or replaces one delimited block inside a file this repository does not own. Whole-file replacement cannot express what the Cachy desktop needs. See [Managed fragments](#managed-fragments).
- `revoked SSH key` gives key removal an explicit reviewed path, so pinning is not a one-way ratchet. See [SSH and firewall safety](#ssh-and-firewall-safety).

Serialized JSON must use strict schemas with unknown fields rejected. The digest protects accidental modification. It is not treated as a signature or authorization token.

## Platform detection and plan binding

Detection will fail closed:

1. Parse `/etc/os-release` as data. Never source it in a shell.
2. Select Cachy only for `ID=cachyos` plus the required Hyprland, UWSM, and Noctalia contract.
3. Select Omarchy only when Omarchy 4 markers and `omarchy version` agree.
4. Reject contradictory or ambiguous evidence.
5. Treat a missing live graphical session as a warning only when static package and version evidence is sufficient.

The plan binds to:

- platform and supported contract version;
- architecture, UID, and canonical target home;
- workspace digest;
- the repository fingerprint: repository names in configured order with their `SigLevel` and `Usage`, plus the digest of `pacman.conf` with `Include` directives resolved to their repository blocks and mirror URLs excluded;
- the package source class and repository resolved during planning;
- exact Git commits and external artifact checksums;
- exact resolved tool versions, with artifact checksums wherever the tool backend supplies one;
- exact SSH public keys and fingerprints approved during planning.

Mirror URLs stay out of the fingerprint deliberately. `/etc/pacman.conf` pulls `Include = /etc/pacman.d/mirrorlist` into `[core]`, `[extra]`, and `[multilib]`, and that file is rewritten by ordinary distribution maintenance — an Omarchy channel upgrade left a `mirrorlist.omarchy-upgrade-to-quattro` backup beside it on this machine. A fingerprint covering mirror URLs expires every plan on routine churn, and a plan that expires constantly teaches the user to re-approve without reading. What must not change silently is which repositories are trusted and in what order, not which host serves the bytes.

`apply` repeats detection and preflight before its first write. Any mismatch requires a new plan. A plan generated for an isolated fixture can only perform simulated system actions.

## Package-manager safety policy

This repository remains a one-shot installer. It will not update either system.

### Pacman invariants

- Never run `pacman -Sy` or refresh sync databases separately.
- Never add an update command to `bootstrap`.
- Never repair or rewrite `pacman.conf`, mirrorlists, Cachy repositories, keyrings, repository order, `IgnorePkg`, or `SigLevel`.
- Never pass `--noconfirm`, `--overwrite`, `--nodeps`, `--assume-installed`, signature bypasses, or package-integrity bypasses. This binds every path, including any wrapper that would pass them on the caller's behalf.
- Never delete `/var/lib/pacman/db.lck`. An active or unexplained lock aborts the package phase.
- Validate package names with a conservative grammar and pass them as argv after `--`.
- Resolve package repository and candidate version during planning. Re-resolve immediately before apply and abort if origin or transaction changes.
- Use one reviewed transaction for repository packages. Confirm the postcondition with `pacman -Q` before journaling success.
- Check sync-database freshness during preflight. Because bootstrap correctly never runs `-Sy`, a database older than the mirrors fails with `target not found` or a download 404, which reads as a bootstrap defect rather than a stale system. Compare the mtime of `/var/lib/pacman/sync/*.db` against a threshold and emit the update instruction below instead of attempting the transaction.

Arch does not support partial upgrades. If preflight determines that installing the selected packages would require a system update, bootstrap stops and instructs the user to run `omarchy update` or the CachyOS-supported full update workflow, then generate a new plan. It must not solve this by running `pacman -Syu` itself. See [Arch system maintenance](https://wiki.archlinux.org/title/System_maintenance#Partial_upgrades_are_unsupported), [pacman(8)](https://man.archlinux.org/man/pacman.8.en.html), and [pacman.conf(5)](https://man.archlinux.org/man/pacman.conf.5.en).

The Cachy backend accepts only repositories already configured by CachyOS. It will not add Cachy repositories to generic Arch. Repository names for every requirement will use an allowlist backed by the supported Cachy image and [CachyOS repository policy](https://wiki.cachyos.org/policy/repository_policy/).

### One package adapter for both platforms

The first draft kept `omarchy pkg add` for signed repository packages on Omarchy, relying on the wizard to show the package set first. That is withdrawn. On Omarchy 4.0.1 the adapter is:

```bash
# /usr/share/omarchy/bin/omarchy-pkg-add
sudo pacman -S --noconfirm --needed "$@"
```

It contradicts the invariant above, and the wizard mitigation does not reach what `--noconfirm` actually suppresses. `pacman(8)` describes the flag as bypassing "any and all" confirmations, which includes provider selection — where the first provider in repository order wins silently — and replacement prompts. Showing the user the *named* packages does not show them the resolved transaction, so "use one reviewed transaction" and "abort if the transaction changes" cannot be enforced through a wrapper that never exposes one.

This is not theoretical on the Cachy side. `cachyos-hypr-noctalia` declares both `provides=('cachyos-desktop-settings')` and `conflicts=('cachyos-desktop-settings')`, and the CachyOS Hyprland guide tells users to expect that conflict and resolve it by hand.

Both platforms therefore use one adapter:

1. Resolve the transaction with `pacman -S --print --print-format` and record it in the plan.
2. Re-resolve immediately before apply and abort on any difference in origin, version, or transaction membership.
3. Show the full resolved transaction, including dependencies, replacements, and removals, and request explicit consent.
4. Execute `pacman -S --needed` with the reviewed names as argv after `--`, without `--noconfirm`, under the privilege boundary below.
5. Confirm each package with `pacman -Q` before journaling success.

`omarchy pkg aur add` is rejected for the same class of reason: it runs `yay -S --noconfirm --needed`, delegating both the review and the build to an AUR helper. Both platforms use the reviewed AUR boundary described next.

### AUR boundary

AUR packages are user-produced build recipes that execute code. Official Arch guidance requires users to inspect build files and build without root privileges. See [Arch User Repository](https://wiki.archlinux.org/title/Arch_User_Repository), [makepkg(8)](https://man.archlinux.org/man/makepkg.8), and [PKGBUILD(5)](https://man.archlinux.org/man/PKGBUILD.5.en.html).

Required flow:

1. The feature selector labels every AUR package as `[AUR]`. Selection only includes it for review.
2. Planning fetches its AUR Git repository as the target user into a private temporary directory.
3. The plan records package base, full commit, `PKGBUILD`, `.SRCINFO`, install scripts, patches, sources, and their hashes.
4. Apply shows the complete build-file diff and requests explicit approval for each package base.
5. Any changed commit, file, dependency, package source, or produced transaction invalidates approval.
6. Build as the unprivileged target user with a scrubbed environment. A clean `devtools` chroot is a supported option and a documented recommendation, not a requirement — reviewing the `PKGBUILD` and building unprivileged in a clean environment captures most of the benefit at a fraction of the setup, and making the chroot mandatory would block Phase 4 on infrastructure this repository needs for nothing else.
7. Do not expose repository credentials, SSH agent sockets, API tokens, or the user's agent environment to the build.
8. Install only the resulting local package with `pacman -U` under the privilege boundary below.
9. Verify installed package identity and provenance after installation.
10. Declining review for a package base skips that package and its dependent feature closure, reports the incomplete state, and leaves every other action untouched. A declined review never leaves a half-applied feature.

The bootstrap will not install or depend on `yay` or `paru`. An existing helper may assist metadata retrieval, but it cannot bypass review. `curl | sh`, moving branches, `--skipinteg`, `--skipchecksums`, `--skippgpcheck`, and automatic execution of new AUR dependencies are forbidden.

## Tool and runtime provisioning

`mise` installs the agent CLIs, the language runtimes, and the Todoist CLI. It is a third-party code path of the same trust class as the AUR, and the first draft omitted it from both the action union and the trust model — so the design spent twenty lines securing seven AUR packages while nine features fetched and executed network code with no review at all:

```text
agent.claude/feature.toml:7      mise = ["claude@latest"]
agent.codex/feature.toml:7       mise = ["codex@latest"]
agent.opencode/feature.toml:7    mise = ["opencode@latest"]
agent.grok/feature.toml:7        mise = ["npm:@xai-official/grok@latest"]
todoist/feature.toml:9           mise = ["npm:@doist/todoist-cli@latest"]
tool.node/feature.toml:7         mise = ["node@24"]
tool.python/feature.toml:7       mise = ["python@3.14"]
```

`@latest` also breaks the determinism this design claims elsewhere. Two applies of one plan can install different code, and `audit` cannot see the difference because `_mise_satisfied` only asks `mise where`.

Rules:

- Feature manifests declare exact versions. `claude@2.1.4`, never `claude@latest`. Composition rule 8 rejects the moving form at load time.
- Planning resolves each selector to a concrete version and records it in the plan, with the artifact checksum wherever the backend supplies one.
- Apply re-resolves and aborts when the resolved version differs from the plan.
- Audit compares the installed version against the plan, not merely the tool's presence.
- Version bumps are a reviewed catalog change, exactly as the pinned theme revisions already are.

Not every `mise` backend exposes an artifact checksum. Where none exists the pin is a version pin only, and the plan says so rather than implying an integrity guarantee the code cannot make.

## Managed fragments

Whole-file replacement cannot express what the Cachy desktop needs, and the first draft had no other mechanism.

`cachyos-hypr-noctalia` ships its Hyprland configuration to `/etc/skel/.config/hypr/`. The root `hyprland.lua` is thirteen `require("config.*")` lines, and the CachyOS Hyprland guide puts monitor identity in `config/variables.lua` as `MONITOR1` and `PRIMARY_MONITOR`, with per-monitor workspace counts in the same file. Reproducing this repository's monitor and workspace behavior therefore means writing into files the distribution seeded and continues to revise — and the v4-to-v5 rename shows that owning copies of those baselines ages badly.

The `managed fragment` action inserts or replaces exactly one delimited block:

```lua
-- BEGIN arch-hypr-bootstrap
require("user.bootstrap")
-- END arch-hypr-bootstrap
```

Constraints:

- The destination is one of an explicit allowlist: `.config/hypr/hyprland.lua`, `.config/hypr/config/variables.lua`, `.config/hypr/config/workspaces.lua`, and `.config/noctalia/config.toml`.
- The plan records the pre-image hash. Apply aborts when the file changed since planning.
- The original file is backed up once, like any other write.
- Content outside the delimiters is preserved byte-for-byte.
- Removing the fragment restores the file to its pre-image when nothing else changed.

This is the only place where a target path has a shared owner, and the allowlist exists precisely to bound that exception.

## Privilege boundary

The main bootstrap, catalog loader, planner, wizard, and audit always run as the target user. Running `sudo ./bootstrap ...` must fail.

The first draft routed system changes through a small root-owned helper with a closed operation set. That helper is withdrawn from the first release, for two reasons.

It never said where it lives or who installs it, and the obvious implementation is a privilege escalation. A helper script inside this git checkout, reachable from a sudoers rule, hands the user's own account a path to root: anything running as the user edits the script, and the next invocation runs it as root. The repository is user-writable by definition.

More importantly it does not earn its cost. Bootstrap needs exactly three privileged capabilities — install packages, enable `sshd.service`, add one UFW rule. A one-shot interactive installer performs all three with `sudo` and a fixed argv array. A custom helper is weaker than interactive sudo unless it is `NOPASSWD`, and a `NOPASSWD` rule is a standing privilege that outlives the install.

The first release therefore uses `sudo` directly:

- Every privileged call is a fixed argv list built in code. No shell string, no user-supplied path, no `sudo -E`, no inherited `PATH`.
- Privileged calls require a TTY. `apply` refuses to perform them non-interactively.
- The privileged operation set is exactly: `pacman -S --needed` with reviewed names, `pacman -U` with a locally built reviewed package, `systemctl enable --now` for one allowlisted system unit, and one `ufw limit` rule.
- Writing a system file is not in the set. No feature in the catalog needs one, and it was the most dangerous operation in the withdrawn helper — it would have installed user-controlled content to a root-owned path behind a validation that only checked the destination.

If a helper is reintroduced later it must satisfy all of: installed to a root-owned path outside this repository, such as `/usr/local/libexec/`; installed by a documented manual step, never by `bootstrap` itself; referenced from sudoers by its absolute installed path; and not `NOPASSWD`. Guidance comes from [sudoers(5)](https://www.sudo.ws/docs/man/1.9.14/sudoers.man.pdf).

User session services stay under `systemctl --user`. System units are limited to machine services such as `sshd`, and `display-manager` is permanently excluded from the allowlist — a failed apply that disables the active display manager leaves a machine with no graphical login. Validate the units this repository ships with `systemd-analyze verify`. Hardening the distribution's own `sshd` unit is packaging's job, not this repository's.

## Filesystem, concurrency, and rollback

The file executor needs stronger guarantees than the current implementation:

- Acquire one `flock` for the target state directory before preflight and keep it through apply.
- Reject a second concurrent apply before mutation.
- Resolve user targets by walking path components with `os.open(..., O_NOFOLLOW | O_DIRECTORY, dir_fd=parent)` from an opened home directory descriptor, rejecting any symlinked parent. CPython does not expose `openat2`: on Python 3.14.7 neither `os.openat2` nor `os.RESOLVE_BENEATH` exists, so the first draft's preference for `RESOLVE_BENEATH` and `RESOLVE_NO_SYMLINKS` would require a hand-built `open_how` struct behind a raw architecture-specific `ctypes` syscall. The descriptor walk is sufficient for a single-user installer and is reviewable.
- Use a random same-directory temporary file, set ownership and mode, write, `fsync` the file, validate it, rename atomically, then `fsync` the directory.
- Back up the original file and metadata once under `.local/state/arch-hypr-bootstrap/backups/<plan-digest>/`.
- Create the state directory mode `0700`. It holds backups of overwritten user files, and the plan file beside it embeds authorized SSH keys and absolute target paths.
- Stage Git checkouts beside the destination. Verify URL, full commit, allowed files, signatures when configured, and absence of unexpected executable content before rename.
- Never reset a dirty checkout, replace an unexpected remote, recursively delete a user directory, or follow a target symlink.
- Journal an action only after its postcondition passes. On retry, trust the postcondition rather than the journal alone.

Global package rollback is deliberately out of scope. Pacman hooks and rolling-release dependencies make blind downgrade unsafe. Bootstrap can restore its own files and exact prior unit states. Before package work it records installed versions, package origins, unit state, and hashes. Snapshot integration is out of the first release: the first draft recorded Btrfs snapshot availability without any action consuming it, which reads as a safety claim the code does not make.

## SSH and firewall safety

`ssh-access` is a visible, opt-in feature, never reachable through `requires` from a default-selected feature. The current worktree violates this and the violation ships today: `features/core-desktop/feature.toml:7` hard-requires `ssh-access`, `features/ssh-access/feature.toml` is `default = false, visible = false`, and the wizard lists only visible features. A plain `./bootstrap` on a fresh machine therefore installs an SSH server, enables it at boot, opens the firewall, and authorizes whatever `github.com/RedHot099.keys` returns at that moment, with no way to decline. Composition rule 9 makes this a load-time error.

Planning fetches public keys from GitHub, validates their wire format, computes fingerprints with `ssh-keygen`, shows each fingerprint for individual approval, and embeds the exact approved key bytes in the plan. Apply never fetches a fresh set. GitHub documents the public endpoint in [List public keys for a user](https://docs.github.com/en/rest/users/keys#list-public-keys-for-a-user).

The shared SSH operation, in this order:

1. Install signed `openssh`.
2. Reject symlinked `.ssh` and `authorized_keys` targets.
3. Preserve existing unrelated keys and comments.
4. Merge exact approved keys atomically and deduplicate by key blob.
5. Enforce ownership plus mode `0700` on `.ssh` and `0600` on `authorized_keys`.
6. Validate with `sshd -t`.
7. Only now enable `sshd.service`.
8. Only then, and only through the separate opt-in firewall action, open the port.

Both platforms use this operation. The first draft's allowance for Omarchy to keep its own adapter is withdrawn, because that adapter inverts the order. `/usr/share/omarchy/bin/omarchy-setup-security-sshd` runs `setup_sshd`, which installs `openssh` and runs `systemctl enable --now sshd.service`; then `open_firewall`, which runs `ufw limit 22/tcp` and `ufw reload`; and only then `authorize_key`. Because `lib/bootstrap_core.py:332` calls it once per fetched key, the first call exposes a network-reachable `sshd` through an opened firewall port while `authorized_keys` is still empty. It also writes to `$HOME` rather than the plan's `target_home`, and the action union already contains an `authorized SSH keys` variant that does this correctly.

Key drift has a defined severity. Upstream removal of a pinned key is an audit `FAIL` naming the stale fingerprint. Pinning stops silent addition; it does nothing about an authorization the user has since revoked upstream, and a subset check cannot notice a key that disappeared — `_github_ssh_satisfied` in the current executor cannot. Audit still never writes. Revocation happens through the `revoked SSH key` action, which is reviewed and explicit.

Firewall configuration is separate and opt-in. CachyOS enables UFW by default with incoming traffic denied, so on that platform the rule is what makes SSH reachable rather than a cosmetic addition, and the consent prompt must say so. Cachy may expose a typed UFW limit rule only when UFW is already installed and active. The plan shows the exact port and current remote-session risk. It never resets rules or silently enables a firewall. An unknown firewall produces an audit warning.

## Desktop ownership split

### Common

- monitor identity, preferred mode, position, scale, and fallback policy;
- workspace assignment intent;
- application IDs and launch-or-focus behavior contracts;
- terminal and editor behavior without platform theme includes;
- session application ordering;
- Todoist CLI behavior and cache protocol;
- AI tools, allowlisted settings, default-agent intent, and reviewed skills;
- rclone helpers and user-unit behavior;
- public SSH key parsing and merge rules.

### Omarchy

- Hyprland root loading `/usr/share/omarchy` and all `o.*` calls;
- Omarchy Shell configuration and user plugins;
- Omarchy launcher, capture, audio, lock, and agent commands;
- Omarchy themes and state-generated terminal/Neovim includes;
- Omarchy package and SSH adapters;
- Omarchy-specific audit probes.

### Cachy

- `cachyos-hypr-noctalia` platform contract;
- native Hyprland `hl.*` root and guarded user module;
- UWSM environment and `uwsm app --` launching;
- Noctalia configuration, IPC, Luau plugins, palettes, and templates;
- native OpenSSH and optional UFW actions;
- Noctalia, UWSM, portal, and Hyprland audit probes.

Desktop intent will render into native platform files during planning. The project will not implement an `o.*` compatibility layer for Cachy. Generated bytes and hashes are stored in the plan, so apply remains deterministic. Where the destination is a file `cachyos-hypr-noctalia` seeded, rendering goes through a [managed fragment](#managed-fragments) rather than whole-file ownership.

Two Cachy prerequisites sit outside this repository's scope and must be stated rather than assumed:

- **A prepared account.** `/etc/skel` is copied only at account creation. The CachyOS Hyprland guide calls a new user account "highly recommended" and reusing an existing one "highly discouraged", offering `cp -r /etc/skel/. ~` only as a fallback and only after a snapshot. Bootstrap does not seed skel. `plan` fails with an explicit message when `~/.config/hypr/hyprland.lua` is absent.
- **A display manager.** The same guide ends by installing `sddm` or `noctalia-greeter` and running `systemctl disable display-manager` followed by `systemctl enable <new>`. Nothing in this design owns that step, and `display-manager` stays off the system-unit allowlist. Reaching the `Hyprland (UWSM)` session is a documented manual prerequisite of the Cachy acceptance test, not something bootstrap delivers.

## Plan, apply, and audit behavior

### Plan

- Detect and assert the platform.
- Compose and validate the workspace.
- Show the interactive list of missing programs with repository and trust class.
- Resolve dependencies and package provenance.
- Resolve every tool selector to a concrete version and record it with any available checksum.
- Render monitor and desktop configuration.
- Fetch and pin reviewed external material, including SSH keys and AUR metadata.
- Produce stable typed actions and a canonical digest.
- Write only the requested plan file.

### Apply

- Acquire the target lock.
- Refuse root execution and re-detect platform, user, home, workspace, repository fingerprint, and sources.
- Run every preflight before the first mutation, including sync-database freshness and every managed-fragment pre-image.
- Require a TTY before the first privileged call.
- Show changed package transactions and request renewed consent.
- Execute typed actions in dependency order.
- Verify each postcondition before journaling success.
- Retry only the failed action. Never recursively restart the whole executor.
- Preserve skipped-feature dependency closure and report incomplete state.

### Audit

- Perform no writes and invoke no mutating package, service, credential, or desktop commands.
- Check desired postconditions, not journal history.
- Report `PASS` for convergence, `WARN` for manual authentication or unavailable runtime context, and `FAIL` for divergence on a matching real host.
- Use shared probes for files, packages, tools, skills, auth readiness, and user units.
- Use platform probes for Omarchy state or Cachy UWSM, Noctalia, portal, native SSH, and firewall state.

## Migration phases

### Phase 0: correct the live defects, then freeze Omarchy behavior

Four defects ship today and are independent of the migration. They land first, still on schema 1, so any regression is attributable before the executor changes underneath them.

1. Remove `"ssh-access"` from `features/core-desktop/feature.toml:7` and set `visible = true` in `features/ssh-access/feature.toml`. A default install must not enable a listening service.
2. Replace the `github-ssh` action's call to `omarchy setup security sshd` with the ordered operation from [SSH and firewall safety](#ssh-and-firewall-safety): install `openssh`, write pinned keys atomically to `target_home`, `sshd -t`, enable the service, firewall separately and opt-in.
3. Add the duplicate-package-owner check and the moving-reference check to `load_catalog`, then pin the nine `mise` selectors to exact versions.
4. Add `luac -p` over every payload `.lua` to `scripts/verify-bootstrap.sh`. `AGENTS.md:21` already claims the gate runs it; the script contains no `luac` invocation.

Then freeze:

5. Add schema-1 golden plans for every profile and representative selections.
6. Record current file owners, packages, AUR packages, tools, units, repositories, auth probes, themes, SSH actions, and monitor fixtures.
7. Write the schema-1 to schema-2 action normalizer as a reviewed, tested artifact with its own snapshot tests.
8. Add static checks for unsafe targets, shell-shaped actions, secrets, and moving references.

Exit gate: the four defects are fixed and covered by tests; current Omarchy planning is deterministic; isolated apply converges twice; audit snapshots are stable; and the normalizer maps every frozen schema-1 action to its schema-2 form.

The normalizer is a Phase 0 deliverable rather than an implicit step of Phase 1 because the exit gates of Phases 1 and 2 both read "normalized actions match the frozen baseline". That phrase carries the entire correctness argument for two phases. Until the mapping exists as code with tests, neither gate can fail, which means neither is a gate.

### Phase 1: introduce schema 2 and platform identity

1. Add the domain types and strict plan parser.
2. Add fail-closed platform detection.
3. Add workspace, repository, home, UID, architecture, and source fingerprints.
4. Reject schema 1 with a clear regenerate-plan message. Do not keep a compatibility executor.
5. Rename new state to `.local/state/arch-hypr-bootstrap` at mode `0700`, carry `skipped_features` forward in a one-time migration, and retain old backups read-only. Without that migration the first schema-2 apply on the real machine starts with an empty journal and silently retries every feature the user previously chose to skip.

Exit gate: a cross-platform or drifted plan performs zero actions, while normalized Omarchy actions still match the frozen baseline.

### Phase 2: create the three ownership trees

1. Create `common`, `omarchy`, and `cachy` bundles and their validators.
2. Move public catalog and profiles to common.
3. Classify every implementation and payload file.
4. Perform the renames composition rule 10 requires: `omarchy-todoist` becomes `todoist-helper`, and `.local/share/omarchy-bootstrap` becomes `.local/share/arch-hypr-bootstrap`.
5. Move portable files to common and Omarchy-only files to omarchy.
6. Add complete platform implementation records, not patches.
7. Switch all loaders and tests in one wave, then delete old top-level trees.

Exit gate: `common + omarchy` generates the same desired Omarchy state, no platform payload reference appears in common, and every payload symlink survives the move as a symlink.

Step 7 is deliberately atomic. Eighteen call sites outside the catalog hardcode `payload/`, `features/`, or `profiles/`: `lib/bootstrap_cli.py:79,80,117,130`, `lib/bootstrap_core.py:259,388`, `scripts/verify-bootstrap.sh:11,15,20,43-46`, `scripts/verify-todoist-integration.sh:5,6,17,20`, `scripts/capture-user-skills.py:25`, `scripts/refresh-theme-pins.py:14`, `tests/test_bootstrap.py:218,231`, `tests/test_omarchy_todoist.py:15`, plus `AGENTS.md:8-10,28,51` and `README.md:113-115`. Splitting the switch leaves two sources of truth, which is worse than one large reviewed change.

The symlink clause matters because `payload/core-desktop/.local/share/icons/Maverick Pointy Dark/cursors/` holds many relative symlinks that `_file_actions` records through `os.readlink`. A move that dereferences them changes the plan without changing intent.

### Phase 3: harden execution boundaries

1. Replace free-form authentication commands with typed argv and probes.
2. Add the process lock, descriptor-based path confinement, random staging, `fsync`, and exact backup metadata.
3. Stage and verify Git assets before installation.
4. Add the `managed fragment` action with its destination allowlist and pre-image check.
5. Reject root execution of the main CLI and route every privileged call through fixed-argv `sudo` with a required TTY.
6. Record and restore exact prior unit state.
7. Add failure-injection tests around interruption, retry, and second apply.

Exit gate: concurrency, symlink race, option injection, crash, retry, atomicity, and fragment pre-image tests pass.

Step 7 moved here from Phase 0. Written earlier it would have targeted the executor this phase replaces wholesale, so the tests would be discarded along with the code they cover.

### Phase 4: implement package and tool providers

1. Inventory every current package and tool on current Omarchy and supported CachyOS.
2. Record allowed signed repositories for each requirement.
3. Build the single reviewed pacman adapter for both platforms and retire `omarchy pkg add` and `omarchy pkg aur add`. It must not change distro repository configuration on either system.
4. Add the sync-database freshness preflight.
5. Build the shared AUR review and clean-build flow.
6. Add the `pinned tool` provider with resolved versions, checksums where the backend supplies them, and audit comparison against the plan.
7. Add stale-system, changed-source, changed-transaction, lock, and interrupted-transaction fixtures.

Exit gate: no package or tool mutation can occur with an unknown origin, unsafe option, unreviewed AUR recipe, moving version selector, stale approval, or mismatched platform.

### Phase 5: deliver the Cachy desktop core

1. Add the supported CachyOS Hyprland Noctalia contract, including a probed Noctalia and Hyprland version range. `cachyos-hypr-noctalia` depends on both unversioned, so the floor must be a plan-time probe, not a package dependency.
2. Add the guarded user extension point as a managed fragment in the seeded root config.
3. Port monitor, input, cursor, workspace, window-rule, and binding intent, writing monitor identity through `config/variables.lua` as the distribution expects.
4. Add UWSM environment and replace Omarchy launch commands with `uwsm app --` and `noctalia msg`.
5. Add portal and minimal Noctalia configuration.

Exit gate: on a clean CachyOS VM with a freshly created account and a display manager already configured, the session enters `Hyprland (UWSM)`, reports no Hyprland config errors, exposes its portal and Noctalia IPC, reproduces the monitor and six-workspace behavior, and survives a logout and relogin with user units and mounts detaching and reattaching cleanly.

The logout and relogin clause is not decoration. UWSM session teardown and `graphical-session.target` ordering are exactly where user units and rclone mounts break, and a first-boot-only test cannot see it.

### Phase 6: port shell behavior and themes

1. Port Todoist UI to a version-pinned Noctalia plugin while keeping its CLI logic common.
2. Add the default-agent Noctalia widget or launcher entry.
3. Convert Akane, All Hallows Eve, and Void to reviewed palettes and templates.
4. Remove Omarchy runtime theme references from Cachy terminal and Neovim files.
5. Validate Noctalia's plugin API, the merged configuration, and whether GUI state silently overrides the written `config.toml`. Noctalia documents state as taking precedence over the config file, so a written overlay may become inert the first time the user opens the settings panel.

Exit gate: Todoist operations work, every theme updates Noctalia and installed applications, and unsupported Noctalia versions fail before mutation.

### Phase 7: resolve Calendar notification parity

1. Capture a real Chrome Google Calendar Freedesktop notification and its D-Bus action list.
2. Test stock Noctalia action handling.
3. Implement Snooze only if the notification exposes a suitable action or Noctalia gains a reviewed extension point.
4. Otherwise mark the feature unavailable on Cachy with an explicit reason.

Exit gate: Snooze works through the real notification path, or the catalog truthfully reports the limitation.

### Phase 8: shared applications and machine services

1. Enable AI, skills, editors, cloud, applications, and research profiles on Cachy.
2. Add native SSH with planned GitHub key fingerprints and the `revoked SSH key` action.
3. Add the separate optional UFW action.
4. Test rclone mounts, session cleanup, authentication warnings, SSH configuration, and failure recovery.

Exit gate: every selectable feature has a passing implementation and audit or a visible platform-unavailable reason.

### Phase 9: release gate and documentation

1. Run the full verification matrix for both platforms.
2. Test real Omarchy 4 and a clean supported CachyOS VM.
3. Document AUR trust, recovery limits, platform ownership, and distro-owned updates.
4. Keep one `scripts/verify-bootstrap.sh` entry point with separate platform sections.

Exit gate: both platforms satisfy their acceptance matrix and the second isolated apply changes zero files.

## Verification matrix

| Area | Required proof |
| --- | --- |
| Catalog | `common + omarchy` and `common + cachy` load independently; missing implementations, duplicate file owners, duplicate package owners, moving references, and a listening service inside a default closure all fail |
| Platform | Omarchy plan on Cachy and Cachy plan on Omarchy execute zero actions |
| Plan | Stable snapshots include platform, workspace, source, target, and SSH fingerprints |
| Read-only contract | Filesystem, package database, units, credentials, and target home are unchanged by plan and audit |
| Files | traversal, symlink ancestor, TOCTOU, interrupted write, and concurrent apply tests fail safely |
| Packages | no standalone `-Sy`, `--noconfirm`, unsafe flags, hidden repositories, shell execution, stale transaction, or deleted pacman lock; the resolved `--print-format` transaction is shown and re-checked; a stale sync database stops the phase with the update instruction |
| Tools | every selector is exact; the resolved version is recorded, re-checked before apply, and compared by audit against the plan rather than by presence |
| Fragments | destination allowlist enforced; a changed pre-image aborts; content outside the delimiters stays byte-identical; removal restores the pre-image |
| AUR | no build before review; changed recipe invalidates consent; build UID is non-root; clean environment is enforced |
| Privilege | main CLI rejects root; privileged calls are fixed argv, require a TTY, and cover only the four allowed operations; `display-manager` is never an allowed unit |
| Idempotence | two isolated applies per platform; second result reports zero changed files |
| Omarchy VM | Omarchy 4 plan/apply/audit, shell, themes, SSH, and existing behavior pass |
| Cachy VM | UWSM login/logout, Hyprland Lua, portal, Noctalia IPC/plugins, themes, SSH, and selected apps pass |
| Monitor | one-monitor, ultrawide, unknown-monitor, disconnected-output, and invalid-mode fixtures |
| Services | user units verify, start only after graphical session, and restore previous state on rollback |
| SSH | only keys embedded in the plan are authorized; keys are written before the service is enabled and before any firewall rule; upstream removal of a pinned key is a `FAIL` naming the fingerprint; drift never causes a write |
| Session | Cachy logout and relogin restore the session; user units and mounts detach and reattach; a second boot reproduces the first |
| Recovery | files and prior unit states restore exactly; package failures produce a recovery report, not blind downgrade |

## Main risks and explicit non-goals

- AUR cannot be made as trustworthy as signed distribution repositories. The design makes execution visible and constrained but still requires human review.
- A generic automatic test cannot prove that a rolling-release package downgrade is safe. Package rollback stays manual or snapshot-based.
- Noctalia's plugin API may change. The Cachy platform contract must pin and test the supported range.
- Google Calendar Snooze remains gated by observed D-Bus behavior.
- The initial Cachy backend does not imply support for every Arch Hyprland setup.
- Bootstrap does not perform system updates, repair trust databases, add Cachy repositories, or manage later updates.
- Noctalia GUI state may override a written `config.toml`. Theme and shell delivery must be verified against the merged result, not against the file this repository wrote.
- CachyOS account preparation and display-manager selection are manual prerequisites. Bootstrap does not seed `/etc/skel` and never touches `display-manager`.
- Not every `mise` backend exposes an artifact checksum. Where none exists the guarantee is a version pin, not integrity.
- Pinning GitHub keys narrows the trust window to plan time; it does not remove the fact that a GitHub account compromise before planning grants shell access. Per-fingerprint approval is what makes that window reviewable.

## Synthesis record

Two architectures were compared. The selected base used a common feature catalog with platform implementations because it keeps package and file ownership near the feature and preserves the existing no-update rule. The competing complete-bundle design contributed complete implementation records, workspace digests, repository allowlists, transaction reapproval, explicit postconditions, and a safer migration order.

The final design rejects arbitrary overlay replacement, a central package-intent registry detached from features, Cachy package installation through `pacman -Syu`, Omarchy's unattended AUR path, and a universal platform class with pass-through methods. The security audit added whole-apply locking, descriptor-based filesystem confinement, staged Git installation, clean AUR builds, planned SSH fingerprints, and deliberately limited rollback.

## Review record

An independent read-only review of the first draft, checked against the installed Omarchy 4.0.1 CLI, the CachyOS wiki and `cachyos-hypr-noctalia` PKGBUILD, Hyprland 0.56.2, the Noctalia docs, `pacman(8)`, and CPython 3.14.7, found the tree shape sound and six blockers. All six are resolved above:

- The root helper was withdrawn. Its installation was never specified and the natural implementation — a script in this user-writable checkout behind a sudoers rule — is a privilege escalation. Fixed-argv `sudo` is smaller and stronger. Its system-file operation had no caller and was deleted.
- The `omarchy pkg add` exemption was withdrawn. It hardcodes `sudo pacman -S --noconfirm --needed`, contradicting the invariant it was exempted from, and no wrapper that hides the transaction can satisfy "review the transaction".
- The Omarchy SSH adapter exemption was withdrawn. It enables `sshd` and opens the firewall before writing any key.
- `ssh-access` became opt-in and visible, enforced by a composition rule rather than by convention.
- `pinned tool` entered the action union. Nine features install code through `mise` with `@latest`, which the first draft neither typed nor pinned while spending twenty lines on seven AUR packages.
- `managed fragment` entered the action union. The Cachy desktop requires writing into distribution-seeded files, which whole-file ownership cannot express without going stale on the next package update.

The review also withdrew four requirements as disproportionate for this repository: the root helper, `openat2` with `RESOLVE_BENEATH` — unavailable from CPython — mandatory `devtools` chroot builds, and `systemd-analyze security` review of the distribution's own units. Btrfs snapshot recording was removed as an unused safety claim.

## First implementation slice

The first slice is narrower than the first draft proposed, because two of the blockers are live defects that ship today whether or not the migration happens.

1. Remove `"ssh-access"` from `core-desktop`'s `requires` and set `visible = true` on `ssh-access`.
2. Replace the `github-ssh` action's call to `omarchy setup security sshd` with the ordered native operation: install `openssh`, write pinned keys atomically to `target_home`, `sshd -t`, enable the service, firewall separately and opt-in.
3. Add the duplicate-package-owner and moving-reference validators to `load_catalog`, then pin the nine `mise` selectors to exact versions.
4. Add `luac -p` over the payload Lua to `scripts/verify-bootstrap.sh`.
5. Then freeze current Omarchy outputs, write the schema-1 to schema-2 normalizer, and implement schema-2 domain types, strict platform detection, and `load_workspace(common, omarchy)` without moving the payload yet.

Steps 1 through 4 are independently verifiable through the existing gate, which passes on the current worktree, so any regression is attributable. Step 5 is complete only when it reproduces the normalized Omarchy plan and rejects a Cachy fixture before any action.
