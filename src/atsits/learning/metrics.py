"""Deterministic performance metric calculation functions."""

from typing import Any, Sequence, Union
from atsits.journal.models import TradeRecord
from atsits.learning.models import PerformanceMetrics
from atsits.models.backtest import SimulatedTrade

TradeType = Union[SimulatedTrade, TradeRecord]


def calculate_performance_metrics(
    trades: Sequence[TradeType],
    initial_equity: float = 10000.0,
) -> PerformanceMetrics:
    """Calculate deterministic performance metrics across a sequence of completed trades.

    Args:
        trades: Sequence of SimulatedTrade or TradeRecord items.
        initial_equity: Starting capital used to evaluate drawdown and equity curve.

    Returns:
        Immutable PerformanceMetrics instance.
    """
    sample_size = len(trades)
    if sample_size == 0:
        return PerformanceMetrics(
            sample_size=0,
            total_trades=0,
            long_trades=0,
            short_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            net_pnl=0.0,
            profit_factor=0.0,
            average_trade_pnl=0.0,
            average_winner=0.0,
            average_loser=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sl_exits=0,
            tp_exits=0,
            eod_exits=0,
            total_r=0.0,
            average_r=0.0,
            expectancy_r=0.0,
        )

    long_trades = sum(1 for t in trades if t.direction == "LONG")
    short_trades = sum(1 for t in trades if t.direction == "SHORT")
    winning_trades = sum(1 for t in trades if t.net_pnl > 0)
    losing_trades = sum(1 for t in trades if t.net_pnl < 0)

    win_rate = winning_trades / sample_size

    gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    net_pnl = sum(t.net_pnl for t in trades)

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    average_trade_pnl = net_pnl / sample_size
    average_winner = gross_profit / winning_trades if winning_trades > 0 else 0.0
    average_loser = -gross_loss / losing_trades if losing_trades > 0 else 0.0

    # Drawdown tracking
    equity = initial_equity
    peak_equity = initial_equity
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    for t in trades:
        equity += t.net_pnl
        if equity > peak_equity:
            peak_equity = equity
        dd = peak_equity - equity
        dd_pct = dd / peak_equity if peak_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

    # Exit reason counts
    sl_exits = sum(1 for t in trades if t.exit_reason == "SL_HIT")
    tp_exits = sum(1 for t in trades if t.exit_reason == "TP_HIT")
    eod_exits = sum(1 for t in trades if t.exit_reason == "END_OF_DATA")

    # R-multiple metrics
    r_multiples = [getattr(t, "r_multiple", 0.0) for t in trades]
    total_r = sum(r_multiples)
    average_r = total_r / sample_size

    win_r_list = [r for r, t in zip(r_multiples, trades) if t.net_pnl > 0]
    loss_r_list = [abs(r) for r, t in zip(r_multiples, trades) if t.net_pnl < 0]

    avg_win_r = sum(win_r_list) / len(win_r_list) if win_r_list else 0.0
    avg_loss_r = sum(loss_r_list) / len(loss_r_list) if loss_r_list else 0.0
    loss_rate = losing_trades / sample_size

    expectancy_r = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)

    return PerformanceMetrics(
        sample_size=sample_size,
        total_trades=sample_size,
        long_trades=long_trades,
        short_trades=short_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        average_trade_pnl=average_trade_pnl,
        average_winner=average_winner,
        average_loser=average_loser,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        sl_exits=sl_exits,
        tp_exits=tp_exits,
        eod_exits=eod_exits,
        total_r=total_r,
        average_r=average_r,
        expectancy_r=expectancy_r,
    )
