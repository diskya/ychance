# §6.1 Architecture

Initial hypothesis under M2. Names refer to functions, not inherited categories.

## Shape

A directed acyclic graph of **stages**. Each stage is a typed, versioned node with: input artifacts (content-addressed), output artifacts (content-addressed), an invariant, and a cost ceiling. A stage must not read any un-logged input.

## Stages

### Ingest
- **In**: §2-admissible raw data.
- **Out**: provenance-tagged raw store entries.
- **Invariant**: entry hash equals bytes hash; provenance triple present; no overwrite.

### Represent
- **In**: raw store entries; a feature-family spec emitted by Discover.
- **Out**: feature tensors keyed by entity and time, lineage-tracked back to raw entries and spec version.
- **Invariant**: recomputing from lineage reproduces byte-identical outputs.

### Discover
- **In**: data slices; current anti-pattern list; current archive (for novelty); operator co-research inputs (tool requests / red-team requests only — see [../Objective.md](../Objective.md) §4).
- **Out**: candidate Patterns `(spec_ref, assertion, scope, observation_window, replication_protocol)` with executable assertions.
- **Invariant**: every emitted Pattern's assertion is computable from raw-store inputs and reproducible byte-identically; observation window is frozen and folded into `pattern_id`.
- **Implementation**: tool-using agent loop. Single-shot prompting is insufficient. See [03-discovery-loop.md](03-discovery-loop.md).

### EmpiricalTest
- **In**: candidate Patterns from Discover.
- **Out**: replication report (verdict + robustness profile across pre-committed held-out windows). See [04-empirical-test.md](04-empirical-test.md).
- **Invariant**: no data point used in observation window appears in any replication window for the same Pattern.

### Council
- **In**: EmpiricalTest reports + Pattern objects + sampled raw-data slices.
- **Out**: votes and rationales from ≥ 2 measurably-independent vendor families per [05-council.md](05-council.md); archive decision iff ≥ 2 independent approvals.
- **Invariant**: decision reproducible from logged inputs and the decision rule; rationales stored verbatim.

### Archive
- **In**: Council-approved Patterns.
- **Out**: append-only corpus entry — Pattern body, observation window, replication report, council votes, all upstream artifact hashes.
- **Invariant**: archive is append-only. A Pattern that fails future re-replication is *annotated*, not removed.

### Audit
- Spans every other stage. Append-only JSON Lines. Per [09-audit.md](09-audit.md).
- **Invariant**: for every state transition in every stage, exactly one Audit record exists.

### Review (M2a)
- **In**: Audit records since last Review; archive growth and replication statistics; current architecture.
- **Out**: architecture diff red-teamed by a disjoint Council instance; executed or rejected with rationale.
- **Invariant**: architecture frozen between Reviews.

## Hard cross-stage invariants

1. **Cost gating.** Frontier-model calls gated behind cheaper filters whenever such a filter exists. Enforced by per-stage cost ceilings.
2. **No retroactive reads.** A stage's output at time `t` must be reproducible from inputs available at `t`.
3. **Operator-input audit.** Every co-research input is logged at the same fidelity as an LLM prompt; inputs that violate §4's shape are flagged at M2a.
4. **Degraded mode.** Heartbeat absent for `N` days → Discover halts; Ingest/Represent/Audit continue; no data lost.
