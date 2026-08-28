# Branch Review Principles

These principles synthesize the patterns reflected in current Codex skill guidance, Codex prompting guidance, and public code-review skill examples.

## Diff-first review

- Start from the branch diff and commit list, not from a full-repo scan.
- Use changed files to decide what additional context to read.
- Favor merge-base semantics for branch review because it matches PR intent better than tip-to-tip diffs.

## Narrow contract

- This skill exists to review branch changes and produce a report.
- Do not expand into implementation, autofix, or whole-repo auditing unless the user explicitly asks.
- Keep the workflow predictable: collect context, inspect the diff, verify findings, report.

## Report-first workflow

- The primary output is a review report, not code changes.
- Findings should be specific, actionable, and severity-ordered.
- If there are no material issues, say so plainly.

## Progressive disclosure

- Load only the instructions needed for the current diff.
- Use the Python checklist only when Python is involved.
- Pull extra file context only when a suspected issue needs verification.

## Findings over summaries

- Spend most of the report on validated issues, not generic commentary.
- Avoid long summaries that do not change the author's next action.
- Prefer fewer high-signal findings over many shallow observations.

## Severity discipline

- `critical`: severe correctness or security failure, likely blocker
- `high`: material risk that should block merge until resolved
- `medium`: meaningful but non-blocking issue
- `low`: optional improvement or minor inconsistency

## Avoid style-only noise

- Do not nitpick formatting or personal preferences when linters or project conventions already cover them.
- Raise style issues only when they harm readability, consistency, or maintainability in the changed code.

## Evidence before assertion

- Verify a suspected issue against surrounding code, nearby tests, and call sites when needed.
- Do not report hypothetical bugs without grounding them in the actual change.
