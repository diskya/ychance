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
  DAG-level markers - this is the 1.4 exit criterion.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from audit import AuditLog, canonicalize

from .stage import Stage, StageResult


InputBinding = Callable[[dict[str, Any], dict[str, Any]], Any]
# (initial_inputs, stage_outputs_so_far) -> input-dataclass-instance


@dataclass
class _Node:
    stage: Stage
    binding: InputBinding


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
        self._nodes.append(_Node(stage=stage, binding=inputs))
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
            {"name": n.stage.name, "version": n.stage.version} for n in self._nodes
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
                "category": "DAGRun",
                "stage": "pipeline",
                "envelope": self._envelope,
                "event": "run_start",
                "run_id": run_id,
                "dag_signature": sig,
                "stage_order": [n.stage.name for n in self._nodes],
            }
        )

        results: dict[str, StageResult] = {}
        status = "success"
        error_info: Optional[dict] = None
        try:
            for node in self._nodes:
                stage_inputs = node.binding(
                    initial_inputs,
                    {k: v.outputs for k, v in results.items()},
                )
                try:
                    res = node.stage.run(stage_inputs, envelope=self._envelope)
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
            end_record: dict[str, Any] = {
                "category": "DAGRun",
                "stage": "pipeline",
                "envelope": self._envelope,
                "event": "run_end",
                "run_id": run_id,
                "dag_signature": sig,
                "status": status,
                "stages": [
                    {
                        "name": n.stage.name,
                        "cache_hit": results[n.stage.name].cache_hit,
                        "output_hash": results[n.stage.name].output_hash,
                    }
                    for n in self._nodes
                    if n.stage.name in results
                ],
            }
            if error_info is not None:
                end_record["error"] = error_info
            self._audit.append(end_record)

        return results
