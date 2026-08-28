# Todoist integration grounding

## Confirmed product contract

- The bar shows a Todoist icon and the count of every active task.
- The popup sits after `omarchy.agents`, uses the standard panel width, and is capped at 50% of the screen height.
- Tabs are `All`, `Overdue`, `Today`, `Upcoming`, `No date`, and `Completed`.
- `All` groups active tasks by the first five date buckets. The other tabs are flat filtered lists.
- The panel supports keyboard navigation, search, Polish Smart Quick Add, completion, reopen, due-date changes, priority changes, browser opening, and confirmed completion of a recurring series.
- Completed history covers 30 days and at most 50 tasks. A recurring occurrence cannot be reopened through Todoist and must not expose a fake action.
- Reads refresh every 60 seconds, when the panel opens, and after a confirmed mutation.
- A failed read returns the last successful cache as stale. Writes are never queued offline.
- One Google-SSO Todoist account is authorized through the official CLI. The token stays in Secret Service.

## Existing Omarchy Shell flow

1. `~/.config/omarchy/shell.json` is the complete user configuration. It is not deep-merged with defaults.
2. `PluginRegistry` scans `~/.config/omarchy/plugins/<id>/manifest.json` and registers enabled `bar-widget` and `service` entry points.
3. The shell creates one service instance, but `ModuleSlot` creates one bar-widget instance per bar surface and monitor.
4. `ModuleSlot` injects `bar`, `moduleName`, and the non-`id` fields from the layout entry as `settings`.
5. `Panel` owns popup lifecycle. `KeyboardPanel` owns focus, geometry, and dismissal. Standard `PanelKeyCatcher` does not distinguish Enter from Space.
6. Saving a user plugin triggers a full plugin rescan and component-cache clear.

## Required ownership

- `Service.qml` is the single runtime owner of snapshot state, refresh timers, mutation serialization, stale/error state, and undo metadata.
- `Panel.qml` owns only presentation, per-panel tab/selection/scroll state, editors, and keyboard dispatch.
- A helper process is the only boundary that knows the official `td` wire format, command quirks, filesystem cache schema, or process exit behavior.
- The helper must receive an argument array, never shell-concatenated user input.
- QML consumes one stable JSON contract and never reads credentials.

## Official CLI constraints

- Package: `@doist/todoist-cli` 3.3.1 or compatible, Node 24+.
- OAuth PKCE opens a browser. On Linux the CLI stores the token in Secret Service.
- Active snapshot inputs: `td task list --all --json --show-urls`, `td project list --all --json`, `td section list --all --json`.
- Completed input: `td completed list --since <inclusive> --until <exclusive> --all --json --full --show-urls`.
- Smart Quick Add must use `td add` or `td task quickadd`; `td task add` does not parse the content. The panel intentionally uses explicit task creation instead, because it collects the name and due date in separate local UI steps and submits both together.
- `complete`, `uncomplete`, and `browse` do not support JSON output. The helper validates non-empty `id:<id>` references and refreshes after mutation.
- Normal completion advances a recurring task. Reopening a particular recurring occurrence is unsupported.
- The CLI has no durable task cache, offline write queue, or watch mode.

## Persistence and safety

- The Omarchy plugin lives under `omarchy/payload/todoist/.config/omarchy/plugins/kuba.tasks/`. The portable helper lives under `common/payload/todoist-helper/`.
- The active equivalent lives under `~/.config/omarchy/plugins/kuba.tasks/`; no Omarchy-owned source is edited.
- The Omarchy 4 payload uses the stock `omarchy.agents` widget and inserts `kuba.tasks` after it.
- The existing dirty worktree belongs to the user. Only Todoist integration lines and files may change.

## Design rubric

1. One runtime owner prevents duplicate refreshes and conflicting mutations across monitors.
2. QML sees a small domain contract and no raw `td` output, credential, cache, or subprocess policy.
3. Every agreed operation has an explicit success, pending, failure, offline, and recurring-task behavior.
4. The design fits Omarchy's plugin lifecycle and existing UI components without editing packaged sources.
5. The implementation remains small enough to verify with deterministic helper tests and a live plugin check.
6. Installation and dotfiles persistence preserve current user configuration and secrets.
