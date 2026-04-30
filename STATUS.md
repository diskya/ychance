# STATUS — build progress

Cross-thread memory for the manager role. `plan/` is the authoritative task list;
this file tracks what is merged, decisions not visible in `git log`, and items
carried forward.

## Scope as of 2026-04-28

The project pivoted from "AI-native alpha-discovery-to-execution" (Objective.md v2.1) to "frontier-AI pattern-discovery system" (Objective.md v3.0). The corpus of council-approved, replication-tested Patterns is the artifact; trading is out of scope.

### Cleanup executed (2026-04-28)

Two-phase cleanup. The first phase removed v2.1's deployment-half modules; the second phase removed the trading-shaped discovery scaffolding so the rebuild starts from a clean foundation rather than refitting v2.1 vocabulary into v3.0 names.

**Phase-1 deletions (deployment half):**
- Modules: `screen/`, `validate/`.
- Configs: `config/screen.yaml`, `config/validate.yaml`.
- Methodology: `04-validation.md`, `06-sizing-risk-portfolio.md`.
- Plan: `04-lifecycle-and-sizing.md`, `05-execution.md`, `07-go-live.md`.

**Phase-2 deletions (trading-shaped discovery):**
- Modules: `rule/` (Rule = `(C, A, H, X)`, trading-encoded), `propose/` (single-shot prompt, wrong design — see prior conversation), `originality/` (consumed `Grounding` from `rule/`), `council_llm/` (typed on `Rule + ValidationReport`), `council_decide/` (built on `council_llm` types).
- Tests for each of the above.
- Config: `config/propose.yaml`.
- Caches: `.pytest_cache/`, `.hypothesis/`, all `__pycache__/`.

The phase-2 deletions cascade from `rule/`. Refitting them piecewise would have left v2.1 vocabulary (`Grounding`, `validate_report`, `rule_id`) in the new codebase. Rebuilding clean produces `Pattern`, `empirical_test_report`, `pattern_id`.

### Doc rewrites under v3.0

- `Objective.md` — terminal goal is now archive-rate, not P&L. §0 was relaxed from "no imports at all" to §0a "operator does not target."
- `methodology/README.md`, `01-architecture.md`, `02-data-and-representation.md`, `03-discovery-loop.md`, `05-council.md`, `07-operator-workflow.md`, `08-falsification-clock.md`, `09-audit.md` — rewritten or trimmed.
- `methodology/04-empirical-test.md` — new file; replaces v2.1 Validation with assertion-replication on held-out windows.
- `plan/README.md`, `00-operator-decisions.md`, `01-foundation.md`, `02-discovery-loop.md`, `03-council.md`, `06-operator-ux.md` — rewritten.

### Foundation vocabulary scrub (2026-04-28)

After the deletion pass, the surviving foundation was scrubbed for stale
v2.1 names:
- `tests/partitions/test_partitions.py` no longer imports deleted `tests.rule`
  fixtures.
- `access/` window reservations now use `pattern_id` and
  `Discover`/`EmpiricalTest` stages, not `rule_id` and `Screen`/`Validate`.
- `audit/` envelopes now admit `pattern_id`, `cycle_id`, and `m2a_id`.
- `pipeline/` stage allowlist now reflects v3.0 stages.
- `config/envelope.yaml` is trimmed to research-budget scope only.

## Current code state

### Surviving modules (foundation, no trading-shaped vocabulary)

- `rawstore/` — content-addressed, append-only, hash-keyed bytes + provenance index.
- `audit/` — append-only hash-chained JSONL, daily rotation, cross-day continuity.
- `access/` — capability-narrowed read layer; only path Discover/EmpiricalTest/Council may use to read raw bytes.
- `pipeline/` — `Stage` base class with cost ceilings and invariant assertions; `PipelineDAG` orchestrator.
- `ingest/` — SEC EDGAR submissions adapter (one keyless source).
- `represent/` — feature-family spec runner with content-addressed `spec_id` and LLM-as-feature `llm_call` op.
- `partitions/` — partition-tag derivation from raw-store state summaries.

### Surviving tests

- `tests/test_rawstore.py`, `test_audit.py`, `test_access.py`, `test_pipeline.py`, `test_ingest_edgar.py`.
- `tests/represent/` — spec, runner, guardrails.
- `tests/partitions/` — partition derivation, no-rawstore-import guardrail.

### To-rebuild modules (planned, not yet built)

- `pattern/` — replaces `rule/`. `Pattern = (spec_ref, assertion, scope, observation_window, replication_protocol)`. No trading vocabulary. (Phase 3a.)
- `discover/` — replaces `propose/`. Tool-using agent loop with a fixed tool surface (`inspect_spec`, `compute`, `propose_spec`, `test_assertion`, `submit_pattern`). (Phase 3b.)
- `empirical_test/` — replaces `validate/`. Assertion replication on held-out windows + perturbation controls. (Phase 3c.)
- `originality/` — rebuilt against Pattern fingerprints (matcher API survives in spirit). (Phase 3d.)
- `council_llm/` — rebuilt with `(pattern, empirical_test_report, raw_slice)` input contract. (Phase 4.1.)
- `council_decide/` — rebuilt routing to Archive instead of Paper-deploy. (Phase 4.2.)
- `independence/` — new module, Phase 4.3.
- `council_calibration/` — new module, Phase 4.4.
- `archive/` — new module for Pattern corpus persistence + browser. (Phase 5.)

## Phases under v3.0 plan

- [x] **Phase 0** — operator decisions. `config/envelope.yaml` is trimmed to the v3.0 research-budget schema; no deployment fields remain.
- [x] **Phase 1.1–1.4** — `rawstore/`, `audit/`, `access/`, `pipeline/` (Stage + DAG). All survive.
- [x] **Phase 2.1–2.3** — Ingest (EDGAR), `represent/`, LLM-as-feature. All survive. Phase 2.3 §0a clarification: prompts in LLM-as-feature specs must be *extraction* prompts, not *suggestion* prompts.
- [x] **Phase 4.2 (partitions module)** — `partitions/` survives.
- [ ] **Phase 3a** — Pattern object (rebuild from clean).
- [ ] **Phase 3b** — Discover stage as tool-using agent loop. Largest single piece of remaining work; needs research thread before coding.
- [ ] **Phase 3c** — EmpiricalTest stage.
- [ ] **Phase 3d** — Originality filter rebuilt against Pattern fingerprints.
- [ ] **Phase 4.1** — Council voter wrapper rebuild.
- [ ] **Phase 4.2** — Council decision rule rebuild.
- [ ] **Phase 4.3** — Independence audit (research-heavy).
- [ ] **Phase 4.4** — Calibration test.
- [ ] **Phase 5** — Operator UX.

## Decisions not obvious from `git log`

- **2026-04-28 scope pivot**: trading is out of scope (Objective.md v3.0). The discovery half of the system survives; the deployment half was deleted. §0 simultaneously relaxed from "absolute import prohibition" to §0a "operator does not target" because the strict reading was self-undermining and unenforceable.
- **2026-04-28 nuclear cleanup**: rather than refit `rule/` + `propose/` + `originality/` + `council_*/` to Pattern shape, all five modules were deleted to start clean. Justification: the v2.1 trading vocabulary (`Grounding`, `Rule`, `validate_report`) would have leaked into the rebuilt codebase under refit, and the refit work would have approached the rebuild work in size.
- **C-first scope ladder**: the v3.0 system is the **Pattern Catalog** (option C in the prior conversation): output is a corpus of empirical anomalies/structural claims, each with a frozen fingerprint and a re-replication test. Hypothesis-with-mechanism (option A) and tool-using research-agent surfacing (option B) are *not* implemented; they are downstream extensions on top of a working C. The Discover stage is *B-shaped infrastructure (tool-using agent loop) producing C-shaped output (Patterns)* — the simplest composition that gives meaningful operator co-research without exploding the output evaluation problem.

## Decisions carried forward from v2.1 (still valid for the surviving modules)

- **`Stage.audit_extra_payload()` hook** — used by every surviving stage.
- **Spec format**: registered-op DAG, canonical-JSON body, `spec_id = sha256(canonical_body_with_op_versions_folded_in)`.
- **2.3 deps envelope**: `_validate_declared_deps` relaxed for `llm_call`.
- **2.3 cost-drift**: `CostDrift` audit category in `represent/`.
- **Raw store + access discipline**: `represent/` is forbidden by static analysis from importing `rawstore`. The `access` layer is the only read path. `partitions/` follows the same rule.
- **§0 guardrail tests**: token-blocklist greps in surviving modules. Will need re-application in rebuilt modules; the v2.1 blocklist will need a small expansion as `pattern/` lands (no `rule`, `trade`, `position`, `entry`, `exit`, `pnl`, etc.).

## Known issues / flags

- **Qwen pricing placeholders in `represent/pricing.py`**: still need operator confirmation against current Alibaba Cloud pricing.
- **`SpecRegistry.register()` looseness** (accepts both finalized spec and raw body): still valid; revisit when Phase 3b Discover starts emitting specs.
- **Codex-worker contributions are not yet recorded in `audit/`**: deferred to a later audit-extension phase.

## Resuming in a new thread

1. Read `Objective.md` v3.0 (especially §0 and §7).
2. Read this file.
3. Read the relevant `plan/*.md` section for the target phase.
4. Confirm scope with operator **before** delegating anything token-heavy to `codex-coder`.
5. After the worker returns: `git diff`, grep for §0a leakage in new names/comments, run `uv run pytest -q`, update this file.

The next planned work is Phase 3a (Pattern object, clean build) and Phase 3b (Discover stage as tool-using agent). Phase 3a is the prerequisite; Phase 3b is the single largest piece of remaining work and needs a research thread before coding begins.

`uv run pytest -q` should pass cleanly on the surviving foundation before Phase 3a begins.
