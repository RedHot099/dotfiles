---
name: jira-task-from-diff
description: Generate a concise Jira task description from the current git branch diff against master, including committed and local working-tree changes. Use when Codex needs to draft Objective, Background, Acceptance Criteria, Affected Areas, and How to Test from branch changes for Jira or ticket planning.
---

# Jira Task From Diff

Generate a short, business-facing Jira task from the current branch diff against `master`. Include committed changes and local working-tree changes, compare against `origin/master` only when local `master` is unavailable, and write the final answer as paste-ready Jira content.

## Workflow

1. Run the bundled collector from the repository being described:

```bash
bash scripts/collect-jira-task-context.sh
```

The collector is read-only and does not run `git fetch`; use the locally available `master` or `origin/master`.

2. Inspect `JIRA_TASK_RANGE`, `BRANCH`, `COMMITS`, `CHANGED_FILES`, `DIFFSTAT`, `DIFF`, `WORKTREE_STATUS`, `WORKTREE_CHANGED_FILES`, `WORKTREE_DIFFSTAT`, and `WORKTREE_DIFF`.
3. Read changed files or nearby tests only when the collected context is not enough to understand the behavior.
4. Infer the business goal only from evidence in code, changed paths, tests, commit messages, branch name, docs, or user-provided context.
5. If the diff does not support a credible Objective or Background, ask the user for the missing business context before producing the Jira task.
6. Final response must contain only the Jira task body. Do not add a preface, source notes, caveats, or follow-up text.

## Writing Rules

- Write in English.
- Keep labels in English and bold.
- Start the final task with a standalone bold `Description:` label.
- Use `Background`, not `desc`, while treating it as the problem or missing-capability description.
- Keep the Objective to 2-3 concise sentences describing the main business goal.
- Keep the Background to at most 2 concise sentences describing the current problem, gap, or reason the change is needed.
- Keep Acceptance Criteria as specific, concise completion conditions.
- Keep Affected Areas as a short abstract solution path, such as `OCR/parsing`, not a full file list.
- Keep How to Test to at most 3 test cases.
- Make each test case one sentence with the expected outcome included.
- Avoid implementation-heavy wording unless the branch is purely technical.
- Do not invent product intent, user impact, or external requirements that are not supported by evidence.

## Output Format

Use exactly this structure, without wrapper tags:

```markdown
**Description:**
- **Objective:** [2-3 concise sentences describing the main business goal of the ticket.]
- **Background:** [Maximum 2 concise sentences describing the current problem, missing capability, or reason this change is needed.]
- **Acceptance Criteria:**
  - [Specific condition required for the ticket to be complete.]
  - [Specific condition required for the ticket to be complete.]
- **Affected Areas:** [Short abstract solution path, for example `OCR/parsing`.]
- **How to Test:**
  - **Test Case 1:** [One sentence describing the test and expected outcome.]
  - **Test Case 2:** [One sentence describing the test and expected outcome.]
  - **Test Case 3:** [One sentence describing the test and expected outcome.]
```
