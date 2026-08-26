# Use Todoist in Omarchy Shell

The `kuba.tasks` widget shows the number of active Todoist tasks in the right side of the bar. It sits after `omarchy.agents`. Click the widget to open the task panel.

## Navigate the panel

Use these keys while the panel is open:

- Press Left, Right, `h`, or `l` to change the filter.
- Press Up, Down, `j`, or `k` to select a task.
- Press Enter or `o` to open the selected task in Todoist.
- Press Space or `x` to complete an active task or reopen a completed task.
- Press `a` to open the task-name form. Type the task name, press Enter or click **Dalej**, then choose its due date. The complete task is sent to Todoist in the background only after that choice.
- Press `/` to search task titles, descriptions, projects, parents, and labels.
- Press `d` to change the due date.
- Press `p` to change the priority.
- Press `m` to open the task action menu and focus its first action.
- In an open button menu, press `h` or `k` to focus the previous action. Press `l` or `j` to focus the next action. The arrow keys work the same way, and Enter activates the focused action.
- Press `r` to refresh the snapshot.
- Press Escape to close an editor, clear the search, or close the panel.

The panel ignores completion and browser keys for one second after it opens. This guard prevents a key intended for the previous window from changing a task.

## Work with task state

The panel refreshes every 60 seconds, when you open it, and after a write. A pending row keeps its place and shows a spinner until Todoist confirms the write.

If a refresh fails, the panel shows the last cached snapshot. It does not queue writes while the account is offline. Omarchy Shell does not send Todoist notifications, so the Android app remains the only notification source.

The Completed filter contains up to 50 tasks from the last 30 days. You can reopen a normal completed task. Todoist does not support reopening one completed occurrence of a recurring task.

## Check the integration

Run the local checks from the dotfiles repository:

```bash
scripts/verify-todoist-integration.sh --live
```

Check the Todoist CLI and account separately:

```bash
~/.local/bin/omarchy-todoist doctor
```

If `doctor` reports `AUTH_REQUIRED`, sign in again:

```bash
td auth login
```

Todoist stores the OAuth token in the system credential manager. The cache at `~/.local/state/omarchy/tasks/snapshot-v1.json` contains task data but no token. The helper writes the cache with mode `0600`.
