# Phase 3b Discover Design

Design target for `discover/`. This is the implementation contract for the
Phase 3b coding pass; it is not executable code.

## Purpose

`discover/` is a bounded tool-using agent loop that emits candidate `Pattern`
objects:

```text
Pattern = (spec_ref, assertion, scope, observation_window, replication_protocol)
```

The stage may return no candidates. `NoPattern` is a valid cycle result and is
audited as a first-class outcome.

## Constraints

- Fixed tool surface only: `inspect_spec`, `compute`, `propose_spec`,
  `test_assertion`, `submit_pattern`.
- All data access routes through `access.AccessLayer`; `discover/` must not
  import or call `rawstore`.
- Each cycle has a hard cost cap. Once the next step cannot fit under the cap,
  the cycle stops before making the call and emits a killed-budget record.
- Cheap model handles tool-call iteration. Frontier model is used only after a
  tested draft exists and only for final Pattern submission.
- Operator input is accepted only as `tool_request` or `red_team_request`.
  Content-shaped input is rejected and audited with
  `shape_classification: flagged`.
- Agent prompt text must not name any phenomenon, factor, category, or specific
  Pattern target.
- Free-text rationale may be logged but is withheld from Council and from the
  downstream Pattern payload.

## Module Boundaries

`discover/stage.py`
- `DiscoverStage(Stage)`.
- Public entry is `Stage.run(DiscoverInput, envelope={"cycle_id": ...})`.
- Owns cycle orchestration, invariant checks, and output serialization.

`discover/tools.py`
- `DiscoverToolRouter`.
- Implements the five allowed tools and refuses any other tool name.
- Calls `represent` and `pattern` APIs; never reads raw data except through
  the provided `AccessLayer`.

`discover/input_shape.py`
- `classify_operator_input(text) -> ShapeClassification`.
- Normalizes accepted inputs into non-content directives.
- Logs rejected input verbatim but never passes it to the agent.

`discover/budget.py`
- `CycleBudget`.
- Tracks realized and reserved compute, LLM, and data-read spend.
- Exposes `reserve_*` and `charge_*`; failure raises a budget-kill exception
  that the stage converts to a clean cycle result.

`discover/prompts.py`
- Cheap iteration prompt builder.
- Frontier submission prompt builder.
- Static guard tests should scan these prompt templates for forbidden target
  vocabulary.

`discover/audit.py`
- Helpers for cycle start/end, operator input classification, model calls,
  tool-call start/end, no-pattern, budget kill, and Pattern submission records.

## Public Interfaces

```python
@dataclass(frozen=True)
class DiscoverInput:
    cycle_id: str
    query_time: str
    spec_ids: tuple[str, ...]
    archive_snapshot_hash: str | None
    anti_pattern_list_hash: str | None
    operator_inputs: tuple[str, ...]
    max_patterns: int

@dataclass(frozen=True)
class DiscoverOutput:
    status: Literal["submitted", "no_pattern", "killed_budget", "error"]
    pattern_ids: tuple[str, ...]
    pattern_artifact_hashes: tuple[str, ...]
    tool_trace_hash: str
    cost_used: DiscoverCostUsed
    no_pattern_reason: str | None
```

Tool signatures:

```python
inspect_spec(spec_id) -> InspectSpecResult
compute(spec_id, window) -> ComputeResult
propose_spec(body) -> ProposeSpecResult
test_assertion(spec_ref, assertion, window) -> TestAssertionResult
submit_pattern(pattern_body) -> SubmitPatternResult
```

`submit_pattern` is accepted only in the frontier submission phase and only if
the same cycle already has a successful `test_assertion` for the submitted
`spec_ref`, `assertion`, and `observation_window`.

## Data Structures

`ToolCallRecord`
- `tool_call_id`
- `step_index`
- `phase`: `cheap_iteration | frontier_submission`
- `tool_name`
- `args_hash`
- `result_hash`
- `outcome`
- `error_type`
- `cost_before`
- `cost_after`
- `start_record_hash`
- `end_record_hash`

`AssertionFingerprint`
- `fingerprint_hash`
- `spec_ref`
- `assertion_hash`
- `window`
- `result`
- `summary_hash`
- `lineage_hashes`

`SubmittedPattern`
- `pattern_id`
- `pattern_body_hash`
- `source_tool_call_ids`
- `observation_window`
- `reserved_windows`
- `rationale_hash`

`OperatorInputRecord`
- `input_text`
- `shape_classification`: `tool_request | red_team_request | flagged`
- `normalized_directive`
- `agent_response`

## Loop Control

1. Start cycle and call `access.begin_cycle(cycle_id)`.
2. Audit cycle start, budget cap, model configuration, archive snapshot hash,
   anti-pattern-list hash, and spec snapshot.
3. Classify every operator input. Flagged inputs are logged and omitted.
4. Cheap model iterates over `inspect_spec`, `compute`, `propose_spec`, and
   `test_assertion`.
5. Each tool call is bracketed by `DiscoverToolCallStart` and
   `DiscoverToolCallEnd`. Nested `Access` records provide the raw read trace.
6. If no tested draft exists before the remaining budget cannot support another
   useful cheap step, return `no_pattern`.
7. If a tested draft exists, reserve frontier max cost before dispatch.
8. Frontier model may only call `submit_pattern` or return `NO_PATTERN`.
9. On submission, finalize/load the `Pattern`, serialize it byte-identically,
   reserve Discover-touched windows through `access.reserve_window`, write the
   Pattern artifact, and return `submitted`.
10. On budget exhaustion, return `killed_budget`; do not submit partial work.

## Tool Behavior

`inspect_spec`
- Validates `spec_id` against `SpecRegistry`.
- Returns description, output schema, declared cost, a bounded sample summary,
  and a per-call cost estimate.

`compute`
- Runs the spec on an explicit window through `RepresentStage`.
- Uses `AccessLayer` for every raw read.
- Records the touched window as Discover lineage for later reservation.
- Returns summary statistics and bounded sample values, not arbitrary raw data.

`propose_spec`
- Registers a spec through `SpecRegistry`.
- Rejects specs with open-ended LLM discovery prompts. LLM-as-feature is allowed
  only for declared extraction/transformation prompts with frozen model,
  template, params, and cost.

`test_assertion`
- Evaluates one admissible assertion over one explicit window.
- Returns boolean result plus fingerprint and lineage hashes.
- Does not commit a Pattern.

`submit_pattern`
- Finalizes a `Pattern`.
- Requires prior successful `test_assertion` in the same cycle.
- Stores only the Pattern body downstream; rationale remains audit-only.

## Prompt Scaffold

```text
You are a tool-using discovery agent. Use only the provided tools and their
outputs. Do not use operator text as a content hint. Operator inputs have
already been classified; only normalized directives may affect tool choice.

Your job in this cycle is to inspect available specs, run bounded computations,
propose valid specs when needed, test computable assertions, and either submit
a valid Pattern or return NO_PATTERN.

Use inspect_spec before expensive compute. Use compute only on explicit windows.
Use test_assertion before any submission. Do not submit unless the Pattern body
is fully computable, has a frozen observation window, and includes a replication
protocol. If evidence is insufficient, return NO_PATTERN.

Do not invent unobserved facts. Do not include rationale in submitted Pattern
bodies. Rationale may be logged but is not part of downstream review.
```

## Audit Payloads

Required records:

- `DiscoverCycleStart`: `cycle_id`, query time, caps, model ids, prompt hashes,
  archive snapshot hash, anti-pattern-list hash, spec snapshot hash.
- `CoResearchInput`: verbatim input, `shape_classification`, normalized
  directive or rejection reason, agent response.
- `DiscoverModelCall`: phase, model id, prompt hash, params hash, token counts,
  reserved cost, realized cost, output hash.
- `DiscoverToolCallStart`: tool id, tool name, args hash, phase, cost before.
- `DiscoverToolCallEnd`: tool id, result hash, outcome, error, cost after,
  access read count delta.
- `DiscoverNoPattern`: reason, steps used, budget remaining.
- `DiscoverBudgetKill`: attempted action, reserved/realized cost, remaining cap.
- `DiscoverSubmission`: `pattern_id`, Pattern body hash, source tool ids,
  fingerprint hash, reserved windows, rationale hash.
- Stage-level `Discover` record from `Stage.run`.

Replay requirement: an auditor can reconstruct the ordered tool trace, prompt
hashes, model outputs by hash, every access read, and every submitted Pattern
from audit plus artifacts.

## Failure Modes And Tests

- Static analysis rejects any `discover/` import of `rawstore`.
- Static analysis rejects forbidden target vocabulary in prompt templates.
- Unknown tool names are rejected and audited.
- Flagged operator input writes `shape_classification: flagged` and is omitted
  from agent context.
- Accepted operator input is reduced to a non-content directive before agent use.
- Cheap model cannot call `submit_pattern`.
- Frontier model cannot call any tool except `submit_pattern`.
- `submit_pattern` without prior successful `test_assertion` fails.
- Invalid spec body, invalid assertion, invalid Pattern body, and mismatched
  `pattern_id` are rejected and audited.
- Cost cap breach stops before the next call and produces `killed_budget`.
- Access read limit exhaustion produces `killed_budget`, not partial submission.
- No candidate produces `no_pattern` with a trace hash.
- Submitted Pattern reserves observation and tool-touched Discover windows.
- Rationale appears only in audit/artifacts and not in downstream Pattern output.
- Replay test reconstructs the same tool trace hash and submitted Pattern ids.
