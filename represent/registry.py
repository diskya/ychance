from __future__ import annotations

from typing import Any, Mapping

from .ops import DEFAULT_OPS, PrimitiveOp
from .spec import Spec, finalize_spec, load_spec


class SpecRegistry:
    """In-memory registry of finalized specs keyed by spec_id."""

    def __init__(self, *, op_registry: Mapping[str, PrimitiveOp] | None = None) -> None:
        self._ops = dict(op_registry or DEFAULT_OPS)
        self._specs: dict[str, Spec] = {}

    @property
    def op_registry(self) -> dict[str, PrimitiveOp]:
        return dict(self._ops)

    def register(self, spec: Mapping[str, Any] | Spec) -> str:
        if isinstance(spec, Spec):
            resolved = load_spec(spec, op_registry=self._ops)
        elif "spec_id" in spec:
            resolved = load_spec(spec, op_registry=self._ops)
        else:
            resolved = load_spec(finalize_spec(spec, op_registry=self._ops), op_registry=self._ops)

        existing = self._specs.get(resolved.spec_id)
        if existing is None:
            self._specs[resolved.spec_id] = resolved
            return resolved.spec_id
        if existing.public_body() != resolved.public_body():
            raise ValueError(f"conflicting spec registration for {resolved.spec_id}")
        return resolved.spec_id

    def get(self, spec_version: str) -> Spec:
        try:
            return self._specs[spec_version]
        except KeyError as exc:
            raise KeyError(f"unknown spec version {spec_version}") from exc

    def list(self) -> list[str]:
        return sorted(self._specs)
