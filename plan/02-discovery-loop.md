# Phase 3 — Discovery Loop

**Goal**: Pattern object, Discover (tool-using agent loop), EmpiricalTest, Originality. Council is in [03-council.md](03-council.md).

Foundation exists: `rawstore`, `audit`, `access`, `pipeline`, `ingest`, `represent`, `partitions`. Legacy `propose/`, `rule/`, `validate/`, and `originality/` were deleted; rebuild clean.

## Sequencing

3a (Pattern) is the prerequisite. 3b (Discover) and 3c (EmpiricalTest) can run in parallel after 3a. 3d (Originality) is small; slot it anywhere.

---

## 3a. Pattern object — **[M]**

> Define `Pattern` as `(spec_ref, assertion, scope, observation_window, replication_protocol)`, each component serializable and content-addressed. Reuse `represent/`'s registered-op DAG infrastructure for `assertion` and `scope`.
>
> Acceptance:
> - `pattern_id = sha256(canonical_body_with_op_versions_folded_in)`.
> - `Pattern.evaluate(t, access, registry) -> bool` evaluates the assertion at `t`.
> - Round-trip serialization is byte-identical.
> - Static-analysis test: `pattern/` does not import or define any trading-shaped vocabulary (no `position`, `trade`, `pnl`, `entry`, `exit`, `horizon`, etc.).

---

## 3b. Discover stage — tool-using agent loop — **[L]**

### Research thread prompt

> Design `discover/` per [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md): a tool-using agent loop that receives the anti-pattern list + archive and emits candidate Patterns.
>
> Fixed tools: `inspect_spec`, `compute`, `propose_spec`, `test_assertion`, `submit_pattern`; all route through `access`. Decide: loop control, prompt scaffold, operator-input denylist, cost enforcement, no-Pattern handling.
>
> Constraints: hard per-cycle cap; rationale logged but withheld from Council; operator inputs only as tool/red-team requests with `shape_classification`; cheaper model for tool-call iteration, frontier model only at submission.
>
> Design artifact: [02-discovery-loop-3b-design.md](02-discovery-loop-3b-design.md).

### Coding prompt (after design)

> Implement `discover/` per the attached design as a `Stage` subclass. Every tool call audited; every operator input audited with `shape_classification`. Submitted Patterns flow downstream to Originality and EmpiricalTest.

---

## 3c. EmpiricalTest stage — **[M]**

> Implement `empirical_test/` per [../methodology/04-empirical-test.md](../methodology/04-empirical-test.md). For each candidate Pattern: deterministically select held-out windows from `pattern_id` + `replication_protocol`; assert disjointness via raw-store lineage; re-evaluate the assertion on each window and per partition tag (consume `partitions/`); run three perturbation controls (time-shuffled, scope-randomized, threshold-perturbed); emit an `EmpiricalTestReport` with verdict, partition results, control results, disjointness audit.
>
> Acceptance:
> - Disjointness provable from lineage.
> - Verdict deterministic given `pattern_id` and the same raw-store state.
> - All three perturbation controls have unit tests against synthetic Patterns designed to fail each one.
> - Audit emits a record per [../methodology/09-audit.md](../methodology/09-audit.md).

---

## 3d. Originality filter — **[S]**

> Rebuild `originality/` for Pattern fingerprints: bounded mutable computable matchers, reject on fingerprint reducibility, emit Originality records with `pattern_id`, `result`, `matched_anti_pattern` if any, and `anti_pattern_list_version`.

---

## Exit criteria

- A synthetic Pattern passes Discover → Originality → EmpiricalTest end-to-end on test data, producing an `EmpiricalTestReport`.
- LLM spend per Discover cycle is within the per-cycle cap (integration test mocks the LLM client).
- Discover's tool-call trace is fully reconstructable from audit (replay test).
- An operator input that violates §4's shape is mechanically rejected with a logged `shape_classification: flagged` record.
- `pattern/` static-analysis guard passes.
