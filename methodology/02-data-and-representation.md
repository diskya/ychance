# §6.2 Data Ingestion and Representation

Initial hypothesis under M3. Specific feeds and feature families are AI proposals, not operator decisions. This file fixes the *contracts* every feed and every feature must satisfy. The catalog of what is actually ingested, and what features are actually computed, lives in versioned artifacts produced by Discover.

## Ingest contract

A data source is admissible iff:
1. It is retail-accessible per §2.
2. Its terms of service permit retention.
3. Its total cost fits the envelope `E` alongside other sources currently admitted.
4. Fetched bytes can be stored with a **provenance triple** `(source_id, fetch_time, vendor_timestamp)` — `vendor_timestamp` is what the vendor claims, never silently derived.

## Raw store

Append-only, content-addressed. Keyed by `sha256(bytes)`. Provenance is a separate index joined by hash, so re-ingesting the same bytes from a second vendor increases provenance multiplicity without duplicating storage.

**No mutations.** Vendor corrections are new entries with new provenance referring to the original by hash. The raw store is a DAG of observations and corrections, not a rolling "current truth" table.

## Feature contract

A **feature-family spec** is an AI-produced artifact containing:
- A pure-function definition `f(raw_entries) → tensor` — no hidden state, no clock-reads beyond those declared.
- Declared dependency set: which raw-store entries the feature reads.
- Cost annotation: compute, LLM (if any), storage.
- Lineage commitment: given spec version + dependency set, recomputation is byte-identical.

Specs are content-addressed: `spec_id = sha256(canonical_body_with_op_versions_folded_in)`. Any change produces a new `spec_id`. Discover emits specs; Patterns carry `spec_ref`, never inlined feature definitions.

## LLM-as-feature

A spec may call an LLM. When it does:
- Spec freezes model version, prompt template, sampling parameters. Any change is a new spec version.
- The raw response is stored in the raw store with provenance `(model_id, fetch_time, prompt_hash, params_hash)`. Later inspection can catch model-behavior drift.
- Cost annotation is tracked; realized drift above tolerance fires a `CostDrift` audit record.

LLM-as-feature is admissible under §0a because the LLM transforms raw bytes into a numeric feature (e.g., extract a specific number from a document), not suggest *what to look for*. The discrimination matters: a prompt of the shape "return the value of field X" is admissible; a prompt of the shape "find anything interesting" is operator-supplied targeting laundered through a model and is not.

## Representation for Discover

Discover reads through an **access layer** that:
- Serves only data with `vendor_timestamp ≤ t` for explicit query time `t`.
- Rate-limits request volume so a single cycle cannot exhaust `$B`.
- Logs every read.

`access` is the *only* read path for Discover, EmpiricalTest, and Council. Direct rawstore access from these stages is forbidden by static-analysis tests.

## What the operator does here

Approve a new vendor subscription when its cost enters the envelope; kill a subscription if ToS violates §2. The operator does not choose features, does not rank them, does not name what data the system should focus on within the admissible scope.
