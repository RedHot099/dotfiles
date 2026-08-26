# Todoist integration architecture

## Problem

Omarchy Shell creates one service plugin but one bar widget for every bar surface. Todoist's official `td` command is a short-lived network client with multiple output shapes and no durable cache. The integration therefore needs one runtime state owner, one boundary that hides `td`, and monitor-local panel state that cannot start competing writes.

## Usage

The shell layout enables one plugin after `omarchy.agents`:

```json
{
  "id": "kuba.tasks"
}
```

Every `Panel.qml` instance reads the same service:

```qml
readonly property var tasks: bar && bar.shell
  ? bar.shell.serviceFor("kuba.tasks")
  : null

function toggleSelectedTask() {
  var task = selectedTask()
  if (!task || tasks.pendingFor(task.id)) return
  if (task.kind === "active") tasks.completeTask(task.id)
  else if (task.reopenable) tasks.reopenTask(task.id)
}
```

The service calls one managed helper with an argument array:

```qml
worker.command = [helperPath, "request", JSON.stringify(request)]
worker.running = true
```

The helper prints exactly one versioned JSON response. QML never invokes `td`, reads its token, parses its output, or reads the cache.

## Shape

### Domain snapshot

```ts
type Priority = "p1" | "p2" | "p3" | "p4"
type TaskKind = "active" | "completed"
type TabId = "all" | "overdue" | "today" | "upcoming" | "noDate" | "completed"

type Task = {
  kind: TaskKind
  id: string
  title: string
  description: string
  url: string
  project: { id: string, name: string | null }
  section: { id: string, name: string | null } | null
  parent: { id: string, title: string | null } | null
  labels: string[]
  priority: Priority
  order: number
  due: {
    date: string
    datetime: string | null
    timezone: string | null
    recurring: boolean
    expression: string | null
  } | null
  completedAt: string | null
  reopenable: boolean
}

type Snapshot = {
  contractVersion: 1
  fetchedAt: string
  active: Task[]
  completed: Task[]
}

type Freshness =
  | { kind: "fresh", fetchedAt: string }
  | { kind: "stale", fetchedAt: string, failedAt: string, reason: string }
```

The bar count is always derived from `snapshot.active.length`. Date buckets are derived in the pure view model so a cached snapshot changes buckets after local midnight without another network response.

### Helper contract

```text
omarchy-todoist snapshot
omarchy-todoist request '<versioned JSON request>'
omarchy-todoist doctor
```

Requests name user intent:

```ts
type Request =
  | { version: 1, requestId: string, operation: "quickAdd", content: string, due: string }
  | { version: 1, requestId: string, operation: "complete", taskId: string }
  | { version: 1, requestId: string, operation: "reopen", taskId: string }
  | { version: 1, requestId: string, operation: "setDue", taskId: string, due: string }
  | { version: 1, requestId: string, operation: "clearDue", taskId: string }
  | { version: 1, requestId: string, operation: "setPriority", taskId: string, priority: Priority }
  | { version: 1, requestId: string, operation: "browse", taskId: string }
  | { version: 1, requestId: string, operation: "completeSeries", taskId: string }
```

The helper validates the request once and maps it to exact `td` argv. `completeSeries` uses `td task complete id:<id> --forever`. Task creation uses `td task add <content> [--due <due>] --json`, so the name and chosen date are sent in one operation. It builds active state from tasks, projects, and sections, and completed state from the last 30 days capped at 50 records.

The private cache lives at `$XDG_STATE_HOME/omarchy/tasks/snapshot-v1.json`, defaults to `~/.local/state`, uses a distinct private schema version, mode `0600`, and atomic replacement. A failed read returns the last valid snapshot as stale. A write is never stored or retried offline.

### Runtime service

`Service.qml` owns the timer, one worker process, FIFO mutation queue, coalesced refresh flag, current snapshot, freshness, errors, per-task pending map, and eight-second undo record.

Public operations are `refresh`, `quickAdd`, `completeTask`, `reopenTask`, `setDue`, `clearDue`, `setPriority`, `browseTask`, `completeSeries`, and `undoLastCompletion`. They are intent methods, not process pass-throughs. The service rejects a second queued or running operation for the same task and uses a separate global pending key for Quick Add.

A mutation leaves the row visible until the helper confirms it and returns a post-write snapshot. Failure preserves the old snapshot. Unknown outcomes never trigger automatic retry.

### Panel and view model

`Panel.qml` owns tab, selection, scroll, editor, menu, and confirmation state. `TaskView.js` is a pure function that returns rows, selectable task IDs, and an index in one call. It owns filtering, grouping, search, sorting, and selection reconciliation.

The popup uses `Style.space(380)` and `KeyboardPanel.fittedContentHeight()` capped at half of the screen height. It uses a `ListView` so a large active list does not instantiate every row. A local key handler distinguishes Enter from Space; arrows and `h/j/k/l` retain the established Omarchy behavior.

## Module map

```text
payload/todoist/.config/omarchy/plugins/kuba.tasks/
  manifest.json
  Service.qml
  Panel.qml
  TaskView.js

home/.local/bin/
  omarchy-todoist

tests/
  test_omarchy_todoist.py
  fixtures/todoist/

scripts/
  verify-todoist-integration.sh
```

## Synthesis decision

Candidate A is the base because its single atomic snapshot keeps cache provenance out of QML and its `buildView` interface is deeper. The cross-judge scored it 27/30 versus 26/30 for candidate B.

The synthesis grafts four parts from B: a hard duplicate-pending guard, a `doctor` command, separate public and private cache versions, and the exact `--forever` command. It also moves date-bucket classification from the helper into the view model so cached tasks cross local midnight correctly.

The segmented public snapshot from B was rejected because `remote|cache|none` leaks storage policy into the panel. A long-running daemon was rejected because Omarchy's service already owns lifecycle and serialization. Direct QML calls to `td` were rejected because they leak transport, credentials, cache, and error policy across every monitor instance.

## Tradeoffs accepted

- We accept a full post-write refresh in exchange for server-confirmed rows without rollback logic.
- We accept one worker at a time in exchange for deterministic mutation order across monitors.
- We accept one larger Python helper in exchange for one place that owns every `td` and cache invariant.
- We accept polling every 60 seconds in exchange for no webhook endpoint or additional daemon.
- We accept one all-or-nothing snapshot in exchange for a smaller public contract.

## Verification contract

- Helper tests freeze the clock, replace `td` with a deterministic fake, and isolate the state directory.
- Tests assert exact argv for quotes, newlines, leading dashes, and shell-looking Quick Add text.
- Fixtures cover active and completed normalization, project and parent enrichment, recurring reopen restrictions, cache fallback, invalid IDs, Quick Add argument safety, and browser freshness.
- The verification script checks manifest JSON, shell placement, executable permissions, helper tests, QML parsing where available, active helper state, and shell logs.
- The approved live test creates one task, records its ID, changes due date and priority, completes and reopens it, then deletes only that exact ID.

## Implementation status

The helper, service, panel, view model, manifests, and verification scripts are installed. The live test created one task, changed its due date and priority, completed it, reopened it, and deleted the exact created ID.
