# §6.4 Empirical-Test Protocol

Initial hypothesis under M6. The protocol is itself subject to meta-validation; a protocol stays in force only as long as it out-predicts challengers.

## What EmpiricalTest produces

For each candidate Pattern `P`:

1. **Replication verdict.** Boolean: did `P`'s assertion hold, at the pre-committed pass level, on the pre-committed set of held-out windows?
2. **Robustness profile.** Realized statistics across (a) multiple held-out windows of the same scope, (b) per-partition splits, (c) perturbation controls.
3. **Disjointness audit.** Proof from raw-store lineage that no observation-window data point appears in any held-out window for `P`.

No EmpiricalTest output is a single scalar. Council reads the verdict and the distribution.

## Held-out window selection

Time-respecting only. A window touched while shaping `P` (observation window + windows the Discover agent's tool calls hit) may not appear in any replication window. **Gap** between observation and held-out windows is sized to the longest dependency in `spec_ref` — otherwise a held-out feature value can leak observation information.

Held-out windows are deterministic given `pattern_id` and `replication_protocol`. This determinism is what makes EmpiricalTest reproducible across reruns.

## Partitioning

Held-out windows are split by partition tags derived from observable raw-store state (see [`partitions/`](../partitions/)). Tags are `partition_0`, `partition_1`, … with statistical fingerprints; they carry no inherited names. Re-derived every M2a. A Pattern must replicate in a pre-committed majority of active partitions, not just in aggregate — guarding against patterns that hold on average but only on one partition.

## Perturbation controls

- **Time-shuffled.** Re-evaluate on `spec_ref` outputs whose time index has been shuffled within the held-out window. If the assertion still holds, it's detecting marginal distribution structure, not temporal structure.
- **Scope-randomized.** Re-evaluate on a randomly sampled scope of the same size. If still holds, the scope is not load-bearing.
- **Threshold perturbation.** Move the assertion's thresholds within a small band. Verdict should not flip; if it does, the Pattern is overfit to the observation window.

A Pattern that fails any control is rejected before reaching Council, regardless of the replication verdict. Controls are gates, not advisories.

## Pass criterion

A Pattern passes iff *all* of:
1. Replication verdict positive on pre-committed majority of held-out windows.
2. Replication verdict positive on pre-committed majority of active partitions.
3. All three perturbation controls reject the assertion on shuffled / randomized / perturbed inputs.
4. Disjointness audit clean.

No partial credit.

## Meta-validation (M6)

Every M2a: score the current protocol `P_0` and ≥ 1 AI-produced challenger `P_1` by how well their verdict *predicted* re-replication on a fresh window. Calibration (do verdicts match realized rates?) and discrimination (do `pass`-verdict Patterns re-replicate at higher rates than `fail`-verdict ones?) are both measured. If `P_1` strictly dominates on both, swap. Partial dominance triggers a Council tie-break. Until enough Patterns have been archived to populate the meta-validation set, this is a null-op.
