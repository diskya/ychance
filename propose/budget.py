"""Budget configuration and enforcement for the Propose stage.

Reads from the envelope config to determine:
- Per-cycle candidate count target (conservative)
- Per-cycle LLM cost ceiling
"""

from __future__ import annotations

import json
from pathlib import Path


class BudgetConfig:
    """Encapsulates per-cycle budget constraints."""

    def __init__(
        self,
        *,
        target_candidates_per_cycle: int = 5,
        draft_lm_budget_usd: float = 2.0,
        adjudicate_lm_budget_usd: float = 3.0,
        draft_score_threshold: float = 0.5,
        draft_model_id: str = "qwen-plus",
        adjudicate_model_id: str = "qwen-plus",
    ):
        """Initialize budget constraints.

        Args:
            target_candidates_per_cycle: target number of candidates to generate
                per cycle (conservative, stays well under per-stage ceiling).
            draft_lm_budget_usd: LLM budget for draft pass only.
            adjudicate_lm_budget_usd: LLM budget for adjudicate pass only.
            draft_score_threshold: minimum draft score before adjudicate review.
            draft_model_id: model id used for draft calls.
            adjudicate_model_id: model id used for adjudicate calls.
        """
        self.target_candidates_per_cycle = target_candidates_per_cycle
        self.draft_lm_budget_usd = draft_lm_budget_usd
        self.adjudicate_lm_budget_usd = adjudicate_lm_budget_usd
        self.draft_score_threshold = draft_score_threshold
        self.draft_model_id = draft_model_id
        self.adjudicate_model_id = adjudicate_model_id

    def total_lm_budget_usd(self) -> float:
        """Total LLM budget for a full cycle."""
        return self.draft_lm_budget_usd + self.adjudicate_lm_budget_usd


def load_budget_from_config(config_path: Path | str | None = None) -> BudgetConfig:
    """Load budget config from envelope.yaml or propose.yaml.

    If config_path is None, searches for config/propose.yaml first,
    then config/envelope.yaml. Returns defaults if neither exists.
    """
    if config_path is None:
        repo_root = Path(__file__).resolve().parents[1]
        candidates = [
            repo_root / "config" / "propose.yaml",
            repo_root / "config" / "envelope.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None:
        # No config found, use defaults
        return BudgetConfig()

    config_path = Path(config_path)
    if not config_path.exists():
        return BudgetConfig()

    text = config_path.read_text()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = _load_simple_yaml_mapping(text)

    # Navigate to propose or discovery budgets
    propose_cfg = data.get("propose", {}) or {}
    if not propose_cfg:
        # Try "discovery" or top-level fields
        propose_cfg = data.get("discovery", {}) or {}

    target_candidates = propose_cfg.get(
        "target_candidates_per_cycle",
        data.get("target_candidates_per_cycle", 5)
    )
    draft_budget = propose_cfg.get("draft_lm_budget_usd", 2.0)
    adjudicate_budget = propose_cfg.get("adjudicate_lm_budget_usd", 3.0)
    draft_threshold = propose_cfg.get("draft_score_threshold", 0.5)
    draft_model_id = propose_cfg.get("draft_model_id", "qwen-plus")
    adjudicate_model_id = propose_cfg.get("adjudicate_model_id", "qwen-plus")

    return BudgetConfig(
        target_candidates_per_cycle=int(target_candidates),
        draft_lm_budget_usd=float(draft_budget),
        adjudicate_lm_budget_usd=float(adjudicate_budget),
        draft_score_threshold=float(draft_threshold),
        draft_model_id=str(draft_model_id),
        adjudicate_model_id=str(adjudicate_model_id),
    )


def _load_simple_yaml_mapping(text: str) -> dict:
    """Parse the simple nested key/scalar YAML used under config/."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, scalar_text = line.split(":", 1)
        key = key.strip()
        scalar_text = scalar_text.split("#", 1)[0].strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if scalar_text == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(scalar_text)
    return root


def _parse_scalar(scalar_text: str):
    if scalar_text in {"true", "false"}:
        return scalar_text == "true"
    if (
        (scalar_text.startswith('"') and scalar_text.endswith('"'))
        or (scalar_text.startswith("'") and scalar_text.endswith("'"))
    ):
        return scalar_text[1:-1]
    try:
        return int(scalar_text)
    except ValueError:
        pass
    try:
        return float(scalar_text)
    except ValueError:
        return scalar_text
