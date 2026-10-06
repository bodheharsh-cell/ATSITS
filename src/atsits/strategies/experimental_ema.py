"""Separate experimental EMA strategy implementation (EMA20/EMA30 + 3R)."""

from typing import Optional
from atsits.strategies.ema_pullback import EMAPullbackStrategy


class EMAExperimentalStrategy(EMAPullbackStrategy):
    """Separate Experimental Strategy: EMA20 / EMA30 + 3R Take Profit.

    Rules & Constraints:
    - Indicators: EMA20 and EMA30 (Fast=20, Slow=30).
    - Long Trend: EMA20 > EMA30.
    - Long Pullback: Completed candle has Low <= EMA20.
    - Long Confirmation: Immediately next completed candle must have Close > Pullback High,
      Close > EMA20, and trend must remain EMA20 > EMA30.
    - Long Stop Loss: Pullback candle Low.
    - Long Target: 3.0R.

    - Short Trend: EMA20 < EMA30.
    - Short Pullback: Completed candle has High >= EMA20.
    - Short Confirmation: Immediately next completed candle must have Close < Pullback Low,
      Close < EMA20, and trend must remain EMA20 < EMA30.
    - Short Stop Loss: Pullback candle High.
    - Short Target: 3.0R.

    Strict Invariants Maintained:
    - Completed candle decisions only.
    - Single-candle confirmation window.
    - Entry at next candle open.
    - Configurable 1% account risk.
    - One open position per symbol, no pyramiding, no immediate reversal.
    - SL-first precedence when SL and TP occur on the same bar.
    - No lookahead bias.
    """

    VERSION: str = "EMA_Pullback_EMA20_30_3R"
    NAME: str = "EMA_Pullback_EMA20_30_3R"

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 30,
        take_profit_rr: float = 3.0,
    ):
        super().__init__(
            fast_period=fast_period,
            slow_period=slow_period,
            take_profit_rr=take_profit_rr,
        )
