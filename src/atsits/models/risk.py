"""Risk management configuration models."""

from pydantic import BaseModel, ConfigDict, Field


class RiskConfig(BaseModel):
    """Configuration governing risk thresholds and position sizing bounds."""

    model_config = ConfigDict(frozen=True)

    max_risk_per_trade_pct: float = Field(
        ...,
        gt=0.0,
        le=1.0,
        description="Maximum capital percentage risked per single trade (e.g. 0.01 for 1%)",
    )
    max_open_positions: int = Field(
        ...,
        ge=1,
        description="Maximum number of concurrently open positions allowed",
    )
    account_balance: float = Field(
        ...,
        gt=0.0,
        description="Current account balance / capital base for risk calculations",
    )
    max_leverage: float = Field(
        default=1.0,
        ge=1.0,
        description="Maximum allowed leverage factor",
    )
