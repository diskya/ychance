from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .matcher import MatcherDag
from .stats import decode_number, hash_payload, stable_float_text


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class OriginalityConfig:
    target_size: int = 50
    max_size: int = 50
    stale_after_cycles: int = 4
    min_keep_score: str = "0"

    def __post_init__(self) -> None:
        if not isinstance(self.target_size, int) or self.target_size < 0:
            raise ValueError("target_size must be a non-negative int")
        if not isinstance(self.max_size, int) or self.max_size < 0:
            raise ValueError("max_size must be a non-negative int")
        if self.target_size > self.max_size or self.max_size > 50:
            raise ValueError("target_size must be <= max_size <= 50")
        if not isinstance(self.stale_after_cycles, int) or self.stale_after_cycles < 0:
            raise ValueError("stale_after_cycles must be a non-negative int")
        object.__setattr__(self, "min_keep_score", stable_float_text(self.min_keep_score))

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_size": self.target_size,
            "max_size": self.max_size,
            "stale_after_cycles": self.stale_after_cycles,
            "min_keep_score": self.min_keep_score,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OriginalityConfig":
        return cls(
            target_size=int(raw["target_size"]),
            max_size=int(raw["max_size"]),
            stale_after_cycles=int(raw["stale_after_cycles"]),
            min_keep_score=str(raw["min_keep_score"]),
        )


@dataclass(frozen=True)
class AntiPatternEntry:
    entry_id: str
    matcher: MatcherDag
    created_cycle: int
    active: bool = True
    last_hit_cycle: int | None = None
    last_review_cycle: int | None = None
    keep_score: str = "0"

    def __post_init__(self) -> None:
        if not isinstance(self.entry_id, str) or not _SHA256_RE.match(self.entry_id):
            raise ValueError("entry_id must be a sha256 hex string")
        if not isinstance(self.matcher, MatcherDag):
            raise TypeError("matcher must be a MatcherDag")
        if not isinstance(self.created_cycle, int) or self.created_cycle < 0:
            raise ValueError("created_cycle must be a non-negative int")
        if self.last_hit_cycle is not None and self.last_hit_cycle < 0:
            raise ValueError("last_hit_cycle must be non-negative or None")
        if self.last_review_cycle is not None and self.last_review_cycle < 0:
            raise ValueError("last_review_cycle must be non-negative or None")
        object.__setattr__(self, "keep_score", stable_float_text(self.keep_score))

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "matcher": self.matcher.as_dict(),
            "created_cycle": self.created_cycle,
            "active": self.active,
            "last_hit_cycle": self.last_hit_cycle,
            "last_review_cycle": self.last_review_cycle,
            "keep_score": self.keep_score,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AntiPatternEntry":
        return cls(
            entry_id=str(raw["entry_id"]),
            matcher=MatcherDag.from_dict(raw["matcher"]),
            created_cycle=int(raw["created_cycle"]),
            active=bool(raw["active"]),
            last_hit_cycle=_optional_int(raw.get("last_hit_cycle")),
            last_review_cycle=_optional_int(raw.get("last_review_cycle")),
            keep_score=str(raw["keep_score"]),
        )


@dataclass(frozen=True)
class AntiPatternListState:
    version: str
    entries: tuple[AntiPatternEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "entries", tuple(sorted(self.entries, key=lambda item: item.entry_id)))
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("entry_id items must be unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "entries": [entry.as_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AntiPatternListState":
        return cls(
            version=str(raw["version"]),
            entries=tuple(AntiPatternEntry.from_dict(item) for item in raw["entries"]),
        )


@dataclass(frozen=True)
class ReviewFeedback:
    m2a_id: str
    current_cycle: int
    meta_validation_passed: bool
    entry_scores: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.m2a_id, str) or not self.m2a_id:
            raise ValueError("m2a_id must be a non-empty string")
        if not isinstance(self.current_cycle, int) or self.current_cycle < 0:
            raise ValueError("current_cycle must be a non-negative int")
        object.__setattr__(
            self,
            "entry_scores",
            {str(key): stable_float_text(raw_item) for key, raw_item in self.entry_scores.items()},
        )


@dataclass(frozen=True)
class ReviewOutput:
    state: AntiPatternListState
    retired_entry_ids: tuple[str, ...]
    state_hash_before: str
    state_hash_after: str


def empty_seed_state() -> AntiPatternListState:
    return make_state(())


def make_entry(
    matcher: MatcherDag,
    *,
    created_cycle: int,
    active: bool = True,
    last_hit_cycle: int | None = None,
    last_review_cycle: int | None = None,
    keep_score: str = "0",
) -> AntiPatternEntry:
    entry_id = hash_payload(
        {
            "matcher": matcher.as_dict(),
            "created_cycle": created_cycle,
        }
    )
    return AntiPatternEntry(
        entry_id=entry_id,
        matcher=matcher,
        created_cycle=created_cycle,
        active=active,
        last_hit_cycle=last_hit_cycle,
        last_review_cycle=last_review_cycle,
        keep_score=keep_score,
    )


def make_state(entries: tuple[AntiPatternEntry, ...] | list[AntiPatternEntry]) -> AntiPatternListState:
    sorted_entries = tuple(sorted(entries, key=lambda item: item.entry_id))
    return AntiPatternListState(
        version=hash_payload({"entries": [entry.as_dict() for entry in sorted_entries]}),
        entries=sorted_entries,
    )


def state_hash(state: AntiPatternListState) -> str:
    return hash_payload(state.as_dict())


def config_hash(config: OriginalityConfig) -> str:
    return hash_payload(config.as_dict())


def active_entries(state: AntiPatternListState) -> tuple[AntiPatternEntry, ...]:
    return tuple(entry for entry in sorted(state.entries, key=lambda item: item.entry_id) if entry.active)


def with_entry_hits(
    state: AntiPatternListState,
    entry_ids: tuple[str, ...] | list[str],
    cycle_index: int,
) -> AntiPatternListState:
    hit_ids = set(entry_ids)
    if not hit_ids:
        return state
    return make_state(
        tuple(
            replace(entry, last_hit_cycle=cycle_index)
            if entry.entry_id in hit_ids
            else entry
            for entry in state.entries
        )
    )


def bound_anti_pattern_list(
    state: AntiPatternListState,
    config: OriginalityConfig,
) -> AntiPatternListState:
    active_rank = sorted(
        active_entries(state),
        key=lambda item: (-decode_number(item.keep_score), item.entry_id),
    )
    keep_active = {entry.entry_id for entry in active_rank[: config.target_size]}
    adjusted = tuple(
        replace(entry, active=False)
        if entry.active and entry.entry_id not in keep_active
        else entry
        for entry in state.entries
    )
    ranked = sorted(
        adjusted,
        key=lambda item: (
            0 if item.active else 1,
            -decode_number(item.keep_score),
            item.entry_id,
        ),
    )
    return make_state(tuple(ranked[: config.max_size]))


def review_anti_pattern_list(
    state: AntiPatternListState,
    feedback: ReviewFeedback,
    config: OriginalityConfig,
) -> ReviewOutput:
    before_hash = state_hash(state)
    if not feedback.meta_validation_passed:
        retired = tuple(entry.entry_id for entry in active_entries(state))
        after = empty_seed_state()
        return ReviewOutput(
            state=after,
            retired_entry_ids=retired,
            state_hash_before=before_hash,
            state_hash_after=state_hash(after),
        )

    updated: list[AntiPatternEntry] = []
    for entry in state.entries:
        score = feedback.entry_scores.get(entry.entry_id, entry.keep_score)
        ref_cycle = entry.last_hit_cycle if entry.last_hit_cycle is not None else entry.created_cycle
        stale = entry.active and feedback.current_cycle - ref_cycle >= config.stale_after_cycles
        low_score = entry.active and decode_number(score) < decode_number(config.min_keep_score)
        updated.append(
            replace(
                entry,
                active=False if stale or low_score else entry.active,
                last_review_cycle=feedback.current_cycle,
                keep_score=score,
            )
        )

    bounded = bound_anti_pattern_list(make_state(tuple(updated)), config)
    active_after = {entry.entry_id for entry in active_entries(bounded)}
    retired = tuple(
        entry.entry_id for entry in active_entries(state) if entry.entry_id not in active_after
    )
    return ReviewOutput(
        state=bounded,
        retired_entry_ids=retired,
        state_hash_before=before_hash,
        state_hash_after=state_hash(bounded),
    )


def _optional_int(raw: Any) -> int | None:
    if raw is None:
        return None
    return int(raw)
