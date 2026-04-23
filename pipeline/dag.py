"""Topological DAG orchestration for Stages (plan 1.4, §6.1).

A :class:`PipelineDAG` is an ordered list of stage invocations with
input bindings that resolve either to run-level "initial" inputs or to
a prior stage's output. The DAG:

- refuses to add a stage that has not overridden ``compute`` or
  ``invariant`` (methodology §6.1 requires every stage to declare an
  invariant; "missing invariant" is therefore a construction-time
  error, not a runtime one);
- emits exactly one ``run_start`` and one ``run_end`` audit record per
  call to :meth:`run`, regardless of per-stage cache hits or failure;
- delegates per-stage caching to :meth:`Stage.run`, so a re-run whose
  inputs haven't changed produces zero new records apart from the
  DAG-level markers — this is the 1.4 exit criterion.
"""

from __future__ import annotations

import dataclasses
import inspect
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from audit import AuditLog, canonicalize

from .stage import Stage, StageResult


InputBinding = Callable[[dict[str, Any], dict[str, Any]], Any]
# (initial_inputs, stage_outputs_so_far) -> input-dataclass-instance
EnvelopeBinding = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _signature_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _signature_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _signature_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_signature_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {
        "type": type(value).__name__,
        "module": type(value).__module__,
        "qualname": getattr(type(value), "__qualname__", type(value).__name__),
    }


def _callable_signature(fn: Callable[..., Any]) -> str:
    explicit = getattr(fn, "__pipeline_signature__", None)
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit:
            raise ValueError("__pipeline_signature__ must be a non-empty string")
        return explicit

    code = getattr(fn, "__code__", None)
    if code is None:
        # functools.partial, bound methods of C builtins, and other synthetic
        # callables carry no bytecode. Falling back to qualname+source would
        # collide between distinct partials (e.g. two partials over the same
        # underlying function with different bound args share qualname and
        # have no source), and the DAG signature is load-bearing for §6.1
        # reproducibility. Force the caller to commit to an explicit id.
        raise TypeError(
            f"callable {fn!r} has no __code__; set a stable string attribute "
            "'__pipeline_signature__' on it so DAG signatures do not collide."
        )

    payload: dict[str, Any] = {
        "module": getattr(fn, "__module__", None),
        "qualname": getattr(fn, "__qualname__", type(fn).__qualname__),
        "code": {
            "bytecode": code.co_code.hex(),
            "consts": [_signature_value(value) for value in code.co_consts],
            "names": list(code.co_names),
            "varnames": list(code.co_varnames),
        },
    }
    closure = getattr(fn, "__closure__", None)
    if closure:
        payload["closure"] = [
            _signature_value(cell.cell_contents) for cell in closure
        ]
    try:
        payload["source"] = inspect.getsource(fn).strip()
    except (OSError, TypeError):
        pass
    return hashlib.sha256(canonicalize(payload)).hexdigest()


@dataclass
class _Node:
    stage: Stage
    binding: InputBinding
    binding_signature: str
    envelope_binding: Optional[EnvelopeBinding]
    envelope_signature: Optional[str]


class PipelineDAG:
    """Ordered collection of Stage nodes with run-level audit markers."""

    def __init__(
        self,
        *,
        audit: AuditLog,
        envelope: Optional[dict] = None,
    ) -> None:
        if not isinstance(audit, AuditLog):
            raise TypeError("audit must be an AuditLog")
        self._audit = audit
        self._envelope = dict(envelope or {})
        self._nodes: list[_Node] = []
        self._names: set[str] = set()

    # --- construction -----------------------------------------------------

    def add(
        self,
        stage: Stage,
        *,
        inputs: InputBinding,
        envelope: Optional[EnvelopeBinding] = None,
    ) -> "PipelineDAG":
        if not isinstance(stage, Stage):
            raise TypeError("stage must be a Stage instance")
        if type(stage).compute is Stage.compute:
            raise ValueError(
                f"stage {stage.name!r}: must override Stage.compute"
            )
        if type(stage).invariant is Stage.invariant:
            raise ValueError(
                f"stage {stage.name!r}: must override Stage.invariant "
                "(methodology §6.1 requires every stage to declare an invariant)"
            )
        if stage.name in self._names:
            raise ValueError(f"duplicate stage name in DAG: {stage.name!r}")
        if not callable(inputs):
            raise TypeError(
                "inputs binding must be callable (initial, results) -> Stage.InputType"
            )
        if envelope is not None and not callable(envelope):
            raise TypeError(
                "envelope binding must be callable (initial, results) -> dict"
            )
        self._nodes.append(
            _Node(
                stage=stage,
                binding=inputs,
                binding_signature=_callable_signature(inputs),
                envelope_binding=envelope,
                envelope_signature=(
                    _callable_signature(envelope) if envelope is not None else None
                ),
            )
        )
        self._names.add(stage.name)
        return self

    # --- shape ------------------------------------------------------------

    def signature(self) -> str:
        """Content hash of the DAG shape: ordered ``(name, version)`` pairs.

        Used in the run-start/run-end markers so an audit reader can tell
        whether two runs were against the same DAG definition without
        walking every stage record.
        """
        shape = [
            {
                "name": n.stage.name,
                "version": n.stage.version,
                "binding_signature": n.binding_signature,
                "envelope_signature": n.envelope_signature,
            }
            for n in self._nodes
        ]
        return hashlib.sha256(canonicalize(shape)).hexdigest()

    @property
    def envelope(self) -> dict:
        return dict(self._envelope)

    @property
    def stage_names(self) -> list[str]:
        return [n.stage.name for n in self._nodes]

    # --- execution --------------------------------------------------------

    def run(self, initial: Optional[dict] = None) -> dict[str, StageResult]:
        initial_inputs = dict(initial or {})
        run_id = uuid.uuid4().hex
        sig = self.signature()

        self._audit.append(
            {
                "category": "Audit",
                "stage": "Audit",
                "envelope": self._envelope,
                "event": "run_start",
                "record_type": "DAGRun",
                "run_id": run_id,
                "dag_signature": sig,
                "stage_order": [n.stage.name for n in self._nodes],
            }
        )

        results: dict[str, StageResult] = {}
        stage_envelopes: dict[str, dict[str, Any]] = {}
        status = "success"
        error_info: Optional[dict] = None
        try:
            for node in self._nodes:
                prior_outputs = {k: v.outputs for k, v in results.items()}
                stage_inputs = node.binding(
                    initial_inputs,
                    prior_outputs,
                )
                stage_envelope = dict(self._envelope)
                if node.envelope_binding is not None:
                    extra_env = node.envelope_binding(initial_inputs, prior_outputs)
                    if not isinstance(extra_env, dict):
                        raise TypeError(
                            "envelope binding must return a dict"
                        )
                    stage_envelope.update(extra_env)
                stage_envelopes[node.stage.name] = stage_envelope
                try:
                    res = node.stage.run(stage_inputs, envelope=stage_envelope)
                except Exception as exc:
                    status = "error"
                    error_info = {
                        "failed_stage": node.stage.name,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                    raise
                results[node.stage.name] = res
        finally:
            failed_stage = (
                error_info["failed_stage"] if error_info is not None else None
            )
            end_record: dict[str, Any] = {
                "category": "Audit",
                "stage": "Audit",
                "envelope": self._envelope,
                "event": "run_end",
                "record_type": "DAGRun",
                "run_id": run_id,
                "dag_signature": sig,
                "status": status,
                "stages": [
                    {
                        "name": n.stage.name,
                        "status": (
                            "cache_hit"
                            if n.stage.name in results
                            and results[n.stage.name].cache_hit
                            else "success"
                            if n.stage.name in results
                            else "error"
                            if n.stage.name == failed_stage
                            else "not_started"
                        ),
                        "cache_hit": (
                            results[n.stage.name].cache_hit
                            if n.stage.name in results
                            else None
                        ),
                        "output_hash": (
                            results[n.stage.name].output_hash
                            if n.stage.name in results
                            else None
                        ),
                        "envelope": stage_envelopes.get(n.stage.name),
                    }
                    for n in self._nodes
                ],
            }
            if error_info is not None:
                end_record["error"] = error_info
            self._audit.append(end_record)

        return results
