from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from audit import canonicalize
from pattern import Pattern


class FingerprintPathError(ValueError):
    """Raised when a matcher requests an unknown fingerprint path."""


def digest_jsonable(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


@dataclass(frozen=True)
class PatternFingerprint:
    pattern_id: str
    fingerprint_hash: str
    spec_ref: str
    assertion: dict[str, Any]
    scope: dict[str, Any]
    observation_window: dict[str, str]
    replication_protocol: dict[str, Any]
    observation_fingerprint_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "fingerprint_hash": self.fingerprint_hash,
            "spec_ref": self.spec_ref,
            "assertion": _canonical_copy(self.assertion),
            "scope": _canonical_copy(self.scope),
            "observation_window": _canonical_copy(self.observation_window),
            "replication_protocol": _canonical_copy(self.replication_protocol),
            "observation_fingerprint_hash": self.observation_fingerprint_hash,
        }

    def projection(self, paths: Iterable[str]) -> dict[str, Any]:
        root = self.as_dict()
        projection: dict[str, Any] = {}
        for path in paths:
            projection[path] = _path_value(root, path)
        return projection


def build_pattern_fingerprint(
    pattern: Pattern,
    *,
    observation_fingerprint_hash: str | None = None,
) -> PatternFingerprint:
    if observation_fingerprint_hash is not None:
        _validate_hash(observation_fingerprint_hash, "observation_fingerprint_hash")
    base = {
        "pattern_id": pattern.pattern_id,
        "spec_ref": pattern.spec_ref,
        "assertion": pattern.assertion.hash_dict(),
        "scope": pattern.scope.hash_dict(),
        "observation_window": pattern.observation_window.as_dict(),
        "replication_protocol": pattern.replication_protocol.as_dict(),
        "observation_fingerprint_hash": observation_fingerprint_hash,
    }
    return PatternFingerprint(
        pattern_id=pattern.pattern_id,
        fingerprint_hash=digest_jsonable(base),
        spec_ref=pattern.spec_ref,
        assertion=_canonical_copy(base["assertion"]),
        scope=_canonical_copy(base["scope"]),
        observation_window=_canonical_copy(base["observation_window"]),
        replication_protocol=_canonical_copy(base["replication_protocol"]),
        observation_fingerprint_hash=observation_fingerprint_hash,
    )


def _canonical_copy(value: Any) -> Any:
    return json.loads(canonicalize(value).decode("utf-8"))


def _path_value(root: dict[str, Any], path: str) -> Any:
    if not isinstance(path, str) or not path:
        raise FingerprintPathError("fingerprint projection paths must be non-empty strings")
    current: Any = root
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise FingerprintPathError(f"unknown fingerprint path {path!r}")
        current = current[part]
    return _canonical_copy(current)


def _validate_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a 64-character hash")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be hexadecimal") from exc
