"""Deterministic bar-by-bar backtesting engine with optional journal integration."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence
from atsits.data.loader import validate_candle_series
from atsits.journal.models import (
    EntryRecord,
    ExitRecord,
    MarketObservationRecord,
    SetupDetectedRecord,
    SetupRejectedRecord,
    TradeRecord,
)
from atsits.journal.storage import TradingJournal
from atsits.models.backtest import (
    BacktestConfig,
    BacktestResult,
    SetupRejection,
    SimulatedTrade,
)
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy, EntrySignal


@dataclass
class _ActivePositionState:
    """Internal tracker for an active open position."""

    trade_id: str
    signal: EntrySignal
    direction: str  # "LONG" or "SHORT"
    entry_timestamp: datetime
    raw_entry_price: float
    entry_price: float  # Effective entry price after slippage
    stop_price: float
    target_price: float  # 2R target
    quantity: float
    risk_amount: float
    equity_before: float
    entry_fee: float
    entry_slippage: float


class BacktestEngine:
    """Deterministic, reproducible bar-by-bar backtester.

    Execution Flow on Bar i:
    1. Pending Entry Execution: If a signal was confirmed on bar i-1, attempt entry at bar i OPEN.
       - Validates that stop price is valid relative to open price.
       - If invalid (e.g. open <= SL for long), setup is rejected and recorded.
       - If valid, calculates position size (1% risk by default), 2R target, applies entry slippage/fees.
    2. Intrabar Position Evaluation:
       - Evaluates active position against bar i High and Low.
       - If both SL and TP are touched in the same bar, assumes SL happens first.
       - Calculates gross PnL, fees, slippage, net PnL, updates equity, and records trade.
    3. Strategy Evaluation:
       - Evaluates strategy on completed bar i.
       - If confirmed setup is produced and no position is open, schedules entry for bar i+1 OPEN.
    4. End of Data:
       - If a position remains open at the end of the dataset, it is closed at the final bar's CLOSE
         with reason 'END_OF_DATA'.
    """

    def __init__(
        self,
        strategy: Optional[EMAPullbackStrategy] = None,
        config: Optional[BacktestConfig] = None,
    ):
        self.strategy = strategy or EMAPullbackStrategy()
        self.config = config or BacktestConfig()

    def run(
        self,
        candles: Sequence[Candle],
        run_id: str = "run_001",
        journal: Optional[TradingJournal] = None,
        record_observations: bool = False,
    ) -> BacktestResult:
        """Execute deterministic backtest across a sequence of candles.

        Args:
            candles: Chronological sequence of OHLCV candles.
            run_id: Traceable identifier for this execution run.
            journal: Optional TradingJournal instance to record factual events.
            record_observations: Whether to record MarketObservationRecord for each bar.

        Returns:
            BacktestResult object containing performance metrics and trade logs.
        """
        validate_candle_series(candles)

        self.strategy.reset()
        equity: float = self.config.initial_equity
        peak_equity: float = equity
        max_drawdown: float = 0.0
        max_drawdown_pct: float = 0.0

        active_position: Optional[_ActivePositionState] = None
        pending_signal: Optional[EntrySignal] = None
        completed_trades: List[SimulatedTrade] = []
        rejections: List[SetupRejection] = []

        trade_counter = 0
        rec_counter = 0

        def make_rec_id(rtype: str) -> str:
            nonlocal rec_counter
            rec_counter += 1
            return f"{run_id}_{rtype.lower()}_{rec_counter:05d}"

        for candle in candles:
            # -------------------------------------------------------------
            # STEP 1: Process Pending Entry at bar OPEN
            # -------------------------------------------------------------
            if pending_signal is not None and active_position is None:
                sig = pending_signal
                pending_signal = None
                open_price = candle.open

                # Validate intended stop against actual open price
                is_invalid_stop = False
                if sig.direction == "LONG" and open_price <= sig.stop_price:
                    is_invalid_stop = True
                elif sig.direction == "SHORT" and open_price >= sig.stop_price:
                    is_invalid_stop = True

                if is_invalid_stop:
                    rejection = SetupRejection(
                        timestamp=candle.timestamp,
                        symbol=candle.symbol,
                        direction=sig.direction,
                        reason="INVALID_STOP_AT_OPEN",
                        details={
                            "open_price": open_price,
                            "stop_price": sig.stop_price,
                        },
                    )
                    rejections.append(rejection)

                    if journal is not None:
                        journal.append(
                            SetupRejectedRecord(
                                record_id=make_rec_id("setup_rej"),
                                timestamp=candle.timestamp,
                                run_id=run_id,
                                strategy_version=self.strategy.VERSION,
                                execution_mode="BACKTEST",
                                symbol=candle.symbol,
                                timeframe=candle.timeframe,
                                direction=sig.direction,
                                reason="INVALID_STOP_AT_OPEN",
                                details={
                                    "open_price": open_price,
                                    "stop_price": sig.stop_price,
                                },
                            )
                        )
                else:
                    trade_counter += 1
                    risk_amount = equity * self.config.risk_pct
                    risk_per_unit = abs(open_price - sig.stop_price)

                    # Position sizing: risk_amount / abs(entry - stop)
                    quantity = risk_amount / risk_per_unit

                    tp_rr = getattr(self.strategy, "take_profit_rr", 2.0)

                    if sig.direction == "LONG":
                        target_price = open_price + (tp_rr * risk_per_unit)
                        # Adverse slippage on BUY adds to entry price
                        entry_slippage_delta = (
                            self.config.cost_model.slippage_points
                            + (open_price * self.config.cost_model.slippage_pct)
                        )
                        effective_entry = open_price + entry_slippage_delta
                    else:
                        target_price = open_price - (tp_rr * risk_per_unit)
                        # Adverse slippage on SELL subtracts from entry price
                        entry_slippage_delta = (
                            self.config.cost_model.slippage_points
                            + (open_price * self.config.cost_model.slippage_pct)
                        )
                        effective_entry = open_price - entry_slippage_delta

                    entry_fee = effective_entry * quantity * self.config.cost_model.commission_rate
                    entry_slippage_cost = entry_slippage_delta * quantity

                    trade_id = f"trd-{trade_counter:04d}"

                    active_position = _ActivePositionState(
                        trade_id=trade_id,
                        signal=sig,
                        direction=sig.direction,
                        entry_timestamp=candle.timestamp,
                        raw_entry_price=open_price,
                        entry_price=effective_entry,
                        stop_price=sig.stop_price,
                        target_price=target_price,
                        quantity=quantity,
                        risk_amount=risk_amount,
                        equity_before=equity,
                        entry_fee=entry_fee,
                        entry_slippage=entry_slippage_cost,
                    )

                    if journal is not None:
                        journal.append(
                            EntryRecord(
                                record_id=make_rec_id("entry"),
                                trade_id=trade_id,
                                timestamp=candle.timestamp,
                                run_id=run_id,
                                strategy_version=self.strategy.VERSION,
                                execution_mode="BACKTEST",
                                symbol=candle.symbol,
                                timeframe=candle.timeframe,
                                direction=sig.direction,
                                price=effective_entry,
                                raw_price=open_price,
                                quantity=quantity,
                                stop_price=sig.stop_price,
                                target_price=target_price,
                                risk_amount=risk_amount,
                                equity_before=equity,
                                fees=entry_fee,
                                slippage=entry_slippage_cost,
                            )
                        )

            # -------------------------------------------------------------
            # STEP 2: Intrabar Evaluation of Active Position
            # -------------------------------------------------------------
            if active_position is not None:
                exit_triggered = False
                exit_reason = ""
                raw_exit_price = 0.0

                if active_position.direction == "LONG":
                    sl_hit = candle.low <= active_position.stop_price
                    tp_hit = candle.high >= active_position.target_price

                    if sl_hit and tp_hit:
                        # Ambiguity resolution: SL takes precedence when both occur in same bar
                        exit_triggered = True
                        exit_reason = "SL_HIT"
                        raw_exit_price = active_position.stop_price
                    elif sl_hit:
                        exit_triggered = True
                        exit_reason = "SL_HIT"
                        raw_exit_price = active_position.stop_price
                    elif tp_hit:
                        exit_triggered = True
                        exit_reason = "TP_HIT"
                        raw_exit_price = active_position.target_price

                    if exit_triggered:
                        exit_slippage_delta = (
                            self.config.cost_model.slippage_points
                            + (raw_exit_price * self.config.cost_model.slippage_pct)
                        )
                        effective_exit = raw_exit_price - exit_slippage_delta
                        exit_fee = effective_exit * active_position.quantity * self.config.cost_model.commission_rate
                        exit_slippage_cost = exit_slippage_delta * active_position.quantity

                        gross_pnl = (raw_exit_price - active_position.raw_entry_price) * active_position.quantity
                        total_fees = active_position.entry_fee + exit_fee
                        total_slippage = active_position.entry_slippage + exit_slippage_cost
                        net_pnl = gross_pnl - total_fees - total_slippage
                        r_multiple = net_pnl / active_position.risk_amount

                        equity_before = active_position.equity_before
                        equity += net_pnl

                        sim_trade = SimulatedTrade(
                            trade_id=active_position.trade_id,
                            strategy_version=active_position.signal.strategy_version,
                            symbol=candle.symbol,
                            timeframe=candle.timeframe,
                            direction=active_position.direction,
                            pullback_timestamp=active_position.signal.pullback_timestamp,
                            confirmation_timestamp=active_position.signal.confirmation_timestamp,
                            entry_timestamp=active_position.entry_timestamp,
                            entry_price=active_position.entry_price,
                            stop_price=active_position.stop_price,
                            target_price=active_position.target_price,
                            quantity=active_position.quantity,
                            risk_amount=active_position.risk_amount,
                            exit_timestamp=candle.timestamp,
                            exit_price=effective_exit,
                            exit_reason=exit_reason,
                            gross_pnl=gross_pnl,
                            fees=total_fees,
                            slippage=total_slippage,
                            net_pnl=net_pnl,
                            r_multiple=r_multiple,
                        )
                        completed_trades.append(sim_trade)

                        if journal is not None:
                            journal.append(
                                ExitRecord(
                                    record_id=make_rec_id("exit"),
                                    trade_id=active_position.trade_id,
                                    timestamp=candle.timestamp,
                                    run_id=run_id,
                                    strategy_version=self.strategy.VERSION,
                                    execution_mode="BACKTEST",
                                    symbol=candle.symbol,
                                    timeframe=candle.timeframe,
                                    direction=active_position.direction,
                                    exit_price=effective_exit,
                                    raw_exit_price=raw_exit_price,
                                    exit_reason=exit_reason,
                                    quantity=active_position.quantity,
                                    gross_pnl=gross_pnl,
                                    fees=total_fees,
                                    slippage=total_slippage,
                                    net_pnl=net_pnl,
                                    equity_after=equity,
                                )
                            )
                            journal.append(
                                TradeRecord(
                                    record_id=make_rec_id("trade"),
                                    trade_id=active_position.trade_id,
                                    timestamp=candle.timestamp,
                                    run_id=run_id,
                                    strategy_version=self.strategy.VERSION,
                                    execution_mode="BACKTEST",
                                    symbol=candle.symbol,
                                    timeframe=candle.timeframe,
                                    direction=active_position.direction,
                                    pullback_timestamp=active_position.signal.pullback_timestamp,
                                    confirmation_timestamp=active_position.signal.confirmation_timestamp,
                                    entry_timestamp=active_position.entry_timestamp,
                                    entry_price=active_position.entry_price,
                                    stop_price=active_position.stop_price,
                                    target_price=active_position.target_price,
                                    quantity=active_position.quantity,
                                    risk_amount=active_position.risk_amount,
                                    exit_timestamp=candle.timestamp,
                                    exit_price=effective_exit,
                                    exit_reason=exit_reason,
                                    gross_pnl=gross_pnl,
                                    fees=total_fees,
                                    slippage=total_slippage,
                                    net_pnl=net_pnl,
                                    r_multiple=r_multiple,
                                    equity_before=equity_before,
                                    equity_after=equity,
                                )
                            )

                        active_position = None

                elif active_position.direction == "SHORT":
                    sl_hit = candle.high >= active_position.stop_price
                    tp_hit = candle.low <= active_position.target_price

                    if sl_hit and tp_hit:
                        # Ambiguity resolution: SL takes precedence
                        exit_triggered = True
                        exit_reason = "SL_HIT"
                        raw_exit_price = active_position.stop_price
                    elif sl_hit:
                        exit_triggered = True
                        exit_reason = "SL_HIT"
                        raw_exit_price = active_position.stop_price
                    elif tp_hit:
                        exit_triggered = True
                        exit_reason = "TP_HIT"
                        raw_exit_price = active_position.target_price

                    if exit_triggered:
                        exit_slippage_delta = (
                            self.config.cost_model.slippage_points
                            + (raw_exit_price * self.config.cost_model.slippage_pct)
                        )
                        effective_exit = raw_exit_price + exit_slippage_delta
                        exit_fee = effective_exit * active_position.quantity * self.config.cost_model.commission_rate
                        exit_slippage_cost = exit_slippage_delta * active_position.quantity

                        gross_pnl = (active_position.raw_entry_price - raw_exit_price) * active_position.quantity
                        total_fees = active_position.entry_fee + exit_fee
                        total_slippage = active_position.entry_slippage + exit_slippage_cost
                        net_pnl = gross_pnl - total_fees - total_slippage
                        r_multiple = net_pnl / active_position.risk_amount

                        equity_before = active_position.equity_before
                        equity += net_pnl

                        sim_trade = SimulatedTrade(
                            trade_id=active_position.trade_id,
                            strategy_version=active_position.signal.strategy_version,
                            symbol=candle.symbol,
                            timeframe=candle.timeframe,
                            direction=active_position.direction,
                            pullback_timestamp=active_position.signal.pullback_timestamp,
                            confirmation_timestamp=active_position.signal.confirmation_timestamp,
                            entry_timestamp=active_position.entry_timestamp,
                            entry_price=active_position.entry_price,
                            stop_price=active_position.stop_price,
                            target_price=active_position.target_price,
                            quantity=active_position.quantity,
                            risk_amount=active_position.risk_amount,
                            exit_timestamp=candle.timestamp,
                            exit_price=effective_exit,
                            exit_reason=exit_reason,
                            gross_pnl=gross_pnl,
                            fees=total_fees,
                            slippage=total_slippage,
                            net_pnl=net_pnl,
                            r_multiple=r_multiple,
                        )
                        completed_trades.append(sim_trade)

                        if journal is not None:
                            journal.append(
                                ExitRecord(
                                    record_id=make_rec_id("exit"),
                                    trade_id=active_position.trade_id,
                                    timestamp=candle.timestamp,
                                    run_id=run_id,
                                    strategy_version=self.strategy.VERSION,
                                    execution_mode="BACKTEST",
                                    symbol=candle.symbol,
                                    timeframe=candle.timeframe,
                                    direction=active_position.direction,
                                    exit_price=effective_exit,
                                    raw_exit_price=raw_exit_price,
                                    exit_reason=exit_reason,
                                    quantity=active_position.quantity,
                                    gross_pnl=gross_pnl,
                                    fees=total_fees,
                                    slippage=total_slippage,
                                    net_pnl=net_pnl,
                                    equity_after=equity,
                                )
                            )
                            journal.append(
                                TradeRecord(
                                    record_id=make_rec_id("trade"),
                                    trade_id=active_position.trade_id,
                                    timestamp=candle.timestamp,
                                    run_id=run_id,
                                    strategy_version=self.strategy.VERSION,
                                    execution_mode="BACKTEST",
                                    symbol=candle.symbol,
                                    timeframe=candle.timeframe,
                                    direction=active_position.direction,
                                    pullback_timestamp=active_position.signal.pullback_timestamp,
                                    confirmation_timestamp=active_position.signal.confirmation_timestamp,
                                    entry_timestamp=active_position.entry_timestamp,
                                    entry_price=active_position.entry_price,
                                    stop_price=active_position.stop_price,
                                    target_price=active_position.target_price,
                                    quantity=active_position.quantity,
                                    risk_amount=active_position.risk_amount,
                                    exit_timestamp=candle.timestamp,
                                    exit_price=effective_exit,
                                    exit_reason=exit_reason,
                                    gross_pnl=gross_pnl,
                                    fees=total_fees,
                                    slippage=total_slippage,
                                    net_pnl=net_pnl,
                                    r_multiple=r_multiple,
                                    equity_before=equity_before,
                                    equity_after=equity,
                                )
                            )

                        active_position = None

            # Update equity peak and drawdown tracking
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            dd_pct = dd / peak_equity if peak_equity > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

            # -------------------------------------------------------------
            # STEP 3: Strategy Evaluation on Completed Candle
            # -------------------------------------------------------------
            has_pos = active_position is not None
            sig = self.strategy.on_candle(candle, has_open_position=has_pos)

            if sig is not None and not has_pos:
                pending_signal = sig

                if journal is not None:
                    ema20_val = self.strategy.fast_ema.value
                    ema50_val = self.strategy.slow_ema.value
                    journal.append(
                        SetupDetectedRecord(
                            record_id=make_rec_id("setup"),
                            timestamp=candle.timestamp,
                            run_id=run_id,
                            strategy_version=self.strategy.VERSION,
                            execution_mode="BACKTEST",
                            symbol=candle.symbol,
                            timeframe=candle.timeframe,
                            direction=sig.direction,
                            pullback_timestamp=sig.pullback_timestamp,
                            pullback_high=sig.pullback_high,
                            pullback_low=sig.pullback_low,
                            confirmation_timestamp=sig.confirmation_timestamp,
                            ema20=ema20_val or 0.0,
                            ema50=ema50_val or 0.0,
                            facts={"stop_price": sig.stop_price},
                        )
                    )

            if journal is not None and record_observations:
                ema20_val = self.strategy.fast_ema.value
                ema50_val = self.strategy.slow_ema.value
                trend_str = None
                if ema20_val is not None and ema50_val is not None:
                    trend_str = "UPTREND" if ema20_val > ema50_val else ("DOWNTREND" if ema20_val < ema50_val else "FLAT")

                journal.append(
                    MarketObservationRecord(
                        record_id=make_rec_id("obs"),
                        timestamp=candle.timestamp,
                        run_id=run_id,
                        strategy_version=self.strategy.VERSION,
                        execution_mode="BACKTEST",
                        symbol=candle.symbol,
                        timeframe=candle.timeframe,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                        ema20=ema20_val,
                        ema50=ema50_val,
                        trend=trend_str,
                    )
                )

        # -----------------------------------------------------------------
        # STEP 4: End of Dataset Handling
        # -----------------------------------------------------------------
        if active_position is not None:
            last_candle = candles[-1]
            raw_exit_price = last_candle.close

            if active_position.direction == "LONG":
                exit_slippage_delta = (
                    self.config.cost_model.slippage_points
                    + (raw_exit_price * self.config.cost_model.slippage_pct)
                )
                effective_exit = raw_exit_price - exit_slippage_delta
                exit_fee = effective_exit * active_position.quantity * self.config.cost_model.commission_rate
                exit_slippage_cost = exit_slippage_delta * active_position.quantity
                gross_pnl = (raw_exit_price - active_position.raw_entry_price) * active_position.quantity
            else:
                exit_slippage_delta = (
                    self.config.cost_model.slippage_points
                    + (raw_exit_price * self.config.cost_model.slippage_pct)
                )
                effective_exit = raw_exit_price + exit_slippage_delta
                exit_fee = effective_exit * active_position.quantity * self.config.cost_model.commission_rate
                exit_slippage_cost = exit_slippage_delta * active_position.quantity
                gross_pnl = (active_position.raw_entry_price - raw_exit_price) * active_position.quantity

            total_fees = active_position.entry_fee + exit_fee
            total_slippage = active_position.entry_slippage + exit_slippage_cost
            net_pnl = gross_pnl - total_fees - total_slippage
            r_multiple = net_pnl / active_position.risk_amount
            equity_before = active_position.equity_before
            equity += net_pnl

            sim_trade = SimulatedTrade(
                trade_id=active_position.trade_id,
                strategy_version=active_position.signal.strategy_version,
                symbol=last_candle.symbol,
                timeframe=last_candle.timeframe,
                direction=active_position.direction,
                pullback_timestamp=active_position.signal.pullback_timestamp,
                confirmation_timestamp=active_position.signal.confirmation_timestamp,
                entry_timestamp=active_position.entry_timestamp,
                entry_price=active_position.entry_price,
                stop_price=active_position.stop_price,
                target_price=active_position.target_price,
                quantity=active_position.quantity,
                risk_amount=active_position.risk_amount,
                exit_timestamp=last_candle.timestamp,
                exit_price=effective_exit,
                exit_reason="END_OF_DATA",
                gross_pnl=gross_pnl,
                fees=total_fees,
                slippage=total_slippage,
                net_pnl=net_pnl,
                r_multiple=r_multiple,
            )
            completed_trades.append(sim_trade)

            if journal is not None:
                journal.append(
                    ExitRecord(
                        record_id=make_rec_id("exit"),
                        trade_id=active_position.trade_id,
                        timestamp=last_candle.timestamp,
                        run_id=run_id,
                        strategy_version=self.strategy.VERSION,
                        execution_mode="BACKTEST",
                        symbol=last_candle.symbol,
                        timeframe=last_candle.timeframe,
                        direction=active_position.direction,
                        exit_price=effective_exit,
                        raw_exit_price=raw_exit_price,
                        exit_reason="END_OF_DATA",
                        quantity=active_position.quantity,
                        gross_pnl=gross_pnl,
                        fees=total_fees,
                        slippage=total_slippage,
                        net_pnl=net_pnl,
                        equity_after=equity,
                    )
                )
                journal.append(
                    TradeRecord(
                        record_id=make_rec_id("trade"),
                        trade_id=active_position.trade_id,
                        timestamp=last_candle.timestamp,
                        run_id=run_id,
                        strategy_version=self.strategy.VERSION,
                        execution_mode="BACKTEST",
                        symbol=last_candle.symbol,
                        timeframe=last_candle.timeframe,
                        direction=active_position.direction,
                        pullback_timestamp=active_position.signal.pullback_timestamp,
                        confirmation_timestamp=active_position.signal.confirmation_timestamp,
                        entry_timestamp=active_position.entry_timestamp,
                        entry_price=active_position.entry_price,
                        stop_price=active_position.stop_price,
                        target_price=active_position.target_price,
                        quantity=active_position.quantity,
                        risk_amount=active_position.risk_amount,
                        exit_timestamp=last_candle.timestamp,
                        exit_price=effective_exit,
                        exit_reason="END_OF_DATA",
                        gross_pnl=gross_pnl,
                        fees=total_fees,
                        slippage=total_slippage,
                        net_pnl=net_pnl,
                        r_multiple=r_multiple,
                        equity_before=equity_before,
                        equity_after=equity,
                    )
                )

            active_position = None

            # Final drawdown check
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            dd_pct = dd / peak_equity if peak_equity > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

        # -----------------------------------------------------------------
        # STEP 5: Metric Compilation
        # -----------------------------------------------------------------
        num_trades = len(completed_trades)
        winning_trades = sum(1 for t in completed_trades if t.net_pnl > 0)
        losing_trades = sum(1 for t in completed_trades if t.net_pnl < 0)
        win_rate = winning_trades / num_trades if num_trades > 0 else 0.0

        gross_profit = sum(t.net_pnl for t in completed_trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in completed_trades if t.net_pnl < 0))

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        total_net_pnl = equity - self.config.initial_equity
        total_return_pct = total_net_pnl / self.config.initial_equity
        avg_trade_pnl = total_net_pnl / num_trades if num_trades > 0 else 0.0

        return BacktestResult(
            strategy_version=self.strategy.VERSION,
            dataset_start=candles[0].timestamp if candles else None,
            dataset_end=candles[-1].timestamp if candles else None,
            initial_equity=self.config.initial_equity,
            final_equity=equity,
            total_net_pnl=total_net_pnl,
            total_return_pct=total_return_pct,
            number_of_trades=num_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            average_trade_pnl=avg_trade_pnl,
            trades=completed_trades,
            rejections=rejections,
        )
