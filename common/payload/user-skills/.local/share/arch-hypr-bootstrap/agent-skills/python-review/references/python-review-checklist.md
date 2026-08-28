# Python Review Checklist

Use this checklist when the diff includes Python code or Python tests. Apply it pragmatically: consistency within the file and project matters more than blind rule enforcement.

## Review priorities

1. Correctness and regressions
2. Security and unsafe input handling
3. Test coverage and test quality
4. Maintainability and clarity
5. Performance where the change makes it relevant
6. Style, naming, and docs

## Changed-code focus

- Review the modified lines first, then pull minimal surrounding context.
- Do not turn the review into a rewrite of untouched legacy code.
- Raise style findings only when they create inconsistency, confusion, or future maintenance cost.

## Correctness

- Check altered control flow, edge cases, early returns, and error propagation.
- Look for `None` handling mistakes, truthiness bugs, and mutable-default bugs.
- Verify that renamed parameters, changed return values, and exception behavior still match callers and tests.
- Prefer specific exceptions over broad `except Exception:` blocks.
- Watch for hidden behavior changes in refactors that look mechanical in the diff.

## Imports and structure

- Keep imports readable and consistent with project conventions.
- Flag wildcard imports, confusing aliasing, or imports moved into the wrong layer.
- Check whether type-only imports should live under `TYPE_CHECKING`.

## Typing

- Check public or complex functions for clear annotations when the repo uses typing.
- Prefer explicit optionality such as `X | None` over ambiguous defaults.
- Flag annotations that no longer match the actual return type or accepted inputs after the change.

## Naming and readability

- Prefer descriptive names over vague ones like `data`, `value`, or `thing` when scope is broad.
- Check extracted helpers for names that still fit their widened behavior.
- Avoid raising low-value style comments on short-lived local names unless they obscure the logic.

## Documentation and comments

- Check docstrings or comments only when the change modifies behavior, inputs, outputs, or side effects.
- Flag stale comments and misleading docs before missing docs.

## Security

- Look for unsafe SQL construction, shell command interpolation, path traversal, deserialization hazards, and secret leaks.
- Flag uses of `eval`, `exec`, unsafe `yaml.load`, insecure temp-file handling, or trust in external input without validation.
- Treat auth, permissions, token handling, and data exposure issues as high priority.

## Performance

- Check for accidental N+1 queries, repeated expensive work in loops, eager loading of large data, and quadratic string concatenation.
- Only raise performance findings when the changed path is plausibly hot or the regression is obvious from the code.

## Maintainability

- Prefer smaller, intention-revealing helpers when the diff increases branching or nesting substantially.
- Check whether tests cover the new branch conditions and failure modes.
- Flag silent fallback behavior that hides errors unless the codebase explicitly relies on it.

## Quality and readability opportunities

Collect non-blocking locations in changed code that would be worth improving even when they are not merge blockers. Keep them separate from material findings.

- Look for functions or classes that still carry old domain names after extraction or widening.
- Note duplicated logic, overly broad abstractions, hidden side effects, mutation of input arguments, and hardcoded field names where config or existing constants should be used.
- Check whether type annotations are too broad, misleading, or weaker than the implementation contract.
- Identify tests that over-mock behavior, assert only that calls happened, or miss important argument/value assertions.
- Prefer actionable cleanup targets over style preferences: each item should include a precise location and a concrete improvement direction.

## Tests

- Review tests as seriously as production code.
- Check whether new behavior adds or changes:
  - happy path
  - boundary conditions
  - failure cases
  - regression coverage
- If a risky change ships without targeted tests, report that as a separate finding under `tests`.

## Output expectations

- Prioritize material findings with precise `file:line` references.
- Explain why the issue matters, not just which rule it violates.
- If no material problems are found, say that explicitly instead of padding the report with minor nits.
