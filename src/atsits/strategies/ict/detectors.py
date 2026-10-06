"""Lookahead-safe deterministic evaluation components for verified ICT concepts.

CRITICAL INVARIANT:
All detection algorithms in this module operate with strict causal temporal ordering.
No function may access future candle data or emit a signal before its formal confirmation bar closes.

Specifically:
- Swing High/Low at bar `i` with `lookback_right = N` can ONLY be emitted after bar `i + N` closes.
- FVG formed across bars `i-2`, `i-1`, `i` can ONLY be emitted after bar `i` closes.
- HTF candles are only visible after their full duration interval has completed.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple
from atsits.models.market_data import Candle
from atsits.strategies.ict.models import (
    ConceptCertainty,
    FVGDirection,
    FVGRecord,
    LiquidityLevel,
    LiquidityType,
    SwingPoint,
    SwingPointType,
)


def detect_swing_points_at_bar(
    candles: Sequence[Candle],
    current_bar_index: int,
    lookback_left: int = 2,
    lookback_right: int = 2,
    use_wick: bool = True,
    concept_id: str = "verified_swing",
) -> List[SwingPoint]:
    """Detect swing points that are confirmed EXACTLY on the current bar.

    A swing high/low candidate at index `candidate_idx = current_bar_index - lookback_right`
    is confirmed if it is strictly greater/less than its `lookback_left` predecessors and
    `lookback_right` successors.

    Args:
        candles: Full historical sequence of candles up to current_bar_index.
        current_bar_index: The index of the bar that just completed.
        lookback_left: Number of required predecessor bars.
        lookback_right: Number of required successor bars (determines confirmation delay).
        use_wick: If True, uses High/Low. If False, uses Open/Close body bounds.
        concept_id: ID of the governing concept.

    Returns:
        List of SwingPoints confirmed on this exact bar (0 or 1 per type).
    """
    if current_bar_index < lookback_left + lookback_right:
        return []

    candidate_idx = current_bar_index - lookback_right
    cand = candles[candidate_idx]
    confirmed_swings: List[SwingPoint] = []

    def get_high(c: Candle) -> float:
        return c.high if use_wick else max(c.open, c.close)

    def get_low(c: Candle) -> float:
        return c.low if use_wick else min(c.open, c.close)

    cand_high = get_high(cand)
    cand_low = get_low(cand)

    # 1. Test for Swing High
    is_swing_high = True
    # Check left neighbors
    for idx in range(candidate_idx - lookback_left, candidate_idx):
        if get_high(candles[idx]) >= cand_high:
            is_swing_high = False
            break
    # Check right neighbors (up to current_bar_index)
    if is_swing_high:
        for idx in range(candidate_idx + 1, candidate_idx + lookback_right + 1):
            if get_high(candles[idx]) >= cand_high:
                is_swing_high = False
                break

    if is_swing_high:
        confirmed_swings.append(
            SwingPoint(
                swing_id=f"sh_{cand.timestamp.strftime('%Y%m%d%H%M')}",
                swing_type=SwingPointType.SWING_HIGH,
                price=cand_high,
                timestamp=cand.timestamp,
                confirmed_at=candles[current_bar_index].timestamp,
                lookback_candles=lookback_left,
                use_wick=use_wick,
                source_concept_id=concept_id,
                certainty=ConceptCertainty.EXPLICIT,
            )
        )

    # 2. Test for Swing Low
    is_swing_low = True
    # Check left neighbors
    for idx in range(candidate_idx - lookback_left, candidate_idx):
        if get_low(candles[idx]) <= cand_low:
            is_swing_low = False
            break
    # Check right neighbors (up to current_bar_index)
    if is_swing_low:
        for idx in range(candidate_idx + 1, candidate_idx + lookback_right + 1):
            if get_low(candles[idx]) <= cand_low:
                is_swing_low = False
                break

    if is_swing_low:
        confirmed_swings.append(
            SwingPoint(
                swing_id=f"sl_{cand.timestamp.strftime('%Y%m%d%H%M')}",
                swing_type=SwingPointType.SWING_LOW,
                price=cand_low,
                timestamp=cand.timestamp,
                confirmed_at=candles[current_bar_index].timestamp,
                lookback_candles=lookback_left,
                use_wick=use_wick,
                source_concept_id=concept_id,
                certainty=ConceptCertainty.EXPLICIT,
            )
        )

    return confirmed_swings


def detect_fvg_at_bar(
    candles: Sequence[Candle],
    current_bar_index: int,
    min_gap_size: float = 0.0,
    concept_id: str = "verified_fvg",
) -> Optional[FVGRecord]:
    """Detect an FVG formed across `[current_bar_index - 2, current_bar_index - 1, current_bar_index]`.

    CRITICAL BOUNDARY DISTINCTION:
    This function detects ONLY geometric FVG formation events across completed bars.
    It does NOT evaluate trading entry, fill/mitigation, order execution, stop loss,
    or targets, which require an explicitly taught and verified ENTRY_MODEL and RISK specification.

    Timing Invariant:
    An FVG is ONLY confirmed when the 3rd candle (`current_bar_index`) has fully completed.

    Returns:
        FVGRecord if an FVG is confirmed on this bar, otherwise None.
    """
    if current_bar_index < 2:
        return None

    c1 = candles[current_bar_index - 2]
    c2 = candles[current_bar_index - 1]
    c3 = candles[current_bar_index]

    # Bullish FVG: Candle 3 Low > Candle 1 High
    if c3.low > c1.high:
        gap = c3.low - c1.high
        if gap >= min_gap_size:
            return FVGRecord(
                fvg_id=f"fvg_bull_{c2.timestamp.strftime('%Y%m%d%H%M')}",
                direction=FVGDirection.BULLISH,
                upper_boundary=c3.low,
                lower_boundary=c1.high,
                formation_candle_1_ts=c1.timestamp,
                formation_candle_2_ts=c2.timestamp,
                formation_candle_3_ts=c3.timestamp,
                timeframe=c3.timeframe,
                source_concept_id=concept_id,
                certainty=ConceptCertainty.EXPLICIT,
            )

    # Bearish FVG: Candle 3 High < Candle 1 Low
    elif c3.high < c1.low:
        gap = c1.low - c3.high
        if gap >= min_gap_size:
            return FVGRecord(
                fvg_id=f"fvg_bear_{c2.timestamp.strftime('%Y%m%d%H%M')}",
                direction=FVGDirection.BEARISH,
                upper_boundary=c1.low,
                lower_boundary=c3.high,
                formation_candle_1_ts=c1.timestamp,
                formation_candle_2_ts=c2.timestamp,
                formation_candle_3_ts=c3.timestamp,
                timeframe=c3.timeframe,
                source_concept_id=concept_id,
                certainty=ConceptCertainty.EXPLICIT,
            )

    return None


def evaluate_liquidity_sweep(
    candle: Candle,
    level: LiquidityLevel,
    close_inside_required: bool = True,
) -> bool:
    """Evaluate whether a completed candle performs a liquidity sweep of a given level.

    CRITICAL BOUNDARY DISTINCTION:
    This function evaluates ONLY the low-level price relationship against a supplied reference level.
    It does NOT select which reference levels matter, identify market structure, or constitute
    a complete trade setup, all of which require explicit human teaching.

    For Buy-Side Liquidity / Swing High:
      - Candle High > level.price (liquidity is tapped/breached)
      - If close_inside_required: Candle Close <= level.price (rejection back inside)

    For Sell-Side Liquidity / Swing Low:
      - Candle Low < level.price (liquidity is tapped/breached)
      - If close_inside_required: Candle Close >= level.price (rejection back inside)
    """
    is_high_side = level.level_type in (
        LiquidityType.SWING_HIGH,
        LiquidityType.EQUAL_HIGHS,
        LiquidityType.PREVIOUS_HIGH,
        LiquidityType.SESSION_HIGH,
    )

    if is_high_side:
        if candle.high > level.price:
            if close_inside_required:
                return candle.close <= level.price
            return True
    else:
        if candle.low < level.price:
            if close_inside_required:
                return candle.close >= level.price
            return True

    return False

