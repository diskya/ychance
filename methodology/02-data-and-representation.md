# §6.2 Data Ingestion and Representation

## Status
Initial hypothesis under M3. **Specific feeds and feature families are AI proposals, not operator decisions.** This file fixes only the *contracts* that every feed and every feature must satisfy. The catalog of what is actually ingested and what features are actually computed lives in versioned artifacts produced by Propose, not in this document.

## Ingest contract

A data source is admissible iff:
1. It is retail-accessible per §2 (no prime-broker feeds, no exclusive alt-data, no data that requires an institutional entitlement).
2. Its terms of service permit retention of fetched data for methodology use.
3. Its total cost (subscription + request fees + storage) fits the envelope `E` alongside all other sources currently admitted.
4. Fetched bytes can be stored with a **provenance triple**: `(source_id, fetch_time, vendor_timestamp)` — where `vendor_timestamp` is what the vendor claims the observation refers to, never silently derived.

## Raw store

Append-only, content-addressed. Keyed by `sha256(bytes)`. Provenance triples are indexed separately — the raw bytes and the provenance are *physically* separate records, joined by hash, so that re-ingesting the same bytes from a second vendor increases provenance multiplicity without duplicating storage.

**No mutations.** Corrections issued by a vendor are ingested as new entries with new provenance referring to the original entry's hash. The raw store is therefore a DAG of observations and corrections, not a rolling "current truth" table.

## Feature contract

A **feature-family spec** is an AI-produced artifact containing:
- A pure-function definition `f(raw_entries) → tensor` (no hidden state, no clock-reads beyond those declared).
- A declared dependency set: which raw-store entry keys (or streaming subscriptions) the feature reads.
- A cost annotation: compute cost per unit output, LLM cost (if the feature involves a model call), and storage cost.
- A lineage commitment: given the spec version and the dependency set, recomputation is byte-identical.

A feature passes the contract iff recomputation at a later date from the original inputs reproduces the original output bit-for-bit. This rules out features that read "now" as a hidden input or that depend on stateful vendor APIs without freezing the response.

## What the methodology does not do

- **No canonical feature library.** There is no persisted table of "important features" carried across M2a cycles. A feature that proved useful in cycle `k` must be re-proposed in cycle `k+1` to survive. If it is durable, re-proposal is cheap; if it is not durable, it disappears. This is deliberate — a persistent feature library becomes a taxonomy (M1).
- **No asset-class partition.** Features do not know what instrument class their inputs came from. If a feature happens to work only on one subset, that subset is discovered by Screen/Validate, not declared by the feature.
- **No fixed embedding model.** Embeddings of text, filings, or event streams are features like any other, proposed and retired by the loop.

## LLM-as-feature

A feature-family spec may call an LLM. When it does:
- The spec freezes the exact model version, the exact prompt template, and the exact temperature/sampling parameters. Any change is a new spec version.
- The raw response is stored in the raw store (with provenance `(model_id, fetch_time, prompt_hash)`), not just the parsed feature value. This lets later inspection catch model-behavior drift.
- The cost annotation is tracked live; if realized cost per output drifts above the annotated value, Propose must re-cost.

## Representation for Propose

When Propose reads data, it reads through an **access layer** that:
- Serves only data whose `vendor_timestamp ≤ t` for some explicit query time `t` — preventing accidental peek.
- Rate-limits request volume so Propose cannot exhaust `$B` on a single cycle.
- Logs every read. Propose cannot circumvent the access layer.

## Cross-validation of the data itself

Data can lie — vendors make mistakes, feeds change silently. The methodology defends against this by:
- Accepting multi-vendor overlap where it exists; a large discrepancy between two vendors for the same `vendor_timestamp` triggers an Audit record and excludes the disagreeing window from downstream use until a rule-level decision is logged.
- Tracking vendor-side retraction events as first-class raw-store entries (see above). Rules that were trained through a retracted window are re-Validated.

## What the operator does here

Nothing, beyond:
1. Approve a new vendor subscription when its cost enters the envelope accounting (operator holds the budget, not a Propose autonomous agent).
2. Kill a vendor subscription if its ToS changes in a way that violates §2.

Operator does not choose features, does not rank them, does not tune them.

## Revision triggers

- Scheduled: every M2a, the ingest contract and feature contract are reviewed. Changes require Council sign-off.
- Unscheduled: a data-integrity incident (silent vendor change, retraction storm, discrepancy spike) forces an ingest-contract review regardless of schedule.
