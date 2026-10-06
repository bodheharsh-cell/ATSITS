"""Unit tests for StrategySpec model."""

import pytest
from pydantic import ValidationError
from atsits.models.strategy import StrategySpec


def test_default_strategy_spec():
    """Verify default values on unverified StrategySpec."""
    spec = StrategySpec(
        strategy_id="strat-001",
        name="EMA_Trend_Pullback",
        version="0.1.0",
    )
    assert spec.strategy_id == "strat-001"
    assert spec.name == "EMA_Trend_Pullback"
    assert spec.version == "0.1.0"
    assert spec.is_verified is False
    assert spec.parameters == {}


def test_verified_strategy_spec_with_params():
    """Verify creation of verified StrategySpec with human-verified parameters."""
    spec = StrategySpec(
        strategy_id="strat-002",
        name="EMA_Trend_Pullback",
        version="1.0.0",
        description="Human-verified 20/50 EMA strategy",
        parameters={
            "fast_ema": 20,
            "slow_ema": 50,
        },
        is_verified=True,
    )
    assert spec.is_verified is True
    assert spec.parameters["fast_ema"] == 20
    assert spec.parameters["slow_ema"] == 50


def test_strategy_spec_immutability():
    """Verify StrategySpec instances are frozen."""
    spec = StrategySpec(
        strategy_id="strat-001",
        name="EMA_Trend_Pullback",
        version="0.1.0",
    )
    with pytest.raises(ValidationError):
        spec.is_verified = True  # type: ignore


def test_strategy_spec_parameters_nested_immutability():
    """Verify that parameters dictionary cannot be mutated in place."""
    raw_params = {"fast_ema": 20, "nested": {"level": 1}}
    spec = StrategySpec(
        strategy_id="strat-003",
        name="EMA_Trend_Pullback",
        version="1.0.0",
        parameters=raw_params,
    )

    with pytest.raises(TypeError, match="does not support item assignment"):
        spec.parameters["fast_ema"] = 99  # type: ignore

    with pytest.raises(TypeError, match="does not support item assignment"):
        spec.parameters["nested"]["level"] = 2  # type: ignore

    # Verify mutating original dict does not alter frozen model
    raw_params["fast_ema"] = 100
    assert spec.parameters["fast_ema"] == 20
