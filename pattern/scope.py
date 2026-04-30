from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from audit import canonicalize


class ScopeValidationError(ValueError):
    """Raised when a scope body is not computable."""


class ScopeEvaluationError(RuntimeError):
    """Raised when a scope needs registry help that is unavailable."""


_PARTITION_ID_RE = re.compile(r"^partition_(0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class ScopeOp:
    kind: str
    op_version: str
    normalize: Callable[[Mapping[str, Any]], dict[str, Any]]
    fn: Callable[[dict[str, Any], datetime, Any, Any, str, dict[str, Any]], bool]

    def validate(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ScopeValidationError("scope kind must be a non-empty string")
        if not isinstance(self.op_version, str) or not self.op_version:
            raise ScopeValidationError("scope op_version must be a non-empty string")


@dataclass(frozen=True)
class Scope:
    kind: str
    args: dict[str, Any]
    op_version: str
    _fn: Callable[[dict[str, Any], datetime, Any, Any, str, dict[str, Any]], bool] = field(
        repr=False,
        compare=False,
    )

    def public_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "args": _canonical_copy(self.args)}

    def hash_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data["op_version"] = self.op_version
        return data

    def matches(self, *, spec_ref: str, t: datetime, access: Any, registry: Any) -> bool:
        return bool(self._fn(self.args, t, access, registry, spec_ref, self.public_dict()))


def load_scope(
    body: Mapping[str, Any] | Scope,
    *,
    op_registry: Mapping[str, ScopeOp] | None = None,
) -> Scope:
    if isinstance(body, Scope):
        return body
    if not isinstance(body, Mapping):
        raise ScopeValidationError("scope must be a mapping")
    if set(body.keys()) != {"kind", "args"}:
        raise ScopeValidationError("scope must contain exactly kind and args")
    kind = body["kind"]
    if not isinstance(kind, str) or not kind:
        raise ScopeValidationError("scope kind must be a non-empty string")
    registry = dict(op_registry or DEFAULT_SCOPE_OPS)
    op = registry.get(kind)
    if op is None:
        raise ScopeValidationError(f"unknown scope kind {kind!r}")
    op.validate()
    args = body["args"]
    if not isinstance(args, Mapping):
        raise ScopeValidationError("scope args must be a mapping")
    normalized = op.normalize(args)
    return Scope(kind=kind, args=normalized, op_version=op.op_version, _fn=op.fn)


def _canonical_copy(value: Any) -> Any:
    return json.loads(canonicalize(value).decode("utf-8"))


def _parse_time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
    else:
        raise ScopeValidationError(f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise ScopeValidationError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _normalize_all(args: Mapping[str, Any]) -> dict[str, Any]:
    if args:
        raise ScopeValidationError("all scope takes no args")
    return {}


def _normalize_time_range(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"t0", "t1"}:
        raise ScopeValidationError("time_range args must be t0 and t1")
    start = _parse_time(args["t0"], "time_range t0")
    end = _parse_time(args["t1"], "time_range t1")
    if end < start:
        raise ScopeValidationError("time_range t1 must be >= t0")
    return {"t0": start.isoformat(), "t1": end.isoformat()}


def _normalize_entity_set(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"entities"}:
        raise ScopeValidationError("entity_set args must be entities")
    values = args["entities"]
    if not isinstance(values, list) or not values:
        raise ScopeValidationError("entity_set entities must be a non-empty list")
    entities = tuple(sorted(str(item) for item in values))
    if any(not item for item in entities):
        raise ScopeValidationError("entity_set entities must be non-empty strings")
    if len(set(entities)) != len(entities):
        raise ScopeValidationError("entity_set entities must be unique")
    return {"entities": list(entities)}


def _normalize_partition(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"partition_id"}:
        raise ScopeValidationError("partition args must be partition_id")
    value = args["partition_id"]
    if not isinstance(value, str) or _PARTITION_ID_RE.match(value) is None:
        raise ScopeValidationError("partition_id must be partition_0, partition_1, ...")
    return {"partition_id": value}


def _all(args: dict[str, Any], t: datetime, access: Any, registry: Any, spec_ref: str, public: dict[str, Any]) -> bool:
    del args, t, access, registry, spec_ref, public
    return True


def _time_range(args: dict[str, Any], t: datetime, access: Any, registry: Any, spec_ref: str, public: dict[str, Any]) -> bool:
    del access, registry, spec_ref, public
    when = t.astimezone(timezone.utc)
    start = datetime.fromisoformat(args["t0"])
    end = datetime.fromisoformat(args["t1"])
    return start <= when <= end


def _delegated(args: dict[str, Any], t: datetime, access: Any, registry: Any, spec_ref: str, public: dict[str, Any]) -> bool:
    del args
    method = getattr(registry, "scope_contains", None)
    if not callable(method):
        raise ScopeEvaluationError("registry must expose scope_contains for this scope")
    try:
        return bool(method(spec_ref=spec_ref, t=t, access=access, scope=public))
    except TypeError:
        return bool(method(spec_ref, t, access, public))


DEFAULT_SCOPE_OPS: dict[str, ScopeOp] = {
    "all": ScopeOp(
        kind="all",
        op_version="1",
        normalize=_normalize_all,
        fn=_all,
    ),
    "time_range": ScopeOp(
        kind="time_range",
        op_version="1",
        normalize=_normalize_time_range,
        fn=_time_range,
    ),
    "entity_set": ScopeOp(
        kind="entity_set",
        op_version="1",
        normalize=_normalize_entity_set,
        fn=_delegated,
    ),
    "partition": ScopeOp(
        kind="partition",
        op_version="1",
        normalize=_normalize_partition,
        fn=_delegated,
    ),
}
