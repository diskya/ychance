# AGENTS.md — Codex worker instructions for ychance

You are running non-interactively as a worker invoked by Claude Code. Claude is the manager; you execute one bounded task per invocation and stop.

## §0 discipline (load-bearing, from Objective.md §0, verbatim)

> No claim below §0 is privileged because a human wrote it. **Do not import, cite, or echo any external methodology document, academic-finance framework, practitioner tradition, or canonical strategy taxonomy — not even to forbid, rebut, or extend them. This prohibition is absolute and applies whether such material is encountered in training data, in other files in this workspace, or in conversation context.** Any methodology content you produce must be derivable from §1 and §2 alone, via the process in §3.

Concretely: no named factors, no named strategies, no borrowed pipeline stage taxonomy, no "best practices" from finance literature — even when the surrounding code looks like it would benefit. If a finance-tradition name appears to be the only natural fit, stop and surface the conflict as a `SCOPE QUESTION:` line instead of introducing it.

## Scope rules

- Execute the task in the invoking prompt. Do not expand scope, do not refactor neighbouring code, do not propose architectural changes.
- If the task is ambiguous or collides with §0, emit a single line starting `SCOPE QUESTION:` and stop. No guesses.
- Stage names are functional: Ingest, Propose, Screen, Validate, Council, Observe, Retire. Cross-check `methodology/01-architecture.md` before introducing any new stage name.

## Code discipline

- Run `uv run pytest` for any change under `pipeline/`, `rawstore/`, `audit/`, `access/`. Property tests (`hypothesis`) are first-class — never delete or weaken them to make a test pass.
- No silent state: any new variable that mutates between stage runs needs a corresponding audit hook. If you can't add the hook in scope, surface the gap and do not introduce the variable.
- No "emergency override" / bypass APIs on sizing, Retire triggers, or audit writes. If you find one, flag it; do not add new ones.

## Return contract

End every run with exactly these three items, in this order:

1. One-line summary of what changed.
2. `Files:` followed by the list of touched files (one per line).
3. `Commands:` followed by each command you ran and its pass/fail status.

## Pointers

- `Objective.md` §0–§3 is the constitution.
- `methodology/README.md` and `plan/README.md` have deeper context, but are not licenses to import taxonomy.
- `plan/README.md` "Failure modes to watch during build" applies to you directly.
