# Phases 1–2 — Foundation + Data Pipeline

**Goal**: the bones of [../methodology/09-audit.md](../methodology/09-audit.md), the raw store from [../methodology/02-data-and-representation.md](../methodology/02-data-and-representation.md), and the feature-family spec runner. Nothing else runs until these are correct.

## Dependencies
- Phase 0 ([00-operator-decisions.md](00-operator-decisions.md)) is done and `config/envelope.yaml` exists.

## Parallelism within this phase
- 1.1, 1.2, 1.3 can all start once envelope is fixed. 1.4 depends on 1.1–1.3. 2.1 adapters can begin in parallel once 1.1 is stable. 2.2 depends on 1.1+1.4.

---

## 1.1 Content-addressed raw store — **[S]**

> Read [../methodology/02-data-and-representation.md](../methodology/02-data-and-representation.md). Implement a Python module `rawstore/` that provides:
> - `put(bytes, provenance) -> hash`: appends bytes, stores provenance triple separately, keyed by sha256. Idempotent on repeat hash.
> - `get(hash) -> bytes`
> - `provenance(hash) -> list[provenance_triple]`
> - `corrections(hash) -> list[hash]` (links to correction entries referring to the original)
>
> Storage format: per-day directory of `<hash-prefix>/<hash>` files for bytes + a SQLite index for provenance and corrections. Include property-based tests for idempotency and provenance-multiplicity. No mutation of existing entries — corrections are new entries that reference originals by hash.

## 1.2 Append-only hash-chained audit log — **[S]**

> Read [../methodology/09-audit.md](../methodology/09-audit.md). Implement `audit/` that writes JSONL records with `record_hash`, `prev_hash`, chain verification, daily rotation at midnight UTC, cross-file continuity. Provide:
> - `append(record: dict) -> record_hash`
> - `verify_chain(day: date) -> bool`
> - `verify_cross_day(range) -> bool`
>
> Records must be canonicalized before hashing (sort keys, no trailing whitespace). Include a test that tampering with any record in a day-file breaks the chain from that point forward. Every record has the common fields from [../methodology/09-audit.md](../methodology/09-audit.md) §"Record categories".

## 1.3 Access layer — **[S]**

> Implement `access/` per [../methodology/02-data-and-representation.md](../methodology/02-data-and-representation.md) §"Representation for Propose": a thin wrapper over `rawstore` that serves data only with `vendor_timestamp ≤ query_time`, rate-limits by call volume per cycle, and logs every read into the audit module from 1.2. No other module in the system may read the raw store directly — enforce this by having `rawstore` accept reads only from the `access` layer's API surface.

## 1.4 Stage orchestration shell — **[M]**

> Read [../methodology/01-architecture.md](../methodology/01-architecture.md). Implement `pipeline/` with a `Stage` base class: typed inputs/outputs, content-addressed artifacts, versioning, per-invocation cost ceilings (compute, LLM, data-read), and invariant assertions on outputs. Each `Stage.run()` automatically emits an audit record via 1.2. Implement `PipelineDAG` that can topologically run stages, refuses to run on a missing invariant, and skips on content-hash match (reproducibility / idempotency). Include a test that re-running an unchanged DAG produces zero new audit records except re-run-start/end markers.

---

## 2.1 Ingest adapters — **[M, one per vendor]**

One coding session per vendor. Plan for 2–4 initial vendors; more is Phase 11+.

Coding prompt, per vendor:

> Implement an Ingest adapter for `<vendor>` that pulls `<data type>` and writes entries to `rawstore` with a correct provenance triple. Include: retry/backoff, dedup on byte hash, vendor-timestamp extraction from the raw response (never from our clock), cost tracking against `E_ops`. Write integration tests against a recorded vendor response fixture. The adapter is a `Stage` subclass from 1.4 and emits Ingest records per [../methodology/09-audit.md](../methodology/09-audit.md) §"Ingest records".

## 2.2 Feature-family spec runner — **[M]**

> Implement `represent/` per [../methodology/02-data-and-representation.md](../methodology/02-data-and-representation.md) §"Feature contract". A feature spec is a pure-function definition plus declared dependencies plus cost annotation plus lineage commitment. Provide:
> - spec registration + versioning,
> - deterministic evaluation from raw-store inputs,
> - lineage tracking back to raw-store hashes,
> - byte-identical reproducibility tests.
>
> The spec format must allow Phase 3's `Propose` stage to emit new specs programmatically (no hand-coding of feature files required). The runner is a `Stage` subclass from 1.4.

## 2.3 LLM-as-feature harness — **[S]**

> Extend 2.2 to support an LLM call as a feature. When a spec calls an LLM, freeze model version, prompt template, temperature, and sampling params. Log the raw response (with provenance `(model_id, fetch_time, prompt_hash)`) into `rawstore` before returning the parsed feature value. Any change to model/prompt/params is a new spec version. Cost per output is tracked and compared against the spec's annotation; a drift above pre-committed tolerance flags the spec for re-cost.

---

## Exit criteria for this phase

- Every write to `rawstore` or `audit` has an accompanying test.
- A sample vendor ingest → feature evaluation → audit record round-trip runs end-to-end with byte-identical reproducibility on re-run.
- `verify_chain` and `verify_cross_day` pass on a week of test data.
- `access` refuses future-timestamped reads (property-tested).
