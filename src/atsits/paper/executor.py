"""Paper Execution Engine managing pending setups, next-open entries, and intrabar SL/TP triggers."""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from atsits.journal.models import (
    EntryRecord,
    ExitRecord,
    MarketObservationRecord,
    SetupDetectedRecord,
    SetupRejectedRecord,
    TradeRecord,
)
from atsits.journal.storage import TradingJournal
from atsits.market.normalizer import NormalizedKline
from atsits.models.market_data import Candle
from atsits.paper.account import PaperAccount
from atsits.paper.models import PaperPosition
from atsits.strategies.ema_pullback import EMAPullbackStrategy, EntrySignal

logger = logging.getLogger(__name__)


class PaperExecutor:
    """Deterministic Paper Execution Engine.

    Coordinates signal receipt, next-open entry execution, forming-candle
    intrabar SL/TP monitoring, and factual journal logging under execution_mode="PAPER".
    """

    def __init__(
        self,
        account: PaperAccount,
        strategy: EMAPullbackStrategy,
        journal: Optional[TradingJournal] = None,
        run_id: str = "paper_run_001",
        record_observations: bool = True,
    ):
        self.account: PaperAccount = account
        self.strategy: EMAPullbackStrategy = strategy
        self.journal: Optional[TradingJournal] = journal
        self.run_id: str = run_id
        self.record_observations: bool = record_observations

        self.pending_signal: Optional[EntrySignal] = None
        self.completed_trades_history: List[Dict[str, Any]] = []
        self.rejections_history: List[Dict[str, Any]] = []

        self._trade_counter: int = 0
        self._rec_counter: int = 0

    def _make_rec_id(self, rtype: str) -> str:
        self._rec_counter += 1
        return f"{self.run_id}_{rtype.lower()}_{self._rec_counter:05d}"

    def on_tick(self, kline: NormalizedKline) -> Optional[PaperPosition]:
        """Process real-time tick update from forming or completed kline.

        1. Evaluates pending entry if a signal is waiting and this kline represents the next bar.
        2. Evaluates intrabar high/low against stop loss and take profit for active positions.

        Args:
            kline: Normalized real-time kline.

        Returns:
            Active PaperPosition if one was just opened or remains active, otherwise None.
        """
        # -----------------------------------------------------------------
        # 1. Check Pending Signal Entry on Next Bar Open
        # -----------------------------------------------------------------
        candle = kline.candle
        if self.pending_signal is not None and not self.account.has_active_position:
            sig = self.pending_signal
            # Entry occurs on the bar immediately following the confirmation candle
            if candle.timestamp > sig.confirmation_timestamp:
                self.pending_signal = None
                open_price = candle.open
                bar_timestamp = candle.timestamp

                # Validate intended stop against open price
                is_invalid_stop = False
                if sig.direction == "LONG" and open_price <= sig.stop_price:
                    is_invalid_stop = True
                elif sig.direction == "SHORT" and open_price >= sig.stop_price:
                    is_invalid_stop = True

                if is_invalid_stop:
                    rejection_detail = {
                        "open_price": open_price,
                        "stop_price": sig.stop_price,
                    }
                    self.rejections_history.append(
                        {
                            "timestamp": bar_timestamp,
                            "symbol": candle.symbol,
                            "direction": sig.direction,
                            "reason": "INVALID_STOP_AT_OPEN",
                            "details": rejection_detail,
                        }
                    )
                    logger.warning(
                        f"Paper entry rejected for {sig.direction} on {candle.symbol} @ {open_price}: invalid stop {sig.stop_price}"
                    )

                    if self.journal is not None:
                        self.journal.append(
                            SetupRejectedRecord(
                                record_id=self._make_rec_id("setup_rej"),
                                timestamp=bar_timestamp,
                                run_id=self.run_id,
                                strategy_version=self.strategy.VERSION,
                                execution_mode="PAPER",
                                symbol=candle.symbol,
                                timeframe=candle.timeframe,
                                direction=sig.direction,
                                reason="INVALID_STOP_AT_OPEN",
                                details=rejection_detail,
                            )
                        )
                else:
                    self._trade_counter += 1
                    trade_id = f"paper-trd-{self._trade_counter:04d}"

                    pos = self.account.open_position(
                        trade_id=trade_id,
                        strategy_version=self.strategy.VERSION,
                        symbol=candle.symbol,
                        timeframe=candle.timeframe,
                        direction=sig.direction,
                        pullback_timestamp=sig.pullback_timestamp,
                        confirmation_timestamp=sig.confirmation_timestamp,
                        entry_timestamp=bar_timestamp,
                        open_price=open_price,
                        stop_price=sig.stop_price,
                        take_profit_rr=getattr(self.strategy, "take_profit_rr", 2.0),
                    )

                    logger.info(
                        f"Paper position opened: {pos.trade_id} {pos.direction} {pos.quantity:.4f} {pos.symbol} "
                        f"@ {pos.entry_price:.2f} (SL: {pos.stop_price:.2f}, TP: {pos.target_price:.2f})"
                    )

                    if self.journal is not None:
                        self.journal.append(
                            EntryRecord(
                                record_id=self._make_rec_id("entry"),
                                trade_id=pos.trade_id,
                                timestamp=bar_timestamp,
                                run_id=self.run_id,
                                strategy_version=self.strategy.VERSION,
                                execution_mode="PAPER",
                                symbol=pos.symbol,
                                timeframe=pos.timeframe,
                                direction=pos.direction,
                                price=pos.entry_price,
                                raw_price=pos.raw_entry_price,
                                quantity=pos.quantity,
                                stop_price=pos.stop_price,
                                target_price=pos.target_price,
                                risk_amount=pos.risk_amount,
                                equity_before=pos.equity_before,
                                fees=pos.entry_fee,
                                slippage=pos.entry_slippage,
                            )
                        )

        # -----------------------------------------------------------------
        # 2. Intrabar SL/TP Evaluation for Active Position
        # -----------------------------------------------------------------
        if self.account.has_active_position:
            pos = self.account.active_position
            assert pos is not None

            exit_triggered = False
            exit_reason = ""
            raw_exit_price = 0.0

            if pos.direction == "LONG":
                sl_hit = candle.low <= pos.stop_price
                tp_hit = candle.high >= pos.target_price

                if sl_hit and tp_hit:
                    # Same-bar ambiguity resolution: SL takes precedence
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                    raw_exit_price = pos.stop_price
                elif sl_hit:
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                    raw_exit_price = pos.stop_price
                elif tp_hit:
                    exit_triggered = True
                    exit_reason = "TP_HIT"
                    raw_exit_price = pos.target_price

            elif pos.direction == "SHORT":
                sl_hit = candle.high >= pos.stop_price
                tp_hit = candle.low <= pos.target_price

                if sl_hit and tp_hit:
                    # Same-bar ambiguity resolution: SL takes precedence
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                    raw_exit_price = pos.stop_price
                elif sl_hit:
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                    raw_exit_price = pos.stop_price
                elif tp_hit:
                    exit_triggered = True
                    exit_reason = "TP_HIT"
                    raw_exit_price = pos.target_price

            if exit_triggered:
                trade_res = self.account.close_position(
                    raw_exit_price=raw_exit_price,
                    exit_reason=exit_reason,
                )
                self.completed_trades_history.append(trade_res)

                exit_ts = kline.close_time or candle.timestamp

                logger.info(
                    f"Paper position closed: {pos.trade_id} {pos.direction} Reason={exit_reason} "
                    f"ExitPrice={trade_res['effective_exit_price']:.2f} NetPnL={trade_res['net_pnl']:.2f} "
                    f"R={trade_res['r_multiple']:.2f}R EquityAfter={trade_res['equity_after']:.2f}"
                )

                if self.journal is not None:
                    self.journal.append(
                        ExitRecord(
                            record_id=self._make_rec_id("exit"),
                            trade_id=pos.trade_id,
                            timestamp=exit_ts,
                            run_id=self.run_id,
                            strategy_version=self.strategy.VERSION,
                            execution_mode="PAPER",
                            symbol=pos.symbol,
                            timeframe=pos.timeframe,
                            direction=pos.direction,
                            exit_price=trade_res["effective_exit_price"],
                            raw_exit_price=trade_res["raw_exit_price"],
                            exit_reason=exit_reason,
                            quantity=pos.quantity,
                            gross_pnl=trade_res["gross_pnl"],
                            fees=trade_res["fees"],
                            slippage=trade_res["slippage"],
                            net_pnl=trade_res["net_pnl"],
                            equity_after=trade_res["equity_after"],
                        )
                    )
                    self.journal.append(
                        TradeRecord(
                            record_id=self._make_rec_id("trade"),
                            trade_id=pos.trade_id,
                            timestamp=exit_ts,
                            run_id=self.run_id,
                            strategy_version=self.strategy.VERSION,
                            execution_mode="PAPER",
                            symbol=pos.symbol,
                            timeframe=pos.timeframe,
                            direction=pos.direction,
                            pullback_timestamp=pos.pullback_timestamp,
                            confirmation_timestamp=pos.confirmation_timestamp,
                            entry_timestamp=pos.entry_timestamp,
                            entry_price=pos.entry_price,
                            stop_price=pos.stop_price,
                            target_price=pos.target_price,
                            quantity=pos.quantity,
                            risk_amount=pos.risk_amount,
                            exit_timestamp=exit_ts,
                            exit_price=trade_res["effective_exit_price"],
                            exit_reason=exit_reason,
                            gross_pnl=trade_res["gross_pnl"],
                            fees=trade_res["fees"],
                            slippage=trade_res["slippage"],
                            net_pnl=trade_res["net_pnl"],
                            r_multiple=trade_res["r_multiple"],
                            equity_before=trade_res["equity_before"],
                            equity_after=trade_res["equity_after"],
                        )
                    )

        return self.account.active_position

    def on_candle_completed(self, candle: Candle, kline: NormalizedKline) -> Optional[EntrySignal]:
        """Process completed candle for strategy evaluation and observation recording.

        Args:
            candle: Completed OHLCV candle.
            kline: Normalized kline payload.

        Returns:
            EntrySignal if confirmed setup detected, otherwise None.
        """
        # Ensure forming evaluation had a chance to process the final tick
        self.on_tick(kline)

        # Evaluate strategy on completed candle
        has_pos = self.account.has_active_position
        signal = self.strategy.on_candle(candle, has_open_position=has_pos)

        if signal is not None and not has_pos:
            self.pending_signal = signal
            logger.info(
                f"Confirmed paper setup detected: {signal.direction} on {candle.symbol} @ {candle.timestamp.isoformat()} (SL: {signal.stop_price})"
            )

            if self.journal is not None:
                ema20_val = self.strategy.fast_ema.value or 0.0
                ema50_val = self.strategy.slow_ema.value or 0.0
                self.journal.append(
                    SetupDetectedRecord(
                        record_id=self._make_rec_id("setup"),
                        timestamp=candle.timestamp,
                        run_id=self.run_id,
                        strategy_version=self.strategy.VERSION,
                        execution_mode="PAPER",
                        symbol=candle.symbol,
                        timeframe=candle.timeframe,
                        direction=signal.direction,
                        pullback_timestamp=signal.pullback_timestamp,
                        pullback_high=signal.pullback_high,
                        pullback_low=signal.pullback_low,
                        confirmation_timestamp=signal.confirmation_timestamp,
                        ema20=ema20_val,
                        ema50=ema50_val,
                        facts={"stop_price": signal.stop_price},
                    )
                )

        # Record market observation
        if self.journal is not None and self.record_observations:
            ema20_val = self.strategy.fast_ema.value
            ema50_val = self.strategy.slow_ema.value
            trend_str = None
            if ema20_val is not None and ema50_val is not None:
                trend_str = "UPTREND" if ema20_val > ema50_val else ("DOWNTREND" if ema20_val < ema50_val else "FLAT")

            self.journal.append(
                MarketObservationRecord(
                    record_id=self._make_rec_id("obs"),
                    timestamp=candle.timestamp,
                    run_id=self.run_id,
                    strategy_version=self.strategy.VERSION,
                    execution_mode="PAPER",
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

        return signal
