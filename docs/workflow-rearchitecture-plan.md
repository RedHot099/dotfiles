# Three-step bootstrap architecture

## Status

This document is a design checkpoint. Commit `21bc56b` is the tested baseline. Do not start the migration until the user approves this plan.

## Problem

The current repository builds one platform-wide catalog and one global plan. Broad features mix application installation, desktop configuration, agents, cloud services, and authentication. The new design exposes three independent workflows:

1. `packages` installs applications, command-line tools, runtimes, and technical dependencies.
2. `desktop` configures the monitor, Hyprland, the Omarchy Shell bar, workspaces, bindings, themes, Calendar, and selected application startup.
3. `integrations` configures agents, skills, MCP servers, plugins, cloud services, Todoist, SSH access, Tailscale, and Bitbucket instructions.

`setup` runs the same workflows in that order. A skipped workflow does not stop later workflows.

The migration removes profiles, Gum, the flat feature picker, and the old directory model. It does not preserve compatibility with old plans or commands.

## User-facing contract

The public CLI is interactive, terminal-only, and English:

```text
./bootstrap setup
./bootstrap packages plan|apply|audit
./bootstrap desktop plan|apply|audit
./bootstrap integrations plan|apply|audit
```

There are no `--yes`, `--defaults`, `--select`, or headless public modes. Tests call the internal planner and executor APIs directly.

`setup` follows this sequence:

```text
Welcome and host check
→ package selection
→ sudo -v before package apply
→ repository and AUR review
→ package installation
→ desktop selection
→ monitor preview
→ desktop apply and Hyprland reload
→ integrations selection
→ skill and harness selection
→ authentication queue
→ final status
```

Each workflow saves its last selection. A new machine uses catalog defaults. A later run starts with the last selection.

The summary uses these statuses:

```text
Packages       READY
Desktop        READY
Integrations   NEEDS LOGIN
Overall        INCOMPLETE
```

`SKIPPED` records a user choice. `NEEDS PACKAGES` records an unmet prerequisite. `NEEDS LOGIN` records deferred authentication. `FAIL` is reserved for failed mutations or postconditions.

## Terminal interface

Replace Gum with a small Python terminal application based on the standard library. The terminal engine is specific to this repository, not a general UI framework.

The selector supports:

- arrow keys and `j` or `k` to move;
- `Space` to toggle one item or a complete group;
- `a` to select all visible items;
- `n` to clear all visible items;
- `/` to search every group, including collapsed groups;
- right and left arrows to expand or collapse a group;
- `Enter` to continue;
- `Esc` to return to any earlier screen before apply starts;
- a footer that always shows the available keys.

The terminal adapter restores terminal state after success, failure, resize, `SIGINT`, and `SIGTERM`. Apply screens do not offer Back. An interrupted apply can resume from its journal.

Installed applications stay visible, selected, and marked `installed`. Clearing an installed application never removes it.

## Repository layout

```text
bootstrap
lib/bootstrap/
  cli.py
  domain.py
  host.py
  platform.py
  repository/
    compiler.py
    model.py
    schema.py
    provenance.py
  workflows/
    packages.py
    desktop.py
    integrations.py
    setup.py
  planning/
    model.py
    projector.py
  execution/
    executor.py
    audit.py
  state.py
  packages.py
  skills.py
  files.py
  tui/
    terminal.py
    model.py
    selector.py
    review.py
    screens.py

packages/
  common/
    catalog/applications/<id>.toml
    catalog/groups.toml
    requirements/<id>.toml
  omarchy/packages.toml

desktop/
  common/
    catalog/features/<id>.toml
    implementations/<id>.toml
    payload/<feature>/...
    hardware/...
  omarchy/
    implementations/<id>.toml
    payload/<feature>/...

integrations/
  common/
    catalog/integrations/<id>.toml
    implementations/<id>.toml
    payload/<integration>/...
    agents/...
    skills/private/<skill>/...
    skills/sources.toml
    skills/groups.toml
    harnesses.toml
  omarchy/
    implementations/<id>.toml
    payload/<integration>/...
```

Each workflow owns its vocabulary and payload. Within each workflow, `common` holds content that does not depend on Omarchy APIs, and `omarchy` holds the Omarchy 4 implementations. An Omarchy implementation is a complete alternative, never a partial overlay.

## Compiled repository model

One compiler reads all three physical trees and produces one immutable repository model for Omarchy 4. The verification gate compiles it.

```python
class WorkflowId(StrEnum):
    PACKAGES = "packages"
    DESKTOP = "desktop"
    INTEGRATIONS = "integrations"

@dataclass(frozen=True)
class FeatureId:
    workflow: WorkflowId
    name: str

@dataclass(frozen=True)
class RepositoryModel:
    platform: PlatformId
    packages: PackagesModel
    desktop: DesktopModel
    integrations: IntegrationsModel
    package_bindings: Mapping[PackageRequirementId, PackageBinding]
    source_digest: Sha256

def compile_repository(root: Path, platform: PlatformId) -> RepositoryModel:
    raise NotImplementedError
```

The compiler hides parsing, common and platform composition, validation, provenance, and hashing. Workflow projectors receive domain objects, not TOML dictionaries.

The compiler validates the entire repository before the TUI presents a choice. It rejects:

- missing or duplicate workflow implementations;
- dependency cycles or invalid dependency direction;
- package ownership outside `packages`;
- missing, unused, or unapproved package bindings;
- duplicate file targets across workflows;
- platform APIs in portable payloads;
- unsafe units, firewall rules, paths, symlinks, Git URLs, or commits;
- secret-like repository files;
- duplicate skill IDs or protected harness targets.

Dependencies are one-way. `desktop` and `integrations` may declare package prerequisites. `packages` cannot depend on either workflow. `desktop` and `integrations` do not invoke each other.

## Independent typed plans

The repository model is shared. Requests and plans are workflow-specific so invalid combinations cannot enter the executor.

```python
@dataclass(frozen=True)
class PackagesRequest:
    applications: frozenset[ApplicationId]

@dataclass(frozen=True)
class DesktopRequest:
    features: frozenset[DesktopFeatureId]
    monitor: MonitorChoice

@dataclass(frozen=True)
class IntegrationsRequest:
    integrations: frozenset[IntegrationId]
    agents: frozenset[AgentId]
    skills: frozenset[SkillId]
    harnesses: frozenset[HarnessId]

@dataclass(frozen=True)
class PackagesEvidence:
    selection_digest: Sha256
    installed: tuple[ExactPackageIdentity, ...]

@dataclass(frozen=True)
class PackagesPlan:
    header: PlanHeader
    request: PackagesRequest
    actions: tuple[PackageAction, ...]

@dataclass(frozen=True)
class DesktopPlan:
    header: PlanHeader
    request: DesktopRequest
    package_evidence: PackagesEvidence
    actions: tuple[DesktopAction, ...]

@dataclass(frozen=True)
class IntegrationsPlan:
    header: PlanHeader
    request: IntegrationsRequest
    package_evidence: PackagesEvidence
    resolved_skills: ResolvedSkillSet
    actions: tuple[IntegrationAction, ...]
```

Persisted selection records intent. `PackagesEvidence` and live probes prove that prerequisites exist. Apply rechecks both. A stale state file cannot satisfy a desktop or integration prerequisite.

Only `PackagesPlan` can contain repository, AUR, or mise installation actions. `DesktopPlan` can contain user files, generated files, themes, and a Hyprland reload. `IntegrationsPlan` can contain allowlisted configuration files, skills, authentication, user units, reviewed system units, SSH access, and UFW rules.

The serialized plan remains the reviewed boundary. Every plan includes its workflow, target home, UID, platform fingerprint, repository digest, workflow digest, selection digest, resolved package facts, resolved remote content, and plan digest.

## Shared executor and audit

Keep one closed action union, one executor, one descriptor-safe file layer, and one global apply lock. Three executors would duplicate the most sensitive code and allow safety policy to drift.

The executor accepts one validated workflow plan and dispatches only its allowed action variants. Catalogs cannot express raw shell commands or arbitrary privileged arguments.

Keep these existing guarantees:

- never use `pacman -Sy`, `--noconfirm`, package removal, downgrade, rollback, lock deletion, or repository edits;
- install repository packages in one reviewed transaction;
- pin every AUR recipe to a full commit and verify every source file;
- build AUR packages unprivileged in a clean environment;
- pass only verified local artifacts through `sudo pacman -U`;
- use fixed absolute argv arrays for privileged actions;
- keep explicit system-unit and firewall allowlists;
- write target-home files atomically and reject path or symlink escape;
- record an action only after its postcondition passes;
- make a second apply change zero files;
- keep audit read-only.

The global lock prevents package, file, and systemd mutations from different workflows from running concurrently.

Add a dedicated `HyprlandReloadAction`. On an active target session, apply runs `hyprctl reload` and then `hyprctl configerrors`. Any configuration error marks Desktop `FAIL`. Outside an active session, the final report instructs the user to enter the Hyprland UWSM session.

## State and resume

```text
~/.local/state/arch-hypr-bootstrap/
  selections/packages.json
  selections/desktop.json
  selections/integrations.json
  plans/packages/<digest>.json
  plans/desktop/<digest>.json
  plans/integrations/<digest>.json
  journals/packages/<digest>.json
  journals/desktop/<digest>.json
  journals/integrations/<digest>.json
  skills/lock.json
```

State writes use private directories, same-directory temporary files, `fsync`, and `os.replace`. Selections, plans, journals, and skill locks have separate schemas.

The journal is a recovery hint, not proof of current state. Apply probes the postcondition before skipping an action. `setup` aggregates workflow results and does not create a fourth source of state.

## Curated package catalog

The selector shows individual applications under toggleable groups. Technical dependencies appear only during review.

Default applications:

- Browsers: Google Chrome and Chromium.
- Editors: Visual Studio Code, Neovim, Cursor, and T3 Code.
- Communication: Caprine, Signal, and Vesktop.
- Media: Spotify.
- Notes and documents: Obsidian and Typora.
- Gaming: Steam.
- System tools: Tailscale.
- Development tools: mise, GitHub CLI, AWS CLI, and Rust.

Available but off by default:

- Media: LosslessCut.
- Notes and documents: LaTeX with Biber.
- System tools: Filelight, Solaar, and CoolerControl.

Hardware detection may add a compatibility hint for Solaar or CoolerControl. It never selects them automatically.

Remove Gemini CLI, GitHub Copilot CLI, Grok CLI, and Crush from the curated catalog. Cursor Agent remains distinct from the Cursor editor.

## Desktop ownership

Desktop owns:

- monitor detection, mode, scale, and preview;
- Hyprland appearance, workspaces, window rules, and keybindings;
- Omarchy Shell;
- launcher, clipboard, screenshots, panels, theme, and wallpaper;
- application bindings, rules, and startup generated from the saved Packages selection;
- Google Calendar.

Omarchy keeps the current Calendar Snooze behavior.

Desktop never installs a package. If prerequisites are missing, it offers to open Packages with the missing applications preselected. Declining marks Desktop `NEEDS PACKAGES` or `SKIPPED`.

Desktop does not add Waybar, Mako, or a second idle or lock daemon.

## Integration ownership

Integrations owns:

- Claude Code, Codex, OpenCode, and Cursor Agent settings and authentication;
- shared MCP and skill selection;
- harness-specific models, permissions, sandbox settings, and plugins;
- Google Drive and OneDrive through rclone;
- Todoist CLI, authentication, helper, and cache;
- the Todoist widget;
- GitHub SSH access and public keys;
- reviewed `sshd.service`, `tailscaled.service`, and UFW configuration;
- Bitbucket SSH key upload;
- AWS CLI, Docker Hub, and 1Password logins.

Packages installs all required binaries. Integrations starts cloud units only after their authentication probes pass.

Bitbucket installs no separate client. It requires Git and OpenSSH and stores no Bitbucket token. Its login copies the machine's SSH key, opens the Bitbucket SSH key page, and makes one SSH connection that records the host key in the user's `known_hosts`; the repository stores no key, host fingerprint, or `known_hosts` entry. Its check uses SSH batch mode and writes nothing. The separate SSH key login creates `~/.ssh/id_ed25519` with `ssh-keygen` only after the user approves it.

The authentication queue lists every selected login. An `order` value in the catalog runs the SSH key, GitHub, and Bitbucket logins first; the rest follow by feature. Skipping, cancelling, or failing one login continues to the next and produces `NEEDS LOGIN`.

## Skill supply chain

Private skills live under `integrations/common/skills/private/`. They may include instructions and supporting files but no credentials, sessions, histories, tokens, or private keys.

Each public skill has one explicit HTTPS Git URL and safe subdirectory in `sources.toml`. During Integrations planning, the resolver:

1. fetches the latest remote commit into isolated staging;
2. rejects submodules, Git LFS pointers, path escape, unsafe symlinks, missing `SKILL.md`, secret-like files, and duplicate IDs;
3. enforces per-source limits before rendering a diff;
4. records every file hash and executable bit;
5. shows the URL, old and new commits, changed files, executable files, and expandable diff;
6. aborts the complete skill operation if any selected source fails;
7. writes the accepted revisions only to the machine-local lock after successful installation.

Initial limits are 2,000 files, 50 MiB of materialized content, and 2 MiB of rendered diff per source. A limit failure asks the user to narrow or split the source. These values remain named constants with boundary tests.

Apply fetches the exact reviewed commit and verifies every byte. "Latest" applies at plan time, never after review.

The user selects one grouped skill set for all selected harnesses:

- `~/.agents/skills`;
- `~/.claude/skills`;
- `~/.codex/skills`;
- `~/.config/opencode/skills`;
- `~/.cursor/skills`.

Canonical immutable content lives under bootstrap-managed state. Harness entries are relative links to the canonical content. Before replacement, the review lists every colliding path. Apply deletes same-name collisions without backup, as explicitly chosen. It removes stale links previously managed by this repository. It preserves unknown noncolliding skills, Codex `.system`, Cursor `skills-cursor`, and packaged namespaces.

## Migration sequence

Each phase ends with a testable repository state. Temporary adapters may exist on the migration branch, but none ship in the final architecture.

### Phase 1: freeze behavior and add the compiler shell

- Keep `21bc56b` as the comparison baseline.
- Capture normalized plans and payload hashes.
- Add failing compiler tests and type shells for `RepositoryModel`, the three requests, and the three plans.
- Compile read-only rearranged fixtures before moving production files.

Exit check: the fixtures compile, unsafe fixtures fail with source paths, and the existing gate still passes.

### Phase 2: migrate Packages

- Move application and tool intent into `packages/common`.
- Move the provider map into `packages/omarchy/packages.toml`.
- Add Chromium and Neovim as first-class applications.
- Remove profiles and the four unused agents.
- Preserve repository transaction and AUR behavior exactly.

Exit check: curated defaults match this document, every requirement resolves, transaction snapshots are stable, and no non-Packages plan can express package mutation.

### Phase 3: migrate Desktop

- Split desktop behavior out of `core-desktop`, `session-autostart`, Calendar, and broad platform payloads.
- Move monitor generation and hardware hints into Desktop.
- Generate application-specific bindings, rules, and startup from Packages selection.
- Preserve the Omarchy Shell implementation.
- Add the Hyprland reload and config-error postcondition.

Exit check: Desktop plans deterministically, isolated second apply changes zero files, Lua and TOML checks pass, and missing packages produce `NEEDS PACKAGES`.

### Phase 4: migrate Integrations

- Split agents, cloud, Todoist, SSH, Tailscale, UFW, and Bitbucket from existing broad features.
- Inventory and encode the actual MCP, plugin, model, permission, and sandbox settings for the four selected agents.
- Keep secrets and auth stores outside the repo.
- Move private skills and add explicit public skill sources.
- Implement staged all-or-nothing skill installation for all five harness roots.

Exit check: deferred authentication produces `NEEDS LOGIN`, authenticated cloud units start, Bitbucket owns no credentials or host keys, collision tests preserve protected and unrelated skills, and one failed public source leaves every harness untouched.

### Phase 5: replace the CLI

- Implement the pure selector reducer and terminal adapter.
- Add workflow screens, review screens, authentication queue, resume, and summary.
- Replace Gum and the flat CLI only after terminal restoration tests pass.
- Keep setup as an orchestrator over the three real workflows.

Exit check: recorded key streams prove item and group Space toggles, search, folding, Back, installed markers, hardware hints, resize, interrupts, and English copy.

### Phase 6: remove the old model

- Delete the old top-level platform trees.
- Delete profiles, broad `core-desktop` and `ai-development`, Gum, schema-2 compatibility parsing, and old CLI adapters.
- Update `AGENTS.md`, README, docs, and the verification gate.
- Add a migration decision log.

Exit check: no old loader or path remains, the repository compiles, all three workflows plan and audit independently, and repository-wide ownership validation passes.

### Phase 7: acceptance

- Run every Python, schema, shell, Lua, TOML, QML, Todoist, rclone, and T3 safety test.
- For each workflow, plan deterministically, apply to an isolated home twice, require zero changes on the second apply, and audit without writes.
- Interrupt and resume each workflow at a verified action boundary.
- Run a real Desktop apply only with explicit approval. Require a successful Hyprland reload and no `hyprctl configerrors`.
- Run `git diff --check` and inspect every changed file.

## Synthesis decision

The compiled repository candidate is the base because it gives the repository one validated source of truth while keeping three independent workflow projections. The alternative with three workspace classes had stronger invalid-state prevention but repeated loader, planner, and audit surfaces.

This plan adopts the strongest parts of that alternative:

- workflow-specific request and plan types;
- `PackagesEvidence` with live revalidation;
- an explicit allowed action set for each workflow;
- digest-addressed plans and journals;
- staging all skills before any harness mutation;
- one immutable canonical skill materialization.

It rejects three independent executors, three autonomous loaders, a generic workflow plugin system, and one global plan with optional workflow sections. Each option either duplicates safety code or recreates the current mixed ownership.

## Tradeoffs accepted

- We compile the complete repository for one command so cross-workflow errors fail before selection.
- We keep three projectors so workflow rules do not become compiler conditionals.
- We maintain a small terminal engine to obtain the requested navigation and deterministic UI tests.
- Public skill planning depends on the network and current remote HEAD. Apply remains tied to the exact reviewed commit and hashes.
- A public skill source failure aborts the complete skill operation.
- Same-name user skills are deleted without backup after exact-path review.
- The public CLI cannot run headlessly. Internal APIs remain testable.
- Package updates and rollbacks remain the responsibility of the installed distribution.

## Approval checkpoint

Approval authorizes implementation of Phases 1 through 7 in order. Any repeated need to bypass the typed workflow boundaries, duplicate package policy, or add generic escape hatches invalidates this design and requires a new checkpoint.
