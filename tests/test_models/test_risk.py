"""Unit tests for RiskConfig model."""

import pytest
from pydantic import ValidationError
from atsits.models.risk import RiskConfig


def test_valid_risk_config():
    """Verify valid RiskConfig initialization."""
    risk = RiskConfig(
        max_risk_per_trade_pct=0.01,
        max_open_positions=2,
        account_balance=25000.0,
        max_leverage=3.0,
    )
    assert risk.max_risk_per_trade_pct == 0.01
    assert risk.max_open_positions == 2
    assert risk.account_balance == 25000.0
    assert risk.max_leverage == 3.0


@pytest.mark.parametrize(
    "risk_pct, max_pos, balance, leverage",
    [
        (0.0, 1, 10000.0, 1.0),      # risk_pct must be > 0
        (1.5, 1, 10000.0, 1.0),      # risk_pct must be <= 1.0 (100%)
        (-0.01, 1, 10000.0, 1.0),    # risk_pct must not be negative
        (0.01, 0, 10000.0, 1.0),     # max_positions must be >= 1
        (0.01, 1, 0.0, 1.0),         # balance must be > 0
        (0.01, 1, -500.0, 1.0),      # balance must not be negative
        (0.01, 1, 10000.0, 0.5),     # leverage must be >= 1.0
    ],
)
def test_invalid_risk_config_bounds(risk_pct, max_pos, balance, leverage):
    """Verify rejection of risk configuration boundary violations."""
    with pytest.raises(ValidationError):
        RiskConfig(
            max_risk_per_trade_pct=risk_pct,
            max_open_positions=max_pos,
            account_balance=balance,
            max_leverage=leverage,
        )
