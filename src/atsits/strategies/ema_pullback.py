"""Locked implementation of EMA_Pullback_v1.0 strategy."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from atsits.indicators.ema import EMAIndicator
from atsits.models.market_data import Candle


@dataclass(frozen=True)
class PullbackCandidate:
    """Represents a qualifying pullback candle waiting for confirmation on the next bar."""

    candle: Candle
    direction: str  # "LONG" or "SHORT"


@dataclass(frozen=True)
class EntrySignal:
    """Signal indicating a confirmed setup ready for market entry on the next bar open."""

    strategy_version: str
    symbol: str
    timeframe: str
    direction: str  # "LONG" or "SHORT"
    pullback_timestamp: datetime
    confirmation_timestamp: datetime
    stop_price: float
    pullback_high: float = 0.0
    pullback_low: float = 0.0


class EMAPullbackStrategy:
    """Strategy implementation for EMA_Pullback_v1.0.

    Rules:
    - Indicators: EMA20 and EMA50.
    - Long Trend: EMA20 > EMA50.
    - Long Pullback: Completed candle has Low <= EMA20.
    - Long Confirmation: Immediately next completed candle must have Close > Pullback High,
      Close > EMA20, and trend must remain EMA20 > EMA50.
    - Long Stop Loss: Pullback candle Low.
    - Long Target: 2R.

    - Short Trend: EMA20 < EMA50.
    - Short Pullback: Completed candle has High >= EMA20.
    - Short Confirmation: Immediately next completed candle must have Close < Pullback Low,
      Close < EMA20, and trend must remain EMA20 < EMA50.
    - Short Stop Loss: Pullback candle High.
    - Short Target: 2R.

    Strict Constraints:
    - No multi-candle confirmation window.
    - The confirmation candle cannot serve as a new pullback candle in the same step.
    - Pullback candle never triggers entry directly.
    """

    VERSION: str = "1.0.0"
    NAME: str = "EMA_Pullback_v1.0"

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        take_profit_rr: float = 2.0,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.take_profit_rr = float(take_profit_rr)
        self.fast_ema = EMAIndicator(period=fast_period)
        self.slow_ema = EMAIndicator(period=slow_period)
        self._pullback_candidate: Optional[PullbackCandidate] = None

    @property
    def is_ready(self) -> bool:
        """True if both fast and slow EMAs have completed warmup."""
        return self.fast_ema.is_ready and self.slow_ema.is_ready

    def reset(self) -> None:
        """Reset strategy and indicator state."""
        self.fast_ema.reset()
        self.slow_ema.reset()
        self._pullback_candidate = None

    def on_candle(self, candle: Candle, has_open_position: bool) -> Optional[EntrySignal]:
        """Process a completed candle and return an EntrySignal if confirmed.

        Args:
            candle: The completed candle.
            has_open_position: Whether a position is currently active (if True, setups are ignored).

        Returns:
            EntrySignal if a confirmed setup was completed on this candle, otherwise None.
        """
        ema20 = self.fast_ema.update(candle.close)
        ema50 = self.slow_ema.update(candle.close)

        # If indicators are still in warmup period, do not evaluate setups
        if ema20 is None or ema50 is None:
            self._pullback_candidate = None
            return None

        # If a position is already open, ignore setups and clear candidate state
        if has_open_position:
            self._pullback_candidate = None
            return None

        signal: Optional[EntrySignal] = None
        was_confirmation_step = False

        # 1. Evaluate pending pullback candidate from the immediately preceding candle
        if self._pullback_candidate is not None:
            was_confirmation_step = True
            candidate = self._pullback_candidate
            self._pullback_candidate = None  # Single-candle window: cleared regardless of outcome

            if candidate.direction == "LONG":
                # Long confirmation check:
                # 1. Trend alignment still holds (EMA20 > EMA50)
                # 2. Close > Pullback High
                # 3. Close > EMA20
                if ema20 > ema50 and candle.close > candidate.candle.high and candle.close > ema20:
                    signal = EntrySignal(
                        strategy_version=self.VERSION,
                        symbol=candle.symbol,
                        timeframe=candle.timeframe,
                        direction="LONG",
                        pullback_timestamp=candidate.candle.timestamp,
                        confirmation_timestamp=candle.timestamp,
                        stop_price=candidate.candle.low,
                        pullback_high=candidate.candle.high,
                        pullback_low=candidate.candle.low,
                    )

            elif candidate.direction == "SHORT":
                # Short confirmation check:
                # 1. Trend alignment still holds (EMA20 < EMA50)
                # 2. Close < Pullback Low
                # 3. Close < EMA20
                if ema20 < ema50 and candle.close < candidate.candle.low and candle.close < ema20:
                    signal = EntrySignal(
                        strategy_version=self.VERSION,
                        symbol=candle.symbol,
                        timeframe=candle.timeframe,
                        direction="SHORT",
                        pullback_timestamp=candidate.candle.timestamp,
                        confirmation_timestamp=candle.timestamp,
                        stop_price=candidate.candle.high,
                        pullback_high=candidate.candle.high,
                        pullback_low=candidate.candle.low,
                    )

        # 2. If this candle was NOT tested as a confirmation candle, check for a fresh pullback
        if not was_confirmation_step:
            if ema20 > ema50 and candle.low <= ema20:
                self._pullback_candidate = PullbackCandidate(candle=candle, direction="LONG")
            elif ema20 < ema50 and candle.high >= ema20:
                self._pullback_candidate = PullbackCandidate(candle=candle, direction="SHORT")

        return signal
