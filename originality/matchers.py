from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .fingerprint import PatternFingerprint, digest_jsonable


class AntiPatternListError(ValueError):
    """Raised when the anti-pattern list cannot accept a mutation."""


@dataclass(frozen=True)
class MatcherResult:
    matched: bool
    match_hash: str
    evidence: dict[str, Any]


@runtime_checkable
class FingerprintMatcher(Protocol):
    matcher_id: str
    matcher_version: str

    def match(self, fingerprint: PatternFingerprint) -> MatcherResult:
        ...

    def config(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class FingerprintReductionMatcher:
    """Match when a fingerprint reduces to a known canonical projection."""

    matcher_id: str
    paths: tuple[str, ...]
    projection_hash: str
    matcher_version: str = "1"

    def __post_init__(self) -> None:
        _validate_label(self.matcher_id, "matcher_id")
        _validate_label(self.matcher_version, "matcher_version")
        normalized = _normalize_paths(self.paths)
        if not normalized:
            raise AntiPatternListError("reduction matcher requires at least one path")
        _validate_hash(self.projection_hash, "projection_hash")
        object.__setattr__(self, "paths", normalized)

    @classmethod
    def from_fingerprint(
        cls,
        *,
        matcher_id: str,
        fingerprint: PatternFingerprint,
        paths: tuple[str, ...],
        matcher_version: str = "1",
    ) -> "FingerprintReductionMatcher":
        normalized = _normalize_paths(paths)
        projection_hash = digest_jsonable(fingerprint.projection(normalized))
        return cls(
            matcher_id=matcher_id,
            matcher_version=matcher_version,
            paths=normalized,
            projection_hash=projection_hash,
        )

    def match(self, fingerprint: PatternFingerprint) -> MatcherResult:
        projection = fingerprint.projection(self.paths)
        match_hash = digest_jsonable(projection)
        return MatcherResult(
            matched=match_hash == self.projection_hash,
            match_hash=match_hash,
            evidence={
                "matcher_id": self.matcher_id,
                "matcher_version": self.matcher_version,
                "paths": list(self.paths),
                "projection_hash": match_hash,
            },
        )

    def config(self) -> dict[str, Any]:
        return {
            "type": "fingerprint_reduction",
            "matcher_id": self.matcher_id,
            "matcher_version": self.matcher_version,
            "paths": list(self.paths),
            "projection_hash": self.projection_hash,
        }


@dataclass(frozen=True)
class AntiPatternEntry:
    anti_pattern_id: str
    matcher: FingerprintMatcher

    def __post_init__(self) -> None:
        _validate_label(self.anti_pattern_id, "anti_pattern_id")
        if not isinstance(self.matcher, FingerprintMatcher):
            raise AntiPatternListError("matcher must implement FingerprintMatcher")

    def as_dict(self) -> dict[str, Any]:
        return {
            "anti_pattern_id": self.anti_pattern_id,
            "matcher": self.matcher.config(),
        }


@dataclass(frozen=True)
class AntiPatternDecision:
    result: str
    matched_anti_pattern: str | None
    anti_pattern_list_version: str
    matcher_id: str | None
    match_hash: str | None
    evidence: dict[str, Any] | None


class AntiPatternList:
    """Bounded mutable list of subtractive, computable fingerprint matchers."""

    def __init__(
        self,
        entries: tuple[AntiPatternEntry, ...] = (),
        *,
        max_size: int = 32,
    ) -> None:
        if not isinstance(max_size, int) or max_size < 0:
            raise AntiPatternListError("max_size must be a non-negative integer")
        self._max_size = max_size
        self._entries: list[AntiPatternEntry] = []
        for entry in entries:
            self.append(entry)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def entries(self) -> tuple[AntiPatternEntry, ...]:
        return tuple(self._entries)

    @property
    def version(self) -> str:
        return digest_jsonable(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_size": self._max_size,
            "entries": [entry.as_dict() for entry in self._entries],
        }

    def append(self, entry: AntiPatternEntry) -> None:
        if not isinstance(entry, AntiPatternEntry):
            raise AntiPatternListError("entry must be an AntiPatternEntry")
        if len(self._entries) >= self._max_size:
            raise AntiPatternListError("anti-pattern list is full")
        if any(existing.anti_pattern_id == entry.anti_pattern_id for existing in self._entries):
            raise AntiPatternListError(f"duplicate anti_pattern_id {entry.anti_pattern_id!r}")
        self._entries.append(entry)

    def remove(self, anti_pattern_id: str) -> None:
        for index, entry in enumerate(self._entries):
            if entry.anti_pattern_id == anti_pattern_id:
                del self._entries[index]
                return
        raise AntiPatternListError(f"unknown anti_pattern_id {anti_pattern_id!r}")

    def clear(self) -> None:
        self._entries.clear()

    def decide(self, fingerprint: PatternFingerprint) -> AntiPatternDecision:
        for entry in self._entries:
            result = entry.matcher.match(fingerprint)
            if result.matched:
                return AntiPatternDecision(
                    result="reject",
                    matched_anti_pattern=entry.anti_pattern_id,
                    anti_pattern_list_version=self.version,
                    matcher_id=entry.matcher.matcher_id,
                    match_hash=result.match_hash,
                    evidence=result.evidence,
                )
        return AntiPatternDecision(
            result="pass",
            matched_anti_pattern=None,
            anti_pattern_list_version=self.version,
            matcher_id=None,
            match_hash=None,
            evidence=None,
        )


def _normalize_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(paths, tuple):
        raise AntiPatternListError("paths must be a tuple of strings")
    for path in paths:
        if not isinstance(path, str) or not path:
            raise AntiPatternListError("paths must be non-empty strings")
    return tuple(sorted(set(paths)))


def _validate_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise AntiPatternListError(f"{label} must be a 64-character hash")
    try:
        int(value, 16)
    except ValueError as exc:
        raise AntiPatternListError(f"{label} must be hexadecimal") from exc


def _validate_label(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise AntiPatternListError(f"{label} must be a non-empty string")
