"""Stage base class for the discovery-loop pipeline (plan 1.4, §6.1).

A Stage is a typed, versioned node with:

- typed input and output dataclasses (``InputType``/``OutputType``);
- a class-level version string;
- a per-invocation cost ceiling (compute, LLM, data-read);
- a ``compute`` method that produces outputs from inputs;
- an ``invariant`` method that asserts a measurable property of
  outputs relative to inputs.

``Stage.run`` is the single call site. It:

1. Hashes the inputs and combines the hash with ``(name, version)`` to
   form a fingerprint.
2. On fingerprint hit (prior run's artifact still present): returns the
   cached output **with no side effects** — no artifact write, no audit
   record. This is load-bearing for the 1.4 completion criterion
   ("re-running an unchanged DAG produces zero new audit records
   except re-run-start/end markers"). Only the DAG emits the markers.
3. On miss: runs ``compute`` under a :class:`StageContext` that enforces
   the cost ceiling, verifies the invariant, writes the output to the
   artifact store, records the fingerprint, and emits exactly one Stage
   audit record describing the call (not individual reads — those are
   emitted by :class:`access.AccessLayer`).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import types
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Union, get_args, get_origin, get_type_hints

from access import AccessLayer, RawStoreWriter
from audit import AuditLog, canonicalize

from .artifacts import ArtifactStore
from .cost import CostCeiling, CostCeilingExceeded, CostUsage


class InvariantViolation(RuntimeError):
    """Raised when a Stage's output fails its declared invariant."""


_ARCHITECTURE_STAGES = frozenset(
    {
        "Ingest",
        "Represent",
        "Discover",
        "Originality",
        "EmpiricalTest",
        "Council",
        "Archive",
        "Audit",
        "Operator",
        "Review",
    }
)


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts. Leaves primitives alone."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def _content_hash(obj: Any) -> str:
    return hashlib.sha256(canonicalize(_to_jsonable(obj))).hexdigest()


def _from_jsonable(type_hint: Any, obj: Any) -> Any:
    if type_hint in (Any, object) or type_hint is None:
        return obj

    origin = get_origin(type_hint)
    if dataclasses.is_dataclass(type_hint) and isinstance(obj, dict):
        hints = get_type_hints(type_hint)
        kwargs = {
            field.name: _from_jsonable(hints.get(field.name, field.type), obj[field.name])
            for field in dataclasses.fields(type_hint)
            if field.name in obj
        }
        return type_hint(**kwargs)

    if origin is list and isinstance(obj, list):
        (item_type,) = get_args(type_hint) or (Any,)
        return [_from_jsonable(item_type, item) for item in obj]

    if origin is tuple and isinstance(obj, list):
        args = get_args(type_hint)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_from_jsonable(args[0], item) for item in obj)
        return tuple(_from_jsonable(arg, item) for arg, item in zip(args, obj))

    if origin is dict and isinstance(obj, dict):
        key_type, value_type = get_args(type_hint) or (Any, Any)
        return {
            _from_jsonable(key_type, key): _from_jsonable(value_type, value)
            for key, value in obj.items()
        }

    if origin in (Union, types.UnionType):
        options = [arg for arg in get_args(type_hint) if arg is not type(None)]
        if obj is None:
            return None
        for option in options:
            try:
                return _from_jsonable(option, obj)
            except (TypeError, ValueError):
                continue
        return obj

    return obj


@dataclass
class StageContext:
    """Per-invocation handle threaded into :meth:`Stage.compute`.

    Tracks cost against the stage's ceiling and, when the stage needs raw
    bytes, exposes the :class:`AccessLayer` (never a bare ``RawStore`` —
    methodology §6.2 requires every read to pass through the access
    layer, where admissibility, rate limiting, and per-read audit live).
    """

    ceiling: CostCeiling
    access: Optional[AccessLayer] = None
    writer: Optional[RawStoreWriter] = None
    envelope: dict[str, Any] = field(default_factory=dict)
    usage: CostUsage = field(default_factory=CostUsage)

    def charge_compute(self, usd: float) -> None:
        self.usage.compute_usd += usd
        if self.usage.compute_usd > self.ceiling.compute_usd:
            raise CostCeilingExceeded(
                f"compute ceiling exceeded: "
                f"{self.usage.compute_usd} > {self.ceiling.compute_usd}"
            )

    def charge_llm(self, usd: float) -> None:
        self.usage.llm_usd += usd
        if self.usage.llm_usd > self.ceiling.llm_usd:
            raise CostCeilingExceeded(
                f"llm ceiling exceeded: "
                f"{self.usage.llm_usd} > {self.ceiling.llm_usd}"
            )

    def charge_data_read(self, n: int = 1) -> None:
        self.usage.data_reads += n
        if self.usage.data_reads > self.ceiling.data_reads:
            raise CostCeilingExceeded(
                f"data-read ceiling exceeded: "
                f"{self.usage.data_reads} > {self.ceiling.data_reads}"
            )


@dataclass
class StageResult:
    outputs: Any
    output_hash: str
    cache_hit: bool
    cost_used: CostUsage


class Stage:
    """Base class for a pipeline stage.

    Subclasses MUST set class attrs and override two methods:
        name, version, cost_ceiling, InputType, OutputType
        compute(self, inputs, ctx) -> OutputType instance
        invariant(self, inputs, outputs) -> None (raise InvariantViolation
            or return False on failure)

    Subclasses MAY override:
        audit_stage       — one of the architecture stages from §6.1.
        audit_category    — defaults to ``audit_stage``; override when a stage
                            needs a narrower §6.9 category name.
        audit_extra_payload
                          — returns category-specific audit fields to merge
                            into the base Stage audit record.
        _serialize_output / _deserialize_output
                          — for output types that canonical JSON does not
                            round-trip cleanly (bytes, custom classes, …).
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = ""
    cost_ceiling: ClassVar[CostCeiling] = CostCeiling()
    InputType: ClassVar[type] = type(None)
    OutputType: ClassVar[type] = type(None)
    audit_stage: ClassVar[str] = ""
    audit_category: ClassVar[Optional[str]] = None

    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        audit: AuditLog,
        access: Optional[AccessLayer] = None,
        writer: Optional[RawStoreWriter] = None,
    ) -> None:
        if not isinstance(artifacts, ArtifactStore):
            raise TypeError("artifacts must be an ArtifactStore")
        if not isinstance(audit, AuditLog):
            raise TypeError("audit must be an AuditLog")
        if access is not None and not isinstance(access, AccessLayer):
            raise TypeError("access must be an AccessLayer or None")
        if writer is not None and not isinstance(writer, RawStoreWriter):
            raise TypeError("writer must be a RawStoreWriter or None")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(
                f"{type(self).__name__}: class attr 'name' must be a non-empty str"
            )
        if not isinstance(self.version, str) or not self.version:
            raise ValueError(
                f"{type(self).__name__}: class attr 'version' must be a non-empty str"
            )
        if not isinstance(self.cost_ceiling, CostCeiling):
            raise TypeError(
                f"{type(self).__name__}: 'cost_ceiling' must be a CostCeiling"
            )
        if self.audit_stage not in _ARCHITECTURE_STAGES:
            raise ValueError(
                f"{type(self).__name__}: 'audit_stage' must be one of "
                f"{sorted(_ARCHITECTURE_STAGES)}"
            )
        if self.audit_category is not None and (
            not isinstance(self.audit_category, str) or not self.audit_category
        ):
            raise ValueError(
                f"{type(self).__name__}: 'audit_category' must be a non-empty str or None"
            )
        self._artifacts = artifacts
        self._audit = audit
        self._access = access
        self._writer = writer

    # --- overridable hooks ------------------------------------------------

    def compute(self, inputs: Any, ctx: StageContext) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__} must override compute(inputs, ctx)"
        )

    def invariant(self, inputs: Any, outputs: Any) -> None:
        """Assert a measurable property of ``outputs`` given ``inputs``.

        Raise :class:`InvariantViolation` or return falsy on failure.
        :class:`PipelineDAG` refuses to add a stage that has not overridden
        this method — methodology §6.1 requires every stage to declare an
        invariant.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must override invariant(inputs, outputs)"
        )

    def _serialize_output(self, outputs: Any) -> bytes:
        return canonicalize(_to_jsonable(outputs))

    def _deserialize_output(self, data: bytes) -> Any:
        obj = json.loads(data.decode("utf-8"))
        if dataclasses.is_dataclass(self.OutputType):
            return _from_jsonable(self.OutputType, obj)
        return obj

    def audit_extra_payload(
        self,
        inputs: Any,
        outputs: Any,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        """Return category-specific fields to merge into the audit payload."""
        return {}

    # --- main call path ---------------------------------------------------

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        """Return ``(inputs_hash, fingerprint)``. Pure function of inputs.

        The fingerprint is the cache key: ``sha256({name, version, inputs_hash})``.
        Exposed for the DAG and for tests that want to verify caching behavior.
        """
        inputs_hash = _content_hash(inputs)
        fp = hashlib.sha256(
            canonicalize(
                {
                    "name": self.name,
                    "version": self.version,
                    "inputs_hash": inputs_hash,
                }
            )
        ).hexdigest()
        return inputs_hash, fp

    def run(self, inputs: Any, *, envelope: Optional[dict] = None) -> StageResult:
        if self.InputType is not type(None) and not isinstance(inputs, self.InputType):
            raise TypeError(
                f"{self.name}: inputs must be {self.InputType.__name__}, "
                f"got {type(inputs).__name__}"
            )
        env = dict(envelope or {})

        inputs_hash, fp = self.fingerprint(inputs)

        cached = self._artifacts.lookup_fingerprint(fp)
        if cached is not None:
            try:
                outputs = self._deserialize_output(self._artifacts.get(cached))
            except KeyError:
                pass
            else:
                # Cache hit: no audit record. The 1.4 completion criterion requires
                # that a re-run with unchanged inputs produces zero new audit
                # records except the DAG-level start/end markers.
                return StageResult(outputs, cached, True, CostUsage())

        ctx = StageContext(
            ceiling=self.cost_ceiling,
            access=self._access,
            writer=self._writer,
            envelope=env,
        )
        outputs = self.compute(inputs, ctx)
        if self.OutputType is not type(None) and not isinstance(outputs, self.OutputType):
            raise TypeError(
                f"{self.name}: compute returned {type(outputs).__name__}, "
                f"expected {self.OutputType.__name__}"
            )

        inv_ret = self.invariant(inputs, outputs)
        if inv_ret is False:
            raise InvariantViolation(
                f"{self.name}: invariant returned False"
            )

        out_bytes = self._serialize_output(outputs)
        output_hash = hashlib.sha256(out_bytes).hexdigest()
        audit_record = {
            "category": self.audit_category or self.audit_stage,
            "stage": self.audit_stage,
            "envelope": env,
            "stage_name": self.name,
            "stage_version": self.version,
            "inputs_hash": inputs_hash,
            "output_hash": output_hash,
            "compute_cost": ctx.usage.compute_usd,
            "llm_cost": ctx.usage.llm_usd,
            "data_reads": ctx.usage.data_reads,
        }
        extra_payload = self.audit_extra_payload(
            inputs,
            outputs,
            ctx,
            inputs_hash=inputs_hash,
            output_hash=output_hash,
        )
        if not isinstance(extra_payload, dict):
            raise TypeError("audit_extra_payload must return a dict")
        audit_record.update(extra_payload)
        self._audit.validate_record(audit_record)

        stored_hash = self._artifacts.put(out_bytes)
        self._artifacts.record_fingerprint(
            fp,
            stage_name=self.name,
            stage_version=self.version,
            inputs_hash=inputs_hash,
            output_hash=stored_hash,
        )

        self._audit.append(audit_record)
        return StageResult(outputs, stored_hash, False, ctx.usage)
