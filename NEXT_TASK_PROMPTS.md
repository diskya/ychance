# Next Task Prompts

Copy one prompt at a time into the coding or research agent. Do not run these as one giant task.

Global instruction for every prompt: read `Objective.md` first, especially §0 and §7. Do not introduce any operator-supplied target taxonomy or content-shaped discovery target. Preserve the existing foundation modules unless the prompt explicitly scopes a change to them. Do not resurrect trading-shaped vocabulary or deleted v2.1 modules.

Recommended order: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16. Prompt 11 (`council_decide/`) depends on Prompt 9 (`independence/`) unless you explicitly ask for the fallback behavior described there.

---

## Prompt 1 — Foundation Sanity Check

You are working in `/home/ubuntu/ychance`.

Task: verify the surviving foundation is clean before Phase 3 starts. Do not make code changes unless a failure is clearly caused by stale imports or a trivial test-environment mismatch.

Read:
- `Objective.md`
- `STATUS.md`
- `plan/README.md`

Run:
- `uv run pytest -q`
- `rg -n "rule|trade|position|entry|exit|pnl|validate_report|paper-deploy|graduate|sizing|broker" . --glob '!uv.lock'`

Report:
- Whether tests pass.
- Any remaining trading-shaped vocabulary, grouped as intentional docs/history vs code/test defects.
- Whether Phase 3a can begin.

Do not implement Phase 3a in this task.

---

## Prompt 2 — Phase 3a: Pattern Object

You are working in `/home/ubuntu/ychance`.

Task: implement `pattern/`, the replacement for the deleted trading-shaped `rule/` module.

Read:
- `Objective.md` §0, §4, §7
- `methodology/03-discovery-loop.md` "Pattern object"
- `methodology/04-empirical-test.md`
- `plan/02-discovery-loop.md` section 3a
- Existing `represent/`, `pipeline/`, and `tests/represent/`

Implement:
- A `Pattern` object with fields `(spec_ref, assertion, scope, observation_window, replication_protocol)`.
- Stable canonical serialization.
- `pattern_id = sha256(canonical_body_with_op_versions_folded_in)`.
- Evaluation of the assertion through the existing access/registry path, not direct raw-store reads.
- Round-trip serialization.
- Tests for hash stability, round-trip behavior, evaluation behavior, and no direct raw-store import.
- A static guard test that `pattern/` does not import or define trading-shaped vocabulary such as `position`, `trade`, `pnl`, `entry`, `exit`, `horizon`.

Constraints:
- Reuse existing local patterns from `represent/` where appropriate.
- Do not re-create `rule/`.
- Do not add any trading, sizing, or execution concepts.

Verification:
- `uv run pytest -q`
- Targeted test command for the new `pattern/` tests.

Final response:
- List files changed.
- Summarize the `Pattern` API.
- State test results.

---

## Prompt 3 — Phase 3b Research: Discover Agent Design

You are working in `/home/ubuntu/ychance`.

Task: produce a short design for `discover/`. Do not write code.

Read:
- `Objective.md` §0, §4, §7
- `methodology/03-discovery-loop.md`
- `methodology/02-data-and-representation.md`
- `methodology/09-audit.md`
- `plan/02-discovery-loop.md` section 3b
- Existing `access/`, `represent/`, `pipeline/`, `audit/`

Design:
- A tool-using agent loop that emits candidate `Pattern` objects.
- Fixed tool surface: `inspect_spec`, `compute`, `propose_spec`, `test_assertion`, `submit_pattern`.
- All data access through `access`; no direct raw-store reads.
- Per-cycle hard cost cap and kill behavior.
- Cost-tier discipline: cheaper model for tool-call iteration, frontier model only at final Pattern submission.
- Prompt scaffold that tells the agent how to use tools and submit Patterns without naming any phenomenon, factor, category, or specific Pattern target.
- Operator input handling: only tool requests and red-team requests; content-shaped inputs rejected with `shape_classification`.
- No-Pattern cycle handling.
- Audit payloads required to reconstruct the tool trace and submitted Patterns.

Return:
- A concise design document.
- Module boundaries and public interfaces.
- Data structures.
- Failure modes and how the implementation should test them.

Do not implement code in this task.

---

## Prompt 4 — Phase 3b Implementation: Discover Agent

You are working in `/home/ubuntu/ychance`.

Task: implement `discover/` from the approved design.

Read:
- The approved Discover design from Prompt 3.
- `Objective.md` §0, §4, §7
- `methodology/03-discovery-loop.md`
- `methodology/09-audit.md`
- `plan/02-discovery-loop.md` section 3b
- Existing `pattern/`, `access/`, `represent/`, `pipeline/`, `audit/`

Implement:
- `discover/` as a `Stage` subclass.
- Tool wrappers for `inspect_spec`, `compute`, `propose_spec`, `test_assertion`, `submit_pattern`.
- Audit logging for every tool call.
- Operator input logging with `shape_classification`.
- Mechanical rejection of content-shaped operator inputs.
- Per-cycle cost cap enforcement.
- Cost-tier discipline: cheaper model for tool-call iteration, frontier model only at final Pattern submission.
- No-Pattern as a valid output.
- Tests with mocked LLM/tool calls.

Constraints:
- No direct raw-store access.
- Do not let prompt text name target phenomena, factors, categories, or specific Pattern targets.
- Agent rationale may be logged, but must be clearly marked as withheld from Council.

Verification:
- `uv run pytest -q`
- Tests proving cost cap, audit trace reconstruction, no-Pattern output, and input-shape rejection.

Final response:
- List files changed.
- State how to run a Discover cycle in tests.
- State test results.

---

## Prompt 5 — Phase 3c: EmpiricalTest

You are working in `/home/ubuntu/ychance`.

Task: implement `empirical_test/`.

Read:
- `Objective.md`
- `methodology/04-empirical-test.md`
- `methodology/03-discovery-loop.md`
- `methodology/09-audit.md`
- `plan/02-discovery-loop.md` section 3c
- Existing `pattern/`, `partitions/`, `access/`, `pipeline/`, `audit/`

Implement:
- `EmpiricalTest` as a `Stage` subclass.
- Deterministic held-out window selection from `pattern_id` and `replication_protocol`.
- Raw-store lineage disjointness check between observation window and held-out windows.
- Assertion re-evaluation on each held-out window.
- Partition-aware results using `partitions/`.
- Perturbation controls: time-shuffled, scope-randomized, threshold-perturbed.
- `EmpiricalTestReport` with verdict, partition results, perturbation results, disjointness audit, and compute cost.
- Audit record emission.

Tests:
- Deterministic verdict for same raw-store state and same `pattern_id`.
- Disjointness failure is caught.
- Each perturbation control rejects a synthetic Pattern designed to fail it.
- Partition results are included.

Verification:
- `uv run pytest -q`

Final response:
- List files changed.
- Explain the pass/fail gate.
- State test results.

---

## Prompt 6 — Phase 3d: Originality Filter

You are working in `/home/ubuntu/ychance`.

Task: implement `originality/` for Pattern fingerprints.

Read:
- `Objective.md` §0
- `methodology/03-discovery-loop.md` "Originality filter" and "Anti-pattern list"
- `methodology/09-audit.md`
- `plan/02-discovery-loop.md` section 3d
- Existing `pattern/`, `pipeline/`, `audit/`

Implement:
- A bounded mutable list of computable matchers over Pattern fingerprints.
- Reject on fingerprint reducibility.
- No LLM judgment inside the matcher decision.
- Audit records with `pattern_id`, `result`, `matched_anti_pattern` if any, and `anti_pattern_list_version`.
- M2a-empty-on-failure behavior in spirit: if the list is found net-harmful by later meta-validation, it can be emptied as a unit.

Constraints:
- The list is subtractive only. It must never suggest what to propose.
- Do not add target categories or named Pattern families.

Verification:
- `uv run pytest -q`
- Tests for matcher stability, pass/reject behavior, bounded list behavior, and audit emission.

Final response:
- List files changed.
- Explain matcher API.
- State test results.

---

## Prompt 7 — Phase 4.1: Council Voter Wrapper

You are working in `/home/ubuntu/ychance`.

Task: implement `council_llm/` for Pattern review.

Read:
- `Objective.md`
- `methodology/05-council.md`
- `methodology/09-audit.md`
- `plan/03-council.md` section 4.1
- Existing LLM client/cache patterns in `represent/`

Implement:
- `council_llm/` voters as `Stage` subclasses.
- A common voter interface:
  ```python
  def vote(pattern, empirical_test_report, raw_slice) -> (vote, rationale, citations)
  ```
- Support for at least two configured vendor families through an adapter boundary.
- Sealed votes: no member sees another member's vote or rationale.
- No member sees Discover's free-text rationale.
- No member sees the proposing model identity.
- Cache by `(pattern_hash, empirical_test_hash, member_version)`.
- Two-phase query: `approve` / `reject` / `need full review`; only `need full review` triggers full rationale generation.
- Audit records for member vote, rationale, citations, cache status, and cost.

Constraints:
- Prompt scaffold asks the council member to judge the Pattern and EmpiricalTest evidence. It must not ask for trading relevance, sizing, execution, or target discovery ideas.

Verification:
- `uv run pytest -q`
- Tests for redaction, sealed votes, cache hits, two-phase query behavior, and audit records.

Final response:
- List files changed.
- Explain how to configure vendor families.
- State test results.

---

## Prompt 8 — Phase 4.3 Research: Independence Audit Design

You are working in `/home/ubuntu/ychance`.

Task: design the Council independence audit. Do not write code.

Read:
- `Objective.md` M7
- `methodology/05-council.md` "Independence audit"
- `plan/03-council.md` section 4.3
- `plan/00-operator-decisions.md`

Design:
- Pairwise rationale-similarity procedure.
- A defensive-diversity embedder that is not from any council family.
- Similarity metric and justification.
- Initial `theta_indep` threshold and sensitivity approach.
- Sparse-data operating rule.
- Collapsed-pair mechanics for the decision rule.
- Simulated validation cases:
  - identical models should collapse;
  - demonstrably distinct families should not collapse;
  - correlated blind spots should collapse even if surface wording differs.

Return:
- A concise design document with algorithm, starting parameters, and implementation interfaces.
- Tests the implementation should include.

Do not implement code in this task.

---

## Prompt 9 — Phase 4.3 Implementation: Independence Audit

You are working in `/home/ubuntu/ychance`.

Task: implement `independence/` from the approved design.

Read:
- Approved independence-audit design from Prompt 8
- `methodology/05-council.md`
- `methodology/09-audit.md`
- `plan/03-council.md` section 4.3
- Existing `council_llm/`, `council_decide/`, `audit/`

Implement:
- Independence audit runnable at M2a and on demand.
- Input: historical `(pattern, member, vote, rationale)` tuples.
- Output: `{member: independent_group_id}` classification.
- Pairwise rationale similarity logging.
- Audit records for inputs, similarities, threshold, and final classification.
- Tests for the three simulated validation cases from the design.

Verification:
- `uv run pytest -q`

Final response:
- List files changed.
- Explain classification output.
- State test results.

---

## Prompt 10 — Phase 4.4: Council Calibration

You are working in `/home/ubuntu/ychance`.

Task: implement `council_calibration/`.

Read:
- `methodology/05-council.md` "Calibration"
- `methodology/08-falsification-clock.md`
- `methodology/09-audit.md`
- `plan/03-council.md` section 4.4

Implement:
- Per-member tracking of re-replication outcomes for Patterns each member approved.
- Configurable pre-committed threshold for systematic approval failure.
- Flagging for zero-weighting at next M2a.
- Audit output consumed by Review/M2a.

Constraints:
- This is not a single-Pattern gate.
- Do not let the operator manually weight members.

Verification:
- `uv run pytest -q`
- Tests for calibrated member, failing member, sparse-data/null-op behavior, and audit output.

Final response:
- List files changed.
- Explain threshold behavior.
- State test results.

---

## Prompt 11 — Phase 4.2: Council Decision Rule

You are working in `/home/ubuntu/ychance`.

Task: implement `council_decide/`.

Read:
- `methodology/05-council.md` "Decision rule"
- `methodology/09-audit.md`
- `plan/03-council.md` section 4.2
- Existing `council_llm/` from Prompt 7
- Existing `independence/` from Prompt 9

Implement:
- Aggregate Council votes using the current independence classification.
- Archive decision rule: at least two `approve` votes from mutually independent members.
- Any independent `reject` blocks archive entry.
- Approved Patterns are routed to Archive.
- Rejected Patterns are logged with blocking rationales and are not auto-resubmitted.
- Aggregate decision audit records.

Fallback if `independence/` is not yet implemented:
- Treat every configured member as its own independent group.
- Log the fallback clearly in the decision audit record.
- Keep the interface compatible with the later `independence/` classification output so the fallback can be removed without rewriting callers.

Constraints:
- Do not create an operator override path.
- Do not allow manual archive approval.

Verification:
- `uv run pytest -q`
- Tests for independent approvals, independent reject block, collapsed-member behavior, fallback classification behavior, and audit output.

Final response:
- List files changed.
- Explain decision semantics.
- State test results.

---

## Prompt 12 — Archive Persistence

You are working in `/home/ubuntu/ychance`.

Task: implement `archive/`, the append-only corpus of Council-approved Patterns.

Note: this module is listed in `STATUS.md` under Phase 5 and is required before the archive browser in `plan/06-operator-ux.md` section 5.2 can be implemented.

Read:
- `Objective.md`
- `methodology/03-discovery-loop.md` "Archive"
- `methodology/08-falsification-clock.md`
- `methodology/09-audit.md`
- `plan/06-operator-ux.md` section 5.2
- Existing `pattern/`, `empirical_test/`, `council_decide/`, `audit/`

Implement:
- Append-only archive entries for approved Patterns.
- Stored provenance: Pattern body, observation window, EmpiricalTest report hash, Council decision hash, upstream artifact hashes.
- No edit/delete path for archived Patterns.
- Re-replication annotations appended as new records, never mutating the original entry.
- Read-only query API for the UX/browser.
- Audit records for archive entry and re-replication annotation.

Constraints:
- No manual operator approval.
- No "remove from archive" or "mark wrong" mutation path.

Verification:
- `uv run pytest -q`
- Tests for append-only behavior, provenance completeness, re-replication annotation, and absence of edit/delete affordances.

Final response:
- List files changed.
- Explain archive API.
- State test results.

---

## Prompt 13 — Phase 5.1: Weekly Pane

You are working in `/home/ubuntu/ychance`.

Task: implement the weekly operator pane as a simple local interface.

Read:
- `methodology/07-operator-workflow.md`
- `methodology/09-audit.md`
- `plan/06-operator-ux.md` section 5.1
- Existing `archive/`, `audit/`, `pipeline/`

Implement:
- Cycle log: this week's Discover cycles, Patterns proposed, stage reached, archived count.
- New archive entries: browsable list showing `pattern_id`, `spec_ref`, `assertion`, `scope`, `observation_window`, EmpiricalTest verdict, Council vote summary, and link/detail path for provenance chain.
- Invariant failures: read-only list.
- Envelope status: `$_spent / $B`, projected runway, acknowledge action.
- Bias-log textarea: prompt text from `plan/06-operator-ux.md`; empty submission refused; `none` accepted.
- Operator weekly audit records for every operator action.

Constraints:
- No operator approval/rejection affordance for Patterns.
- No archive mutation affordance.

Verification:
- `uv run pytest -q`
- Tests appropriate to the chosen local interface.
- Test that weekly audit records are written.

Final response:
- List files changed.
- Explain how to run the weekly pane locally.
- State test results.

---

## Prompt 14 — Phase 5.2: Archive Browser

You are working in `/home/ubuntu/ychance`.

Task: implement the read-only archive browser.

Read:
- `methodology/07-operator-workflow.md`
- `methodology/09-audit.md`
- `plan/06-operator-ux.md` section 5.2
- Existing `archive/`, `audit/`

Implement:
- Read-only list of archived Patterns.
- Filters by `spec_ref`, `scope`, archive date, and re-replication status.
- Detail view showing full Pattern body, observation window, EmpiricalTest report, Council votes, and provenance chain.
- Council rationales redacted from the operator UI, while remaining available in the audit log for M2a Council review.

Constraints:
- No "remove from archive", "edit", "annotate as wrong", or manual approval affordance.
- If a Pattern fails re-replication, display the appended system annotation; the operator does not create it.

Verification:
- `uv run pytest -q`
- Static or integration check that no edit/remove/archive-mutation affordance exists.
- Tests for filters and detail view.

Final response:
- List files changed.
- Explain how to run the archive browser locally.
- State test results.

---

## Prompt 15 — Phase 5.3: M2a Pane

You are working in `/home/ubuntu/ychance`.

Task: implement the quarterly M2a pane.

Read:
- `methodology/07-operator-workflow.md`
- `methodology/08-falsification-clock.md`
- `methodology/09-audit.md`
- `plan/06-operator-ux.md` section 5.3
- Existing `audit/`, `empirical_test/`, `independence/`, `council_calibration/`, `originality/`

Implement:
- Architecture-diff viewer reading M2a Architecture records.
- EmpiricalTest meta-validation result display, including null-op early in the clock.
- Council membership review: independence audit classification and per-member calibration.
- Anti-pattern list track record.
- Bias-log drift report display. The operator reads the report, not raw bias-log entries.
- Clock-health snapshot: `t/T`, `$_spent/$B`, archive count, re-replicated count, originality-cleared count, projection vs. `N_min`.

Constraints:
- Consult-only. No ad-hoc architecture editing.
- Architecture changes, if surfaced, are all-or-nothing accept/reject of Council's diff.

Verification:
- `uv run pytest -q`
- Tests for rendering null-op states and populated states.
- Tests that raw bias-log entries are not displayed in this pane.

Final response:
- List files changed.
- Explain how to run the M2a pane locally.
- State test results.

---

## Prompt 16 — Phase 5.4: Bias Log

You are working in `/home/ubuntu/ychance`.

Task: implement or harden the bias-log component used by the weekly pane.

Read:
- `Objective.md` §0, §4, §7
- `methodology/07-operator-workflow.md`
- `methodology/09-audit.md`
- `plan/06-operator-ux.md` section 5.4
- Existing weekly pane code if Prompt 13 has already run

Implement:
- One bias-log entry per week.
- Free text accepted.
- Empty submission refused.
- `none` accepted and distinct from missing.
- Entry logged as an Operator weekly record.
- M2a review path exposes Council-produced drift reports, not raw self-review by the operator.

Constraints:
- Do not add content-shaped suggestions to the Discover co-research interface.
- Do not let the bias-log form become an input channel to Discover.

Verification:
- `uv run pytest -q`
- Tests for empty refusal, `none`, non-empty entry, missed-week distinction, and audit record emission.

Final response:
- List files changed.
- Explain how the bias log is stored and reviewed.
- State test results.
