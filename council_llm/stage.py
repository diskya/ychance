from __future__ import annotations

import hashlib
from typing import Any

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext, StageResult
from pipeline.cost import CostUsage
from represent.llm_client import LLMClient, LLMResponse, params_hash, prompt_hash

from .parsing import parse_full_vote, parse_screening_vote
from .prompts import build_full_prompt, build_screening_prompt
from .types import (
    APPROVE,
    NEED_FULL_REVIEW,
    REJECT,
    CouncilInput,
    CouncilLLMTrace,
    CouncilMember,
    CouncilVote,
    cache_key_hash,
    raw_slice_hash,
    rule_content_hash,
    text_hash,
    to_jsonable,
    validation_report_hash,
)


class CouncilVoterStage(Stage):
    name = "council_llm_voter"
    version = "1"
    audit_stage = "Council"
    cost_ceiling = CostCeiling(compute_usd=0.05, llm_usd=25.0, data_reads=0)
    InputType = CouncilInput
    OutputType = CouncilVote

    def __init__(
        self,
        *,
        member: CouncilMember,
        llm_client: LLMClient,
        artifacts,
        audit,
        access=None,
        writer=None,
    ) -> None:
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._member = member
        self._llm_client = llm_client

    @property
    def member(self) -> CouncilMember:
        return self._member

    def vote(
        self,
        rule: Any,
        validate_report: Any,
        raw_slice: Any,
        *,
        cycle_id: str,
    ) -> tuple[str, str, tuple[str, ...]]:
        result = self.run(
            CouncilInput(
                cycle_id=cycle_id,
                rule=rule,
                validate_report=validate_report,
                raw_slice=raw_slice,
            )
        )
        return result.outputs.as_tuple()

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        if not isinstance(inputs, CouncilInput):
            return super().fingerprint(inputs)
        inputs_hash = self._cache_key_hash(inputs)
        fp = hashlib.sha256(
            canonicalize(
                {
                    "name": self.name,
                    "version": self.version,
                    "cache_key_hash": inputs_hash,
                }
            )
        ).hexdigest()
        return inputs_hash, fp

    def run(self, inputs: Any, *, envelope: dict | None = None) -> StageResult:
        if not isinstance(inputs, CouncilInput):
            raise TypeError(
                f"{self.name}: inputs must be CouncilInput, got {type(inputs).__name__}"
            )

        env = {
            "cycle_id": inputs.cycle_id,
            "rule_id": inputs.rule.rule_id,
        }
        env.update(
            {
                key: value
                for key, value in (envelope or {}).items()
                if key in {"cycle_id", "rule_id", "m2a_id"}
            }
        )
        inputs_hash, fp = self.fingerprint(inputs)

        cached = self._artifacts.lookup_fingerprint(fp)
        if cached is not None:
            try:
                outputs = self._deserialize_output(self._artifacts.get(cached))
            except KeyError:
                pass
            else:
                usage = CostUsage()
                self._append_vote_audit(
                    inputs=inputs,
                    outputs=outputs,
                    envelope=env,
                    inputs_hash=inputs_hash,
                    output_hash=cached,
                    usage=usage,
                    cache_hit=True,
                )
                return StageResult(outputs, cached, True, usage)

        ctx = StageContext(
            ceiling=self.cost_ceiling,
            access=self._access,
            writer=self._writer,
            envelope=env,
        )
        outputs = self.compute(inputs, ctx)
        if not isinstance(outputs, CouncilVote):
            raise TypeError(
                f"{self.name}: compute returned {type(outputs).__name__}, expected CouncilVote"
            )
        inv_ret = self.invariant(inputs, outputs)
        if inv_ret is False:
            raise InvariantViolation(f"{self.name}: invariant returned False")

        out_bytes = self._serialize_output(outputs)
        output_hash = hashlib.sha256(out_bytes).hexdigest()
        stored_hash = self._artifacts.put(out_bytes)
        if stored_hash != output_hash:
            raise RuntimeError("artifact store returned an unexpected output hash")
        self._artifacts.record_fingerprint(
            fp,
            stage_name=self.name,
            stage_version=self.version,
            inputs_hash=inputs_hash,
            output_hash=stored_hash,
        )
        self._append_vote_audit(
            inputs=inputs,
            outputs=outputs,
            envelope=env,
            inputs_hash=inputs_hash,
            output_hash=stored_hash,
            usage=ctx.usage,
            cache_hit=False,
        )
        return StageResult(outputs, stored_hash, False, ctx.usage)

    def compute(self, inputs: CouncilInput, ctx: StageContext) -> CouncilVote:
        member = self._member
        rule_hash = rule_content_hash(inputs.rule)
        report_hash = validation_report_hash(inputs.validate_report)
        slice_hash = raw_slice_hash(inputs.raw_slice)
        key_hash = cache_key_hash(
            rule_hash=rule_hash,
            validate_report_hash=report_hash,
            member_version=member.member_version,
        )

        screening_prompt = build_screening_prompt(
            rule=inputs.rule,
            validate_report=inputs.validate_report,
            raw_slice=inputs.raw_slice,
        )
        screening_trace, screening_text = self._complete(
            phase="screening",
            prompt=screening_prompt,
            params=dict(member.screening_params),
            ctx=ctx,
        )
        screening_decision = parse_screening_vote(screening_text)

        full_trace: CouncilLLMTrace | None = None
        rationale = ""
        citations: tuple[str, ...] = ()
        if screening_decision == NEED_FULL_REVIEW:
            full_prompt = build_full_prompt(
                rule=inputs.rule,
                validate_report=inputs.validate_report,
                raw_slice=inputs.raw_slice,
            )
            full_trace, full_text = self._complete(
                phase="full",
                prompt=full_prompt,
                params=dict(member.full_params),
                ctx=ctx,
            )
            parsed = parse_full_vote(full_text)
            vote = parsed.vote
            rationale = parsed.rationale
            citations = parsed.citations
            query_mode = "full_review"
        else:
            vote = screening_decision
            query_mode = "screening_only"

        prompt_hashes = {
            "screening": screening_trace.prompt_hash,
            "full": None if full_trace is None else full_trace.prompt_hash,
        }
        response_hashes = {
            "screening": screening_trace.response_hash,
            "full": None if full_trace is None else full_trace.response_hash,
        }
        traces = (screening_trace,) if full_trace is None else (screening_trace, full_trace)
        return CouncilVote(
            rule_id=inputs.rule.rule_id,
            member_id=member.member_id,
            member_version=member.member_version,
            vendor_family=member.vendor_family,
            vote=vote,
            rationale=rationale,
            citations=citations,
            rationale_hash=text_hash(rationale),
            screening_decision=screening_decision,
            query_mode=query_mode,
            rule_hash=rule_hash,
            validate_report_hash=report_hash,
            raw_slice_hash=slice_hash,
            cache_key_hash=key_hash,
            prompt_hashes=prompt_hashes,
            response_hashes=response_hashes,
            llm_traces=traces,
        )

    def invariant(self, inputs: CouncilInput, outputs: CouncilVote) -> None:
        if outputs.rule_id != inputs.rule.rule_id:
            raise InvariantViolation("vote rule_id does not match input rule")
        if outputs.member_id != self._member.member_id:
            raise InvariantViolation("vote member_id does not match voter member")
        if outputs.member_version != self._member.member_version:
            raise InvariantViolation("vote member_version does not match voter member")
        if outputs.vote not in {APPROVE, REJECT}:
            raise InvariantViolation("final vote must be approve or reject")
        if outputs.screening_decision not in {APPROVE, REJECT, NEED_FULL_REVIEW}:
            raise InvariantViolation("invalid screening decision")
        if outputs.query_mode == "screening_only" and outputs.screening_decision == NEED_FULL_REVIEW:
            raise InvariantViolation("need full review cannot finish in screening_only mode")
        if outputs.query_mode == "full_review" and outputs.screening_decision != NEED_FULL_REVIEW:
            raise InvariantViolation("full review requires need full review screening decision")
        if outputs.rationale_hash != text_hash(outputs.rationale):
            raise InvariantViolation("rationale_hash does not match rationale")
        expected_key = self._cache_key_hash(inputs)
        if outputs.cache_key_hash != expected_key:
            raise InvariantViolation("cache key hash does not match content key")

    def audit_extra_payload(
        self,
        inputs: CouncilInput,
        outputs: CouncilVote,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return self._vote_payload(
            inputs=inputs,
            outputs=outputs,
            usage=ctx.usage,
            cache_hit=False,
        )

    def _complete(
        self,
        *,
        phase: str,
        prompt: str,
        params: dict[str, Any],
        ctx: StageContext,
    ) -> tuple[CouncilLLMTrace, str]:
        member = self._member
        response = self._llm_client.complete(
            model=member.model,
            prompt=prompt,
            params=params,
        )
        trace = self._trace_response(
            phase=phase,
            prompt=prompt,
            params=params,
            response=response,
        )
        ctx.charge_llm(trace.llm_cost)
        return trace, response.text

    def _trace_response(
        self,
        *,
        phase: str,
        prompt: str,
        params: dict[str, Any],
        response: LLMResponse,
    ) -> CouncilLLMTrace:
        member = self._member
        response_hash = hashlib.sha256(
            canonicalize(
                {
                    "text": response.text,
                    "input_tokens": int(response.input_tokens),
                    "output_tokens": int(response.output_tokens),
                    "raw_json": to_jsonable(response.raw_json),
                }
            )
        ).hexdigest()
        llm_cost = (
            (int(response.input_tokens) / 1000.0) * member.input_cost_per_1k_usd
            + (int(response.output_tokens) / 1000.0) * member.output_cost_per_1k_usd
        )
        return CouncilLLMTrace(
            phase=phase,
            model=member.model,
            prompt_hash=prompt_hash(prompt),
            params_hash=params_hash(model=member.model, params=params),
            response_hash=response_hash,
            input_tokens=int(response.input_tokens),
            output_tokens=int(response.output_tokens),
            llm_cost=llm_cost,
        )

    def _cache_key_hash(self, inputs: CouncilInput) -> str:
        return cache_key_hash(
            rule_hash=rule_content_hash(inputs.rule),
            validate_report_hash=validation_report_hash(inputs.validate_report),
            member_version=self._member.member_version,
        )

    def _append_vote_audit(
        self,
        *,
        inputs: CouncilInput,
        outputs: CouncilVote,
        envelope: dict[str, Any],
        inputs_hash: str,
        output_hash: str,
        usage: CostUsage,
        cache_hit: bool,
    ) -> None:
        record = {
            "category": "Council",
            "stage": "Council",
            "envelope": envelope,
            "stage_name": self.name,
            "stage_version": self.version,
            "inputs_hash": inputs_hash,
            "output_hash": output_hash,
            "compute_cost": usage.compute_usd,
            "llm_cost": usage.llm_usd,
            "data_reads": usage.data_reads,
        }
        record.update(
            self._vote_payload(
                inputs=inputs,
                outputs=outputs,
                usage=usage,
                cache_hit=cache_hit,
            )
        )
        self._audit.validate_record(record)
        self._audit.append(record)

    def _vote_payload(
        self,
        *,
        inputs: CouncilInput,
        outputs: CouncilVote,
        usage: CostUsage,
        cache_hit: bool,
    ) -> dict[str, Any]:
        return {
            "rule_id": outputs.rule_id,
            "member_id": outputs.member_id,
            "member_version": outputs.member_version,
            "vendor_family": outputs.vendor_family,
            "cache_status": "hit" if cache_hit else "miss",
            "cache_hit": cache_hit,
            "cache_key_hash": outputs.cache_key_hash,
            "rule_hash": outputs.rule_hash,
            "validate_report_hash": outputs.validate_report_hash,
            "raw_slice_hash": outputs.raw_slice_hash,
            "vote": outputs.vote,
            "rationale": outputs.rationale,
            "rationale_hash": outputs.rationale_hash,
            "citations": list(outputs.citations),
            "key_evidence_citations": list(outputs.citations),
            "query_mode": outputs.query_mode,
            "screening_decision": outputs.screening_decision,
            "prompt_hashes": dict(outputs.prompt_hashes),
            "response_hashes": dict(outputs.response_hashes),
            "llm_traces": [trace.as_dict() for trace in outputs.llm_traces],
            "cost_usage": {
                "compute_usd": usage.compute_usd,
                "llm_usd": usage.llm_usd,
                "data_reads": usage.data_reads,
            },
        }
