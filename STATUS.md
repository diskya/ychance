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
- [x] **Phase 2.3** — LLM-as-feature harness. Adds `llm_call` primitive op; cached write-through into `rawstore` keyed by `(model_id, prompt_hash, params_hash)`; `CostDrift` audit category for realized-vs-declared drift. Qwen-plus via OpenAI-compatible API as the single provider (temp=0, no streaming, no tool-use); `openai` added as a dep. Tests are fixture-only — no live network.
- [ ] **Phase 3+** — see `plan/02-discovery-loop.md` onward.

## Decisions not obvious from `git log`

- **2.1 single-vendor scope**: operator chose one adapter, keyless only. Retail price data (Polygon / Alpaca / IBKR) all require at least a free key and were deferred. This must be revisited before Phase 10 — the forward sim clock needs real price data.
- **`Stage.audit_extra_payload()` hook** (added in Phase 2.1): lets stage subclasses inject category-specific fields into the Stage audit record per methodology §9. Required by Ingest's field list; will also be needed by Represent, Propose, Council, Validate, etc. Backwards-compatible (default returns `{}`). Not a one-off. Represent (2.2) uses it to emit `spec_version`, `declared_cost`, `cost_used`, `hashes_read`, and output dtype/shape.
- **Spec format chosen in 2.2**: registered-op DAG, canonical-JSON body, `spec_id = sha256(canonical_json(body))` with per-node `op_version` folded into the hash input. Specs are data, not code — Phase 3 Propose emits them programmatically with no feature files on disk. Read path: `raw_get` is the only op that talks to `ctx.access`; all other ops are pure. `represent/` imports nothing from `rawstore` (AST-enforced in tests). Added `numpy` as a runtime dep (first one).
- **2.3 deferred deliberately**: bundling would have doubled 2.2 scope (response write-back into rawstore, prompt-hash provenance, cost-drift monitor). The primitive-op registry was designed so adding `llm_call` is drop-in.
- **2.3 provider choice**: operator picked Qwen via OpenAI-compatible API (`qwen-plus`), reading `OPENAI_API_KEY` + `OPENAI_API_BASE` from env. This sidesteps the Anthropic/OpenAI corpus-independence question for the later council protocol — Qwen is a third training corpus, so neither lane is pre-committed. Real client: `represent.llm_client.QwenOpenAICompatibleClient`. Tests use `StubLLMClient` exclusively.
- **2.3 write-path shape**: new `access.RawStoreWriter` sibling to `AccessLayer`, same closure pattern for capability hiding, single narrow method `put_llm_response(...)`. Threaded into `StageContext.writer` symmetric with `.access`. `represent/` still imports nothing from `rawstore` — guardrail test extended and green.
- **2.3 cache index**: new `llm_cache` sqlite table inside `RawStore` keyed by `(model_id, prompt_hash, params_hash) → bytes_hash`. `AccessLayer.lookup_llm()` returns the bytes-hash or `None`; the subsequent `access.get(bytes_hash, query_time)` still enforces temporal admissibility, so a future-dated cached response is denied on read even though the cache hit resolves. Cache lookups count toward the per-cycle read budget.
- **2.3 mode split**: `llm_call.run()` is one function with an internal branch. Miss → call `LLMClient`, canonicalize full response into JSON envelope, write via `writer.put_llm_response()` (verified by `put()`'s return value, not by a subsequent read). Hit → read cached envelope via `access.get()`, extract text + token counts. Only the miss branch does network; every re-run under pytest is the hit branch.
- **2.3 deps envelope**: `_validate_declared_deps` relaxed to skip `llm_call` nodes (cache bytes-hash is unknown at spec-authoring time). `raw_get` envelope enforcement unchanged. `outputs.input_hashes` union includes both `raw_get` hashes and `llm_call` cache bytes-hashes for full lineage capture. Test asserts an `llm_call` cache hash not in `spec.deps` validates while a `raw_get` hash not in `spec.deps` still fails.
- **2.3 cost-drift**: new audit category `CostDrift` (sibling of `Represent` record, not a payload flag). Emitted per drifted llm_call node per run when `realized_usd / declared_cost_usd > 1 + cost_tolerance` (default tolerance 0.20). Fires on both miss and hit runs (hit-mode realized cost comes from the cached envelope's token counts). Price table lives in `represent/pricing.py` with qwen-plus placeholders; numbers need operator confirmation before Phase 3.

## Carried-forward flags

- Ingest adapter's `invariant()` reaches for `rawstore._issue_reader()` + `has()` to verify a just-written entry. Redundant with the `stored_hash != bytes_hash` check in `compute()`, and arguably bypasses the access-layer discipline from plan 1.3. Tighten next time `ingest/edgar/adapter.py` is opened. Add to future delegation prompts: "verify rawstore writes via `put()`'s return value, not the read API." (Reminder was included in the 2.2 delegation prompt; `represent/` does no writes, so nothing to regress.)
- `SpecRegistry.register()` in 2.2 accepts both a finalized spec (with `spec_id`) and a raw body (auto-calls `finalize_spec`). The manager's delegation prompt said reject-if-missing, but the looser path still validates via `load_spec` and is strictly more caller-friendly. Not a correctness drift, but worth revisiting if Phase 3 Propose wants stricter provenance on what it registers.
- Codex-worker contributions are not yet recorded in `audit/`. Per `CLAUDE.md`, build-tool provenance is out of scope until a later phase wires it; for now the audit trail is `git log` + conversation.
- `config/envelope.yaml` → `operator.jurisdiction` has `home_country: HK` with a note that physical presence is SG. Resolve with a local tax advisor before cutover (Phase 11).
- **Qwen pricing placeholders** in `represent/pricing.py` (`input: $0.8/M`, `output: $2.0/M`) — set to reasonable defaults but need operator confirmation against current Alibaba Cloud Qwen-plus pricing before Phase 3 runs the loop for real. Drift detection still works either way; only the dollar amounts shift.
- **2.3 `RawStoreWriter` is not the only write path** — `RawStore.put()` remains callable directly by trusted callers (Ingest adapter). Writer is a narrow sibling for the llm_call case. If Phase 3+ wants all writes through capabilities, that's a larger refactor and should be a separate decision.
- **Cache lookups cost one read-budget slot per llm_call node**; in hit mode the subsequent `access.get()` costs a second slot. In miss mode the writer's `charge_data_read(1)` also charges one slot (for accounting symmetry). So a single llm_call node consumes 2 slots on miss or 2 slots on hit — revisit if Phase 3 Propose hits the read budget ceiling with multi-llm_call specs.

## Resuming in a new thread

1. Read `Objective.md` §0 + §7.
2. Read this file.
3. Read the relevant `plan/*.md` section for the target phase.
4. Confirm scope with operator **before** delegating anything token-heavy to `codex-coder`.
5. After the worker returns: `git diff`, grep for §0 leakage in new names/comments, run `uv run pytest -q`, update this file.
