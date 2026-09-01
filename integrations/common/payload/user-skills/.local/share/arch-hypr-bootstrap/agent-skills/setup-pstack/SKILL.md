---
name: setup-pstack
description: Configure provider-aware model teams used by pstack skills across Codex, Claude Code, Cursor, and other agent hosts.
---

# Setup pstack

Manage `~/.config/pstack/model-teams.yaml`, the shared source of truth for pstack model selection.

## Model teams

Every team contains one OpenAI, Anthropic, and xAI member. A member has separate `model` and `effort` fields. Provider-specific settings such as Anthropic's adaptive thinking use their own field. Never encode effort in the model slug.

- `explore`: codebase search, history, logs, and evidence gathering.
- `build`: scoped implementation, refactoring, tests, and mechanical migrations.
- `deep`: difficult bugs, performance work, architecture, and synthesis.
- `judge`: independent review, adversarial critique, and candidate selection.

## Dispatch modes

- `native`: detect the current host's model provider and select that provider's member from the requested team. Codex maps to OpenAI, Claude Code maps to Anthropic, and Grok Build maps to xAI. In Cursor, use the provider of the selected parent model.
- `panel`: launch one member per provider that the current host can invoke. Report unavailable providers before continuing. Never substitute another provider or duplicate the native provider to make the panel appear complete.

Treat `model-teams.yaml` as configuration, not proof of availability. Before writing a real model ID, confirm that the target host exposes it. Preserve the current value when availability cannot be checked.

## Update workflow

1. Read the current file. If it is missing, recreate the four-team schema described above.
2. Detect models and effort levels available in each target host the user placed in scope.
3. Show the current matrix and mark entries that the target host rejects or cannot verify.
4. Apply only the requested changes. Keep all three providers in every team.
5. Parse the YAML and verify that every team has exactly `openai`, `anthropic`, and `xai`, each with `model` and `effort`. Allow provider-specific fields such as `thinking` only when the provider supports them.
6. Report the changed entries and which hosts were verified.

New delegations read the updated file immediately. Existing subagents keep the model selected when they were spawned.
