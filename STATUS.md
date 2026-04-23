# STATUS — build progress

Cross-thread memory for the manager role. `plan/` is the authoritative task list;
this file tracks what is merged, decisions not visible in `git log`, and items
carried forward.

## Phases

- [x] **Phase 0** — operator decisions. `config/envelope.yaml` committed (HK NRA via IBKR; Polygon / EDGAR / FRED shortlisted; no US-HK tax treaty noted).
- [x] **Phase 1.1–1.3** — `rawstore/`, `audit/`, `access/`.
- [x] **Phase 1.4** — `pipeline/` Stage + DAG shell, invariants, cost ceilings, cache-hit-no-audit exit criterion.
- [x] **Phase 2.1** — Ingest adapter. Operator restricted scope to one keyless vendor (SEC EDGAR submissions) instead of the plan's 2–4 suggestion.
- [x] **Phase 2.2** — feature-family spec runner (`represent/`). Canonical-JSON spec with registered-op DAG; 12 primitive ops; `op_version` folded into `spec_id`; in-memory `SpecRegistry`; `RepresentStage` reads only through `access` layer; byte-identical repro + no-wall-clock + no-direct-rawstore-import tests.
- [ ] **Phase 2.3** — LLM-as-feature harness. Extends 2.2 with one more primitive op (`llm_call`) + raw-response write-back into `rawstore` + cost-drift tracking. Seam already in place: op registry is open, `op_version` is part of the spec hash.
- [ ] **Phase 3+** — see `plan/02-discovery-loop.md` onward.

## Decisions not obvious from `git log`

- **2.1 single-vendor scope**: operator chose one adapter, keyless only. Retail price data (Polygon / Alpaca / IBKR) all require at least a free key and were deferred. This must be revisited before Phase 10 — the forward sim clock needs real price data.
- **`Stage.audit_extra_payload()` hook** (added in Phase 2.1): lets stage subclasses inject category-specific fields into the Stage audit record per methodology §9. Required by Ingest's field list; will also be needed by Represent, Propose, Council, Validate, etc. Backwards-compatible (default returns `{}`). Not a one-off. Represent (2.2) uses it to emit `spec_version`, `declared_cost`, `cost_used`, `hashes_read`, and output dtype/shape.
- **Spec format chosen in 2.2**: registered-op DAG, canonical-JSON body, `spec_id = sha256(canonical_json(body))` with per-node `op_version` folded into the hash input. Specs are data, not code — Phase 3 Propose emits them programmatically with no feature files on disk. Read path: `raw_get` is the only op that talks to `ctx.access`; all other ops are pure. `represent/` imports nothing from `rawstore` (AST-enforced in tests). Added `numpy` as a runtime dep (first one).
- **2.3 deferred deliberately**: bundling would have doubled 2.2 scope (response write-back into rawstore, prompt-hash provenance, cost-drift monitor). The primitive-op registry was designed so adding `llm_call` is drop-in.

## Carried-forward flags

- Ingest adapter's `invariant()` reaches for `rawstore._issue_reader()` + `has()` to verify a just-written entry. Redundant with the `stored_hash != bytes_hash` check in `compute()`, and arguably bypasses the access-layer discipline from plan 1.3. Tighten next time `ingest/edgar/adapter.py` is opened. Add to future delegation prompts: "verify rawstore writes via `put()`'s return value, not the read API." (Reminder was included in the 2.2 delegation prompt; `represent/` does no writes, so nothing to regress.)
- `SpecRegistry.register()` in 2.2 accepts both a finalized spec (with `spec_id`) and a raw body (auto-calls `finalize_spec`). The manager's delegation prompt said reject-if-missing, but the looser path still validates via `load_spec` and is strictly more caller-friendly. Not a correctness drift, but worth revisiting if Phase 3 Propose wants stricter provenance on what it registers.
- Codex-worker contributions are not yet recorded in `audit/`. Per `CLAUDE.md`, build-tool provenance is out of scope until a later phase wires it; for now the audit trail is `git log` + conversation.
- `config/envelope.yaml` → `operator.jurisdiction` has `home_country: HK` with a note that physical presence is SG. Resolve with a local tax advisor before cutover (Phase 11).

## Resuming in a new thread

1. Read `Objective.md` §0 + §7.
2. Read this file.
3. Read the relevant `plan/*.md` section for the target phase.
4. Confirm scope with operator **before** delegating anything token-heavy to `codex-coder`.
5. After the worker returns: `git diff`, grep for §0 leakage in new names/comments, run `uv run pytest -q`, update this file.
