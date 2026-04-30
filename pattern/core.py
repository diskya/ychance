from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from audit import canonicalize

from .assertion import (
    DEFAULT_ASSERTION_OPS,
    Assertion,
    AssertionOp,
    AssertionValidationError,
    load_assertion,
)
from .scope import DEFAULT_SCOPE_OPS, Scope, ScopeOp, load_scope


class PatternValidationError(ValueError):
    """Raised when a Pattern body is invalid."""


class PatternEvaluationError(RuntimeError):
    """Raised when a Pattern cannot be evaluated through a registry."""


@dataclass(frozen=True)
class ObservationWindow:
    t0: str
    t1: str

    def __post_init__(self) -> None:
        start = _parse_time(self.t0, "observation_window.t0")
        end = _parse_time(self.t1, "observation_window.t1")
        if end < start:
            raise PatternValidationError("observation_window.t1 must be >= t0")
        object.__setattr__(self, "t0", start.isoformat())
        object.__setattr__(self, "t1", end.isoformat())

    def as_tuple(self) -> tuple[datetime, datetime]:
        return (
            datetime.fromisoformat(self.t0),
            datetime.fromisoformat(self.t1),
        )

    def as_dict(self) -> dict[str, str]:
        return {"t0": self.t0, "t1": self.t1}


@dataclass(frozen=True)
class ReplicationProtocol:
    kind: str
    args: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise PatternValidationError("replication_protocol.kind must be non-empty")
        if not isinstance(self.args, Mapping):
            raise PatternValidationError("replication_protocol.args must be a mapping")
        try:
            normalized = json.loads(canonicalize(dict(self.args)).decode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise PatternValidationError(
                "replication_protocol.args must be canonical-JSON-serializable"
            ) from exc
        object.__setattr__(self, "args", normalized)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "args": json.loads(canonicalize(self.args).decode("utf-8"))}


@dataclass(frozen=True)
class Pattern:
    spec_ref: str
    assertion: Assertion
    scope: Scope
    observation_window: ObservationWindow
    replication_protocol: ReplicationProtocol

    def __post_init__(self) -> None:
        _validate_spec_ref(self.spec_ref)
        if not isinstance(self.assertion, Assertion):
            raise PatternValidationError("assertion must be an Assertion")
        if not isinstance(self.scope, Scope):
            raise PatternValidationError("scope must be a Scope")
        if not isinstance(self.observation_window, ObservationWindow):
            raise PatternValidationError("observation_window must be an ObservationWindow")
        if not isinstance(self.replication_protocol, ReplicationProtocol):
            raise PatternValidationError("replication_protocol must be a ReplicationProtocol")

    @property
    def pattern_id(self) -> str:
        return hashlib.sha256(canonicalize(self.hash_body())).hexdigest()

    def body(self) -> dict[str, Any]:
        return {
            "spec_ref": self.spec_ref,
            "assertion": self.assertion.public_dict(),
            "scope": self.scope.public_dict(),
            "observation_window": self.observation_window.as_dict(),
            "replication_protocol": self.replication_protocol.as_dict(),
        }

    def hash_body(self) -> dict[str, Any]:
        data = self.body()
        data["assertion"] = self.assertion.hash_dict()
        data["scope"] = self.scope.hash_dict()
        return data

    def as_dict(self) -> dict[str, Any]:
        data = self.body()
        data["pattern_id"] = self.pattern_id
        return data

    def serialize(self) -> bytes:
        return serialize_pattern(self)

    def evaluate(self, t: datetime | str, access: Any, registry: Any) -> bool:
        when = _parse_time(t, "t")
        if not self.scope.matches(
            spec_ref=self.spec_ref,
            t=when,
            access=access,
            registry=registry,
        ):
            return False
        value = _resolve_value(registry, self.spec_ref, when, access)
        return self.assertion.evaluate(value)


def finalize_pattern(
    body: Mapping[str, Any],
    *,
    assertion_registry: Mapping[str, AssertionOp] | None = None,
    scope_registry: Mapping[str, ScopeOp] | None = None,
) -> dict[str, Any]:
    return _load_body(
        body,
        assertion_registry=assertion_registry,
        scope_registry=scope_registry,
    ).as_dict()


def load_pattern(
    raw: bytes | bytearray | memoryview | Mapping[str, Any] | Pattern,
    *,
    assertion_registry: Mapping[str, AssertionOp] | None = None,
    scope_registry: Mapping[str, ScopeOp] | None = None,
) -> Pattern:
    if isinstance(raw, Pattern):
        return raw
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = json.loads(bytes(raw).decode("utf-8"))
    elif isinstance(raw, Mapping):
        data = dict(raw)
    else:
        raise PatternValidationError("pattern must be bytes or a mapping")
    pattern_id = data.pop("pattern_id", None)
    if not isinstance(pattern_id, str) or len(pattern_id) != 64:
        raise PatternValidationError("pattern_id must be a 64-character string")
    pattern = _load_body(
        data,
        assertion_registry=assertion_registry,
        scope_registry=scope_registry,
    )
    if pattern.pattern_id != pattern_id:
        raise PatternValidationError("pattern_id does not match the canonical Pattern body")
    return pattern


def serialize_pattern(pattern: Pattern) -> bytes:
    if not isinstance(pattern, Pattern):
        raise TypeError("serialize_pattern requires a Pattern")
    return canonicalize(pattern.as_dict())


def _load_body(
    body: Mapping[str, Any],
    *,
    assertion_registry: Mapping[str, AssertionOp] | None,
    scope_registry: Mapping[str, ScopeOp] | None,
) -> Pattern:
    if not isinstance(body, Mapping):
        raise PatternValidationError("Pattern body must be a mapping")
    expected = {
        "spec_ref",
        "assertion",
        "scope",
        "observation_window",
        "replication_protocol",
    }
    if set(body.keys()) != expected:
        raise PatternValidationError("Pattern body has missing or extra keys")
    spec_ref = body["spec_ref"]
    if not isinstance(spec_ref, str):
        raise PatternValidationError("spec_ref must be a string")
    assertion = load_assertion(
        body["assertion"],
        op_registry=assertion_registry or DEFAULT_ASSERTION_OPS,
    )
    scope = load_scope(
        body["scope"],
        op_registry=scope_registry or DEFAULT_SCOPE_OPS,
    )
    window = _load_window(body["observation_window"])
    protocol = _load_protocol(body["replication_protocol"])
    return Pattern(
        spec_ref=spec_ref,
        assertion=assertion,
        scope=scope,
        observation_window=window,
        replication_protocol=protocol,
    )


def _load_window(body: Any) -> ObservationWindow:
    if not isinstance(body, Mapping) or set(body.keys()) != {"t0", "t1"}:
        raise PatternValidationError("observation_window must contain t0 and t1")
    return ObservationWindow(t0=body["t0"], t1=body["t1"])


def _load_protocol(body: Any) -> ReplicationProtocol:
    if not isinstance(body, Mapping) or set(body.keys()) != {"kind", "args"}:
        raise PatternValidationError("replication_protocol must contain kind and args")
    if not isinstance(body["args"], Mapping):
        raise PatternValidationError("replication_protocol args must be a mapping")
    return ReplicationProtocol(kind=body["kind"], args=dict(body["args"]))


def _validate_spec_ref(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise PatternValidationError("spec_ref must be a 64-character string")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PatternValidationError("spec_ref must be hexadecimal") from exc


def _parse_time(value: datetime | str, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
    else:
        raise PatternValidationError(f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise PatternValidationError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _resolve_value(registry: Any, spec_ref: str, t: datetime, access: Any) -> Any:
    for method_name in ("resolve", "evaluate", "at"):
        method = getattr(registry, method_name, None)
        if callable(method):
            try:
                return method(spec_ref=spec_ref, t=t, access=access)
            except TypeError:
                return method(spec_ref, t, access)
    raise PatternEvaluationError("registry must expose resolve(), evaluate(), or at()")


__all__ = [
    "DEFAULT_ASSERTION_OPS",
    "DEFAULT_SCOPE_OPS",
    "AssertionValidationError",
    "ObservationWindow",
    "Pattern",
    "PatternEvaluationError",
    "PatternValidationError",
    "ReplicationProtocol",
    "finalize_pattern",
    "load_pattern",
    "serialize_pattern",
]
