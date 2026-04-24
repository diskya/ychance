"""Tests for budget configuration."""

from propose import BudgetConfig, load_budget_from_config


def test_default_budget_config():
    cfg = BudgetConfig()
    assert cfg.target_candidates_per_cycle == 5
    assert cfg.draft_lm_budget_usd == 2.0
    assert cfg.adjudicate_lm_budget_usd == 3.0
    assert cfg.draft_score_threshold == 0.5
    assert cfg.draft_model_id == "qwen-plus"
    assert cfg.adjudicate_model_id == "qwen-plus"


def test_budget_config_total():
    cfg = BudgetConfig(draft_lm_budget_usd=1.0, adjudicate_lm_budget_usd=2.0)
    assert cfg.total_lm_budget_usd() == 3.0


def test_load_budget_from_config_defaults():
    cfg = load_budget_from_config(config_path="/nonexistent/path.yaml")
    assert cfg.target_candidates_per_cycle == 5
    assert cfg.draft_lm_budget_usd == 2.0
    assert cfg.adjudicate_lm_budget_usd == 3.0


def test_budget_config_is_configurable():
    cfg = BudgetConfig(
        target_candidates_per_cycle=10,
        draft_lm_budget_usd=5.0,
        adjudicate_lm_budget_usd=7.0,
    )
    assert cfg.target_candidates_per_cycle == 10
    assert cfg.total_lm_budget_usd() == 12.0


def test_load_budget_from_yaml_values(tmp_path):
    config_path = tmp_path / "propose.yaml"
    config_path.write_text(
        """
propose:
  target_candidates_per_cycle: 3
  draft_lm_budget_usd: 1.25
  adjudicate_lm_budget_usd: 4.75
  draft_score_threshold: 0.7
  draft_model_id: draft-test
  adjudicate_model_id: review-test
"""
    )
    cfg = load_budget_from_config(config_path=config_path)
    assert cfg.target_candidates_per_cycle == 3
    assert cfg.draft_lm_budget_usd == 1.25
    assert cfg.adjudicate_lm_budget_usd == 4.75
    assert cfg.draft_score_threshold == 0.7
    assert cfg.draft_model_id == "draft-test"
    assert cfg.adjudicate_model_id == "review-test"


def test_load_budget_from_propose_yaml():
    """Load budget config from config/propose.yaml and verify values flow through."""
    cfg = load_budget_from_config(config_path="/home/ubuntu/ychance/config/propose.yaml")
    assert cfg.target_candidates_per_cycle == 5
    assert cfg.draft_lm_budget_usd == 2.0
    assert cfg.adjudicate_lm_budget_usd == 3.0
    assert cfg.draft_score_threshold == 0.5
    assert cfg.draft_model_id == "qwen-plus"
    assert cfg.adjudicate_model_id == "qwen-plus"
    assert cfg.total_lm_budget_usd() == 5.0
