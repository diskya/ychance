# STATUS — build progress

Cross-thread memory for the manager role. `plan/` is the authoritative task list;
this file tracks what is merged, decisions not visible in `git log`, and items
carried forward.

## Phases

- [x] **Phase 0** — operator decisions. `config/envelope.yaml` committed (HK NRA via IBKR; Polygon / EDGAR / FRED shortlisted; no US-HK tax treaty noted).
- [x] **Phase 1.1–1.3** — `rawstore/`, `audit/`, `access/`.
- [x] **Phase 1.4** — `pipeline/` Stage + DAG shell, invariants, cost ceilings, cache-hit-no-audit exit criterion.
- [x] **Phase 2.1** — Ingest adapter. Operator restricted scope to one keyless vendor (SEC EDGAR submissions) instead of the plan's 2–4 suggestion.
- [ ] **Phase 2.2** — feature-family spec runner (`represent/`).
- [ ] **Phase 2.3** — LLM-as-feature harness.
- [ ] **Phase 3+** — see `plan/02-discovery-loop.md` onward.

## Decisions not obvious from `git log`

- **2.1 single-vendor scope**: operator chose one adapter, keyless only. Retail price data (Polygon / Alpaca / IBKR) all require at least a free key and were deferred. This must be revisited before Phase 10 — the forward sim clock needs real price data.
- **`Stage.audit_extra_payload()` hook** (added in Phase 2.1): lets stage subclasses inject category-specific fields into the Stage audit record per methodology §9. Required by Ingest's field list; will also be needed by Represent, Propose, Council, Validate, etc. Backwards-compatible (default returns `{}`). Not a one-off.

## Carried-forward flags

- Ingest adapter's `invariant()` reaches for `rawstore._issue_reader()` + `has()` to verify a just-written entry. Redundant with the `stored_hash != bytes_hash` check in `compute()`, and arguably bypasses the access-layer discipline from plan 1.3. Tighten next time `ingest/edgar/adapter.py` is opened. Add to future delegation prompts: "verify rawstore writes via `put()`'s return value, not the read API."
- Codex-worker contributions are not yet recorded in `audit/`. Per `CLAUDE.md`, build-tool provenance is out of scope until a later phase wires it; for now the audit trail is `git log` + conversation.
- `config/envelope.yaml` → `operator.jurisdiction` has `home_country: HK` with a note that physical presence is SG. Resolve with a local tax advisor before cutover (Phase 11).

## Resuming in a new thread

1. Read `Objective.md` §0 + §7.
2. Read this file.
3. Read the relevant `plan/*.md` section for the target phase.
4. Confirm scope with operator **before** delegating anything token-heavy to `codex-coder`.
5. After the worker returns: `git diff`, grep for §0 leakage in new names/comments, run `uv run pytest -q`, update this file.
