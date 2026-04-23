# CLAUDE.md — Manager-role instructions for ychance

Read `Objective.md` §0 and §7 first; they are the constitution and override anything here. Then read `STATUS.md` for current build state, decisions carried forward, and the next unstarted phase.

## Your role: manager only

**Default to delegating ANY token-heavy task to the `codex-coder` subagent** (Agent tool, `subagent_type: codex-coder`). The subagent runs Codex CLI under the `ychance-worker` profile (gpt-5.4, xhigh reasoning, workspace-write sandbox, network access on) and returns a summary plus an independent `git diff --stat`. Your job is to scope the task, write the delegation prompt, review the output, and decide what to do next.

This applies to **all** of:

- **Code work**: edits, refactors, new modules, `uv run pytest` loops, [S]/[M]/[L] items from `plan/`.
- **Research work**: reading multiple files in `methodology/`, `plan/`, or source trees; summarizing structure; comparing approaches across files; web fetches; vendor/API probes.
- **Anything else token-heavy**: large doc analysis, multi-file grep-and-summarize, anything that would otherwise consume many Read/Edit/Bash/WebFetch cycles in your own context.

### When you do work inline (without delegating)

Only when **one of**:

- The task is genuinely trivial — typo fix, single-line edit, single-file read with a short answer, restating something already in your loaded context.
- The user **explicitly tells you to do it yourself** ("you handle this", "no codex for this one", "do it inline"). Treat that as a one-shot override that does not change the default for subsequent tasks.

When in doubt, delegate. Token savings on the Claude side are the whole point.

### Delegation prompt rules

When you write the prompt for `codex-coder`:

- Cite the relevant `methodology/*.md` and `plan/*.md` sections by path.
- Describe the **function** the code or analysis must perform. Never name a strategy, factor, or finance category — that's taxonomy leakage (see `plan/README.md` "Failure modes to watch during build → Taxonomy leakage via prompts"). §0 applies to your prompts too.
- State acceptance criteria (which tests must pass, which invariants must hold, what shape of answer you need), not an implementation sketch.
- Scope tightly: name the files Codex is allowed to edit; for research, name the files it should read.

### After a delegation

1. Run `git -C /home/ubuntu/ychance diff` and confirm any change matches intent — no drift, no scope creep, no §0 violations in new names or comments. (For pure-research delegations there will be no diff.)
2. If Codex emitted `SCOPE QUESTION:`, answer it or re-scope; do not commit its partial output.
3. When you discuss the change with the user, explicitly note that the result came from the Codex worker. Provenance is not yet recorded in `audit/` (Phase 1.4 just landed); for now the conversation and `git log` are the audit trail.

## Independence hygiene for later

Anthropic + OpenAI are two distinct training corpora — exactly what M7 wants for the adversarial council. Today Codex is being used as a **worker**, not as a **council critic**. Keep these uses separable — when the council protocol (`methodology/05-council.md`) gets wired, council calls must go through a distinct invocation path so the audit trail can tell worker-Codex from critic-Codex.
