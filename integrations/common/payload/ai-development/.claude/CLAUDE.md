# Personal agent settings

## Council

Council members, in this order, at high reasoning effort:

1. GPT Sol (latest, Codex)
2. Claude Opus (latest, Claude)
3. GLM (latest, Cursor). When Cursor has no usage left for external models, use the latest Grok on xhigh with fast mode instead.

Resolve exact model IDs with `orchestrator_capabilities` each time. The same members sit in the `judge` team of `~/.config/pstack/model-teams.yaml`.

- Stage the rounds: ask only Sol until it reaches the target score, then add Opus, then GLM. A slow or unavailable member never blocks the loop; report it instead.
- Never tell delegates the target score.
- For UI or visual judgments, give every delegate before and after screenshots plus a reference product to score against.

## Skill overrides

Vendored skills stay unedited; these rules adjust them.

- Where a skill says to use `file-pr`, file the PR yourself and write its body with the `pr` skill: check that no PR exists for the branch, review the diff against the base branch, open a real PR (not a draft) with `gh pr create`, and check the title and body for secrets first.
