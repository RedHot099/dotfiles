# Report Template

Use this structure for final output. Keep it concise when the diff is small, but preserve the same section order.

## With findings

```md
## Summary
- Overall assessment: Good / Fair / Needs changes
- Scope reviewed: `<head>` against `<base>`
- Main risks: short list of the most important themes

## Detailed Findings
### [high] [correctness] `path/to/file.py:123`
Description of the issue.

Impact / risk: What can break and why it matters.

Recommendation: Concrete fix direction.

### [medium] [tests] `tests/test_feature.py:45`
Description of the test gap or weakness.

Impact / risk: What regression could slip through.

Recommendation: What scenario should be covered.

## Code Quality Improvement Opportunities
1. `path/to/file.py:123` - Briefly name the weak spot.
   Why it is weaker: Explain the readability, maintainability, typing, naming, structure, or test-quality concern.
   Improvement direction: Give a concrete next step without rewriting the whole change.

2. `path/to/other.py:45` - Another non-blocking cleanup target.
   Why it is weaker: Explain the issue.
   Improvement direction: Concrete fix direction.

## Positive Highlights
- Strong patterns worth keeping
- Good tests, clear refactor, safe migration path, etc.

## Open Questions / Risks
- Anything that could not be fully verified from the diff
- Assumptions that may need author confirmation

## Verdict
- `approve` when there are no material findings
- `comment` when there are only low/medium suggestions
- `request changes` when any critical/high finding exists
```

## No material findings

```md
## Summary
- Overall assessment: Good
- Scope reviewed: `<head>` against `<base>`
- No material correctness, security, or test issues found in the reviewed diff.

## Detailed Findings
- No material findings.

## Code Quality Improvement Opportunities
- List changed-code locations that could be improved for readability or maintainability, or `None`.

## Positive Highlights
- Mention 1-3 strengths from the diff.

## Open Questions / Risks
- Note any residual uncertainty briefly, or `None`.

## Verdict
- `approve`
```

## Notes

- Prefer `file:line` references whenever possible.
- Use categories from this skill: `correctness`, `security`, `tests`, `maintainability`, `performance`, `style`, `docs`.
- When local changes are included, describe the scope as `<head> + working tree` against `<base>`.
- Do not inflate `Detailed Findings` with low-value nitpicks when the meaningful outcome is “no material findings.” Put useful non-blocking readability and maintainability targets in `Code Quality Improvement Opportunities` instead.
- Quality opportunities should be specific enough to act on: cite the location, name the weakness, and give an improvement direction.
