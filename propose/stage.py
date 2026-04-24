"""Propose stage: generates candidate rules via a two-pass LLM workflow.

The stage:
1. Draft pass: LLM generates multiple candidate rules
2. Adjudicate pass: LLM refines and scores the candidates
3. Validation: all candidates are checked for executability and grounding

Only candidates that pass all validation checks are emitted.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext
from rule import Rule, finalize_rule, load_rule
from represent.llm_client import LLMClient, LLMResponse, params_hash, prompt_hash

from .budget import BudgetConfig, load_budget_from_config
from .prompts import make_adjudicate_prompt, make_draft_prompt
from .schema import CandidateValidationError, validate_candidate_shape
from .scoring import score_adjudicate_candidate, score_draft_candidate


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposeInput:
    """Input to the Propose stage.

    Attributes:
        cycle_id: identifier for this discovery cycle
        query_time: time at which the stage is running (ISO-8601 string or datetime)
        slice_description: human-readable description of the data slice
        available_spec_ids: list of spec_id strings the LLM can reference
        input_slice_hashes: optional hashes for structured slice artifacts
        anti_pattern_list: optional list of patterns to avoid
        live_rule_groundings: optional list of current rule groundings for originality context
    """
    cycle_id: str
    query_time: str | datetime
    slice_description: str
    available_spec_ids: list[str]
    input_slice_hashes: list[str] | None = None
    anti_pattern_list: list[dict[str, Any]] | None = None
    live_rule_groundings: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.query_time, datetime):
            object.__setattr__(self, "query_time", self.query_time.isoformat())


@dataclass
class ProposeOutput:
    """Output from the Propose stage.

    Attributes:
        candidates: list of Rule objects that passed all validation checks
    """
    candidates: list[Rule]


@dataclass(frozen=True)
class _CandidateAuditEntry:
    """Audit data for a single candidate."""
    rule_id: str
    rule_object: Any
    grounding: dict[str, Any]
    free_text_rationale: str
    rule_hash: str
    draft_score: float
    adjudicate_score: float
    verdict: str  # "accepted" or "rejected"
    verdict_reason: str


@dataclass(frozen=True)
class _LLMCallAuditEntry:
    """Audit data for one LLM call or cache read."""
    pass_name: str
    model_version: str
    prompt_hash: str
    params_hash: str
    response_hash: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    llm_cost: float


class ProposeStage(Stage):
    """Two-pass LLM workflow for proposing candidate rules.

    Draft and adjudicate calls have separate configurable model ids. Drafted
    candidates only reach adjudicate review after passing a cheap local score
    threshold, so higher-cost calls are bounded by the draft filter.
    """

    name = "propose_stage"
    version = "1"
    audit_stage = "Propose"
    cost_ceiling = CostCeiling(compute_usd=0.5, llm_usd=10.0, data_reads=50)
    InputType = ProposeInput
    OutputType = ProposeOutput

    def __init__(
        self,
        *,
        artifacts,
        audit,
        access=None,
        writer=None,
        llm_client: Optional[LLMClient] = None,
        budget_config: Optional[BudgetConfig] = None,
    ):
        super().__init__(
            artifacts=artifacts,
            audit=audit,
            access=access,
            writer=writer,
        )
        self._llm_client = llm_client
        self._budget_config = budget_config or load_budget_from_config()
        self._candidate_audit_entries: list[_CandidateAuditEntry] = []
        self._llm_call_audit_entries: list[_LLMCallAuditEntry] = []

    def compute(self, inputs: ProposeInput, ctx: StageContext) -> ProposeOutput:
        """Compute method: execute the two-pass workflow."""
        if ctx.writer is None:
            raise RuntimeError("ProposeStage requires a writer for LLM caching")
        if ctx.access is None:
            raise RuntimeError("ProposeStage requires an AccessLayer")
        if self._llm_client is None:
            raise RuntimeError("ProposeStage requires an LLM client")
        self._candidate_audit_entries = []
        self._llm_call_audit_entries = []

        # Parse query_time
        if isinstance(inputs.query_time, str):
            query_time = datetime.fromisoformat(inputs.query_time)
        else:
            query_time = inputs.query_time

        # Draft pass: generate candidates
        draft_candidates = self._draft_pass(
            inputs=inputs,
            ctx=ctx,
            query_time=query_time,
        )

        # Adjudicate pass: filter and score candidates
        adjudicated = self._adjudicate_pass(
            draft_candidates=draft_candidates,
            ctx=ctx,
            query_time=query_time,
        )
        self._candidate_audit_entries.extend(adjudicated)

        # Validate and emit candidates
        emitted = []
        for candidate_entry in adjudicated:
            if candidate_entry.verdict == "accepted":
                try:
                    # Round-trip through load_rule to ensure full validity
                    rule = load_rule(candidate_entry.rule_object)
                    emitted.append(rule)
                except Exception as exc:
                    logger.warning(
                        f"Candidate {candidate_entry.rule_id} failed round-trip: {exc}"
                    )

        return ProposeOutput(candidates=emitted)

    def invariant(self, inputs: ProposeInput, outputs: ProposeOutput) -> None:
        """Verify output invariants."""
        if not isinstance(outputs.candidates, list):
            raise InvariantViolation("candidates must be a list")

        for candidate in outputs.candidates:
            if not isinstance(candidate, Rule):
                raise InvariantViolation(f"candidate must be a Rule, got {type(candidate)}")

            # Verify round-trip
            try:
                reloaded = load_rule(candidate.to_dict())
                if reloaded.rule_id != candidate.rule_id:
                    raise InvariantViolation("rule_id changed on round-trip")
            except Exception as exc:
                raise InvariantViolation(f"round-trip failed: {exc}")

    def audit_extra_payload(
        self,
        inputs: ProposeInput,
        outputs: ProposeOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        """Emit candidate-level audit records."""
        llm_calls = [asdict(entry) for entry in self._llm_call_audit_entries]
        return {
            "cycle_id": inputs.cycle_id,
            "input_slice_hashes": list(inputs.input_slice_hashes or []),
            "candidate_audits": [
                asdict(entry) for entry in self._candidate_audit_entries
            ],
            "accepted_rule_ids": [
                entry.rule_id
                for entry in self._candidate_audit_entries
                if entry.verdict == "accepted"
            ],
            "rejected_rule_ids": [
                entry.rule_id
                for entry in self._candidate_audit_entries
                if entry.verdict == "rejected"
            ],
            "model_version": [
                entry["model_version"] for entry in llm_calls
            ],
            "llm_calls": llm_calls,
        }

    def _serialize_output(self, outputs: ProposeOutput) -> bytes:
        return canonicalize(
            {"candidates": [candidate.to_dict() for candidate in outputs.candidates]}
        )

    def _deserialize_output(self, data: bytes) -> ProposeOutput:
        payload = json.loads(data.decode("utf-8"))
        return ProposeOutput(
            candidates=[load_rule(candidate) for candidate in payload["candidates"]]
        )

    def _draft_pass(
        self,
        inputs: ProposeInput,
        ctx: StageContext,
        query_time: datetime,
    ) -> list[dict[str, Any]]:
        """Draft pass: generate candidate rules."""
        # Short-circuit if budget exhausted
        if self._budget_config.target_candidates_per_cycle <= 0:
            return []

        prompt = make_draft_prompt(
            slice_description=inputs.slice_description,
            available_specs=inputs.available_spec_ids,
            anti_patterns=inputs.anti_pattern_list,
            live_rule_groundings=inputs.live_rule_groundings,
        )

        draft_response = self._call_llm(
            pass_name="draft",
            model=self._budget_config.draft_model_id,
            prompt=prompt,
            ctx=ctx,
            query_time=query_time,
        )

        # Parse response as JSON array
        candidates = self._parse_candidate_array(draft_response)

        # Score and filter candidates
        scored = []
        for candidate in candidates:
            try:
                validate_candidate_shape(candidate)
                score = score_draft_candidate(candidate)
                if score >= self._budget_config.draft_score_threshold:
                    scored.append({"candidate": candidate, "draft_score": score})
                else:
                    self._candidate_audit_entries.append(
                        self._rejected_entry(
                            candidate,
                            reason="draft_score_below_threshold",
                            draft_score=score,
                        )
                    )
            except (CandidateValidationError, ValueError, KeyError) as exc:
                logger.warning(f"Draft candidate invalid: {exc}")
                self._candidate_audit_entries.append(
                    self._rejected_entry(candidate, reason=f"invalid_shape: {exc}")
                )

        # Keep top N by score
        scored.sort(key=lambda x: x["draft_score"], reverse=True)
        kept = scored[:self._budget_config.target_candidates_per_cycle]

        return [item["candidate"] for item in kept]

    def _adjudicate_pass(
        self,
        draft_candidates: list[dict[str, Any]],
        ctx: StageContext,
        query_time: datetime,
    ) -> list[_CandidateAuditEntry]:
        """Adjudicate pass: filter and score draft candidates."""
        if not draft_candidates:
            return []

        candidates_json = json.dumps(draft_candidates)
        prompt = make_adjudicate_prompt(
            candidates_json=candidates_json,
            candidate_count=len(draft_candidates),
        )

        adjudicate_response = self._call_llm(
            pass_name="adjudicate",
            model=self._budget_config.adjudicate_model_id,
            prompt=prompt,
            ctx=ctx,
            query_time=query_time,
        )

        # Parse adjudicate response
        try:
            result = json.loads(adjudicate_response)
            decisions = result.get("decisions", [])
        except (json.JSONDecodeError, ValueError):
            logger.warning("Adjudicate response not valid JSON")
            decisions = []

        # Cross-reference decisions with candidates
        audit_entries = []
        for i, candidate in enumerate(draft_candidates):
            decision = next(
                (
                    d
                    for d in decisions
                    if isinstance(d, dict) and d.get("index") == i
                ),
                None,
            )

            # Try to finalize as rule
            try:
                finalize_rule(candidate)
                execution_succeeded = True
                execution_error = ""
            except Exception as exc:
                execution_succeeded = False
                execution_error = str(exc)

            # Compute grounding evaluation (simplified for now)
            grounding_evaluated = (
                execution_succeeded
                and "grounding" in candidate
                and isinstance(candidate["grounding"], dict)
                and "assertion" in candidate["grounding"]
            )

            draft_score = score_draft_candidate(candidate)
            adjudicate_score = score_adjudicate_candidate(
                candidate=candidate,
                execution_succeeded=execution_succeeded,
                grounding_evaluated=grounding_evaluated,
            )

            # Decide: keep if decision says so AND execution succeeded
            keep = (
                decision is not None
                and decision.get("keep", False)
                and execution_succeeded
            )

            verdict = "accepted" if keep else "rejected"
            verdict_reason = (
                decision.get("assessment", "")
                if decision
                else execution_error or "missing_adjudicate_decision"
            )

            # Extract grounding and rule_id
            try:
                rule = finalize_rule(candidate)
                rule_id = rule.rule_id
                grounding_dict = candidate.get("grounding", {})
                # Add rule_id to the candidate dict for storage
                candidate = dict(candidate)  # Make a copy
                candidate["rule_id"] = rule_id
            except Exception:
                rule_id = "invalid"
                grounding_dict = candidate.get("grounding", {})

            entry = _CandidateAuditEntry(
                rule_id=rule_id,
                rule_object=candidate,
                grounding=grounding_dict,
                free_text_rationale=decision.get("assessment", "") if decision else "",
                rule_hash=_rule_hash(candidate),
                draft_score=draft_score,
                adjudicate_score=adjudicate_score,
                verdict=verdict,
                verdict_reason=verdict_reason,
            )
            audit_entries.append(entry)

        return audit_entries

    def _call_llm(
        self,
        pass_name: str,
        model: str,
        prompt: str,
        ctx: StageContext,
        query_time: datetime,
    ) -> str:
        """Call the LLM, using cache when available."""
        if self._llm_client is None:
            raise RuntimeError("LLM client is required")
        if ctx.writer is None:
            raise RuntimeError("Writer is required")
        if ctx.access is None:
            raise RuntimeError("AccessLayer is required")

        # Compute hashes
        prompt_h = prompt_hash(prompt)
        params = {}
        params_h = params_hash(model=model, params=params)

        # Check cache
        ctx.charge_data_read(1)
        cached_bytes_hash = ctx.access.lookup_llm(model, prompt_h, params_h, query_time)

        if cached_bytes_hash is not None:
            # Hit
            ctx.charge_data_read(1)
            response_envelope = json.loads(
                ctx.access.get(cached_bytes_hash, query_time=query_time).decode("utf-8")
            )
            if response_envelope.get("model") != model:
                raise ValueError("cached llm response model mismatch")
            if response_envelope.get("prompt_hash") != prompt_h:
                raise ValueError("cached llm response prompt_hash mismatch")
            if response_envelope.get("params_hash") != params_h:
                raise ValueError("cached llm response params_hash mismatch")
            response_payload = response_envelope.get("response", {})
            if not isinstance(response_payload, dict):
                raise ValueError("cached llm response must contain a response object")
            self._llm_call_audit_entries.append(
                _LLMCallAuditEntry(
                    pass_name=pass_name,
                    model_version=model,
                    prompt_hash=prompt_h,
                    params_hash=params_h,
                    response_hash=cached_bytes_hash,
                    cache_hit=True,
                    input_tokens=int(response_payload.get("input_tokens") or 0),
                    output_tokens=int(response_payload.get("output_tokens") or 0),
                    llm_cost=0.0,
                )
            )
            return response_envelope.get("response", {}).get("text", "")

        # Miss: call LLM
        response: LLMResponse = self._llm_client.complete(
            model=model,
            prompt=prompt,
            params=params,
        )

        # Charge LLM cost
        charged_cost = 0.001
        ctx.charge_llm(charged_cost)  # Approximate cost; refine as needed

        # Write to cache
        response_body = {
            "model": model,
            "prompt_hash": prompt_h,
            "params_hash": params_h,
            "response": {
                "text": response.text,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
        }
        response_bytes = json.dumps(response_body).encode("utf-8")

        bytes_hash = ctx.writer.put_llm_response(
            body=response_bytes,
            model_id=model,
            prompt_hash=prompt_h,
            params_hash=params_h,
            fetch_time=query_time,
        )

        ctx.charge_data_read(1)
        self._llm_call_audit_entries.append(
            _LLMCallAuditEntry(
                pass_name=pass_name,
                model_version=model,
                prompt_hash=prompt_h,
                params_hash=params_h,
                response_hash=bytes_hash,
                cache_hit=False,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                llm_cost=charged_cost,
            )
        )

        return response.text

    def _parse_candidate_array(self, response_text: str) -> list[dict[str, Any]]:
        """Parse LLM response as a JSON array of candidates."""
        # Try to extract JSON from the response
        try:
            # Simple approach: look for a JSON array
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                json_str = response_text[start:end]
                candidates = json.loads(json_str)
                if isinstance(candidates, list):
                    return candidates
        except (json.JSONDecodeError, ValueError):
            pass

        logger.warning(f"Could not parse candidates from response: {response_text[:200]}")
        return []

    def _rejected_entry(
        self,
        candidate: Any,
        *,
        reason: str,
        draft_score: float = 0.0,
    ) -> _CandidateAuditEntry:
        grounding = candidate.get("grounding", {}) if isinstance(candidate, dict) else {}
        return _CandidateAuditEntry(
            rule_id="invalid",
            rule_object=candidate,
            grounding=grounding if isinstance(grounding, dict) else {},
            free_text_rationale="",
            rule_hash=_rule_hash(candidate),
            draft_score=draft_score,
            adjudicate_score=0.0,
            verdict="rejected",
            verdict_reason=reason,
        )


def _rule_hash(candidate: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
