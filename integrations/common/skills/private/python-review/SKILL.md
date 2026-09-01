---
name: python-review
description: Review changes on the current branch or a specified branch against another branch, defaulting to `master`, with a Python-first code review workflow. By default, reviews of the current checkout also include staged, unstaged, and untracked local changes. Use when Codex needs to review a git diff between branches or the current working tree, inspect changed Python files and tests, check for correctness, regressions, security issues, test gaps, maintainability problems, or produce a full review report for a branch before merge, including a separate list of code-quality and readability improvement opportunities.
---

# Python Review

Review branch diffs with a report-first workflow. Focus on changed code, verify findings against nearby context, and prioritize correctness, regressions, security, and tests before style. By default, review of the current branch also includes staged, unstaged, and untracked local changes from the current checkout.

## Workflow

1. Collect the review range and diff context.
   - Run `scripts/collect-review-context.sh` from the target repository.
   - Default to `--base master --head HEAD`.
   - Default behavior is `--working-tree auto`, which includes local staged, unstaged, and untracked changes when `--head` resolves to the current `HEAD` commit.
   - If the user specifies another branch pair, pass those refs explicitly.
   - If the user wants a committed-only review, pass `--working-tree no`.

2. Inspect only the relevant files first.
   - Start from `CHANGED_FILES`, `DIFFSTAT`, and `DIFF`.
   - When present, also review `WORKTREE_STATUS`, `WORKTREE_CHANGED_FILES`, `WORKTREE_DIFFSTAT`, and `WORKTREE_DIFF`.
   - Read the changed files plus the smallest amount of surrounding code or related tests needed to verify a suspected issue.
   - Stay diff-first. Do not drift into a full repo audit unless the user explicitly asks for one.

3. Load references only when needed.
   - Read `references/python-review-checklist.md` when the diff includes `.py`, Python tests, or Python-heavy config.
   - Read `references/branch-review-principles.md` for large, mixed-language, or ambiguous diffs.
   - Read `references/report-template.md` before writing the final report.

4. Review for material issues and quality opportunities.
   - Prioritize: correctness, regressions, security, test coverage gaps, broken assumptions, maintainability, performance.
   - Treat style and docs as lower priority unless they hide a bug, break consistency, or materially hurt maintainability.
   - Do not report a finding until you verify it against file context and, when relevant, nearby tests or call sites.
   - Separately collect changed-code locations that are weaker from a quality/readability perspective even when they do not block merge. Include precise `file:line` references and a concrete improvement direction.

5. Produce a full report.
   - Use the structure from `references/report-template.md`.
   - Include `file:line` for each finding whenever you can ground it precisely.
   - Include a "Code Quality Improvement Opportunities" section after material findings. Keep it focused on actionable maintainability, readability, naming, structure, typing, docs, and test-quality improvements in the reviewed diff.
   - If there are no material problems, say so explicitly and explain any residual risk briefly.

## Review Rules

- Focus on changed code, not unrelated legacy debt.
- Do not nitpick personal preferences when linters or project conventions already settle the question.
- Prefer findings over summaries. The report is useful only when it identifies actionable issues or clearly states there are none.
- Keep material findings and quality opportunities separate:
  - `Detailed Findings` are defects, regressions, security issues, missing tests, or maintainability problems that materially affect merge readiness.
  - `Code Quality Improvement Opportunities` are non-blocking cleanup targets in changed code that would improve readability, structure, typing, naming, or test strength.
- Keep severity honest:
  - `critical`: likely production break, data loss, auth/security hole, or severe regression
  - `high`: substantial correctness, security, or missing-test risk
  - `medium`: meaningful maintainability, performance, or edge-case issue
  - `low`: worthwhile but non-blocking improvement
- Keep verdicts simple:
  - `approve`: no material findings
  - `comment`: only low/medium suggestions
  - `request changes`: any critical/high findings

## Commands

Default review:

```bash
bash scripts/collect-review-context.sh
```

Default review without local uncommitted changes:

```bash
bash scripts/collect-review-context.sh --working-tree no
```

Review against another base:

```bash
bash scripts/collect-review-context.sh --base origin/master
```

Review one branch against another:

```bash
bash scripts/collect-review-context.sh --base release/1.4 --head feature/x
```

Use the emitted `REVIEW_RANGE`, `COMMITS`, `CHANGED_FILES`, `DIFFSTAT`, and `DIFF` sections as the starting point for the review. When `working_tree_included: yes`, include the `WORKTREE_*` sections in the review scope as well.
