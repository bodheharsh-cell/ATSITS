"""Exponential Moving Average (EMA) implementation."""

from typing import List, Optional, Sequence


class EMAIndicator:
    """Incremental, bar-by-bar Exponential Moving Average calculator.

    Computes standard EMA:
    - Multiplier alpha = 2.0 / (period + 1.0)
    - Initial value (at index period - 1) is SMA of first 'period' values.
    - Subsequent values: EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
    """

    def __init__(self, period: int):
        if period < 1:
            raise ValueError(f"EMA period must be >= 1, got {period}")
        self.period: int = period
        self.alpha: float = 2.0 / (period + 1.0)
        self._buffer: List[float] = []
        self._current_ema: Optional[float] = None

    @property
    def is_ready(self) -> bool:
        """True if the indicator has finished warmup and has a valid value."""
        return self._current_ema is not None

    @property
    def value(self) -> Optional[float]:
        """Current calculated EMA value, or None if warming up."""
        return self._current_ema

    def update(self, price: float) -> Optional[float]:
        """Update EMA with the latest closed bar price.

        Args:
            price: Closed bar price.

        Returns:
            Current EMA value or None during warmup.
        """
        if self._current_ema is None:
            self._buffer.append(price)
            if len(self._buffer) == self.period:
                self._current_ema = sum(self._buffer) / self.period
        else:
            self._current_ema = (self.alpha * price) + ((1.0 - self.alpha) * self._current_ema)

        return self._current_ema

    def reset(self) -> None:
        """Reset the indicator state."""
        self._buffer.clear()
        self._current_ema = None


def calculate_ema_series(prices: Sequence[float], period: int) -> List[Optional[float]]:
    """Calculate EMA series across a historical price sequence.

    Args:
        prices: Sequence of close prices.
        period: EMA length.

    Returns:
        List of same length as prices, with None for indices < period - 1.
    """
    indicator = EMAIndicator(period=period)
    results: List[Optional[float]] = []
    for p in prices:
        results.append(indicator.update(p))
    return results
