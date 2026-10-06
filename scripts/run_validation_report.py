"""Phase 1A: Comprehensive historical data validation and backtest reporting script."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.models.backtest import BacktestConfig, BacktestResult, CostModel
from atsits.models.market_data import Candle
from atsits.strategies.ema_pullback import EMAPullbackStrategy


def audit_dataset(candles: List[Candle]) -> dict:
    """Perform data quality and gap analysis on the loaded candles."""
    total = len(candles)
    if total == 0:
        return {"error": "Empty dataset"}

    earliest = candles[0].timestamp
    latest = candles[-1].timestamp

    duplicates = 0
    out_of_order = 0
    ohlc_violations = 0
    missing_intervals: List[Tuple[datetime, datetime, int]] = []

    last_ts = None

    for i, c in enumerate(candles):
        # OHLC sanity
        if not (c.open > 0 and c.high >= c.open and c.high >= c.close and c.low <= c.open and c.low <= c.close and c.low <= c.high and c.volume >= 0):
            ohlc_violations += 1

        if last_ts is not None:
            if c.timestamp == last_ts:
                duplicates += 1
            elif c.timestamp < last_ts:
                out_of_order += 1
            else:
                diff = c.timestamp - last_ts
                expected = timedelta(hours=1)
                if diff > expected:
                    gap_hours = int(diff.total_seconds() // 3600) - 1
                    missing_intervals.append((last_ts, c.timestamp, gap_hours))

        last_ts = c.timestamp

    return {
        "total_candles": total,
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "timezone": str(earliest.tzinfo),
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "ohlc_violations": ohlc_violations,
        "missing_intervals_count": len(missing_intervals),
        "missing_intervals_details": missing_intervals,
    }


def run_validation():
    csv_path = Path("data/btcusdt_1h.csv")
    print("==================================================")
    print("PHASE 1A: HISTORICAL DATA VALIDATION REPORT")
    print("==================================================")

    # 1. Load data
    candles = load_candles_from_csv(csv_path, symbol="BTCUSDT", timeframe="1h")

    # 2. Data Audit
    audit = audit_dataset(candles)
    print("\n--- 1. DATASET SUMMARY & QUALITY AUDIT ---")
    print(f"Source: Binance Public Market Data (REST Kline API, unauthenticated)")
    print(f"Symbol: BTCUSDT | Timeframe: 1h")
    print(f"Period: {audit['earliest']} to {audit['latest']}")
    print(f"Total Candles: {audit['total_candles']}")
    print(f"Timezone: UTC ({audit['timezone']})")
    print(f"Duplicate Timestamps: {audit['duplicates']}")
    print(f"Out-of-Order Timestamps: {audit['out_of_order']}")
    print(f"OHLC Constraint Violations: {audit['ohlc_violations']}")
    print(f"Missing 1H Intervals: {audit['missing_intervals_count']}")
    if audit["missing_intervals_details"]:
        for prev_t, next_t, hrs in audit["missing_intervals_details"]:
            print(f"  Gap: {prev_t.isoformat()} -> {next_t.isoformat()} ({hrs} missing bars)")

    # 3. Backtest Execution
    cost_model = CostModel(commission_rate=0.0, slippage_points=0.0, slippage_pct=0.0)
    config = BacktestConfig(
        initial_equity=10000.0,
        risk_pct=0.01,
        max_open_positions=1,
        cost_model=cost_model,
    )
    strategy = EMAPullbackStrategy()
    engine = BacktestEngine(strategy=strategy, config=config)

    res_1 = engine.run(candles)

    # Determinism Verification: Run 2
    engine_2 = BacktestEngine(strategy=EMAPullbackStrategy(), config=config)
    res_2 = engine_2.run(candles)

    is_deterministic = (res_1.model_dump() == res_2.model_dump())

    print("\n--- 2. BACKTEST SUMMARY ---")
    print(f"Strategy: {res_1.strategy_version}")
    print(f"Initial Equity: ${res_1.initial_equity:,.2f}")
    print(f"Final Equity:   ${res_1.final_equity:,.2f}")
    print(f"Total Net P&L:  ${res_1.total_net_pnl:,.2f} ({res_1.total_return_pct * 100:.2f}%)")
    print(f"Total Trades:   {res_1.number_of_trades}")
    print(f"Winning Trades: {res_1.winning_trades} | Losing Trades: {res_1.losing_trades}")
    print(f"Win Rate:       {res_1.win_rate * 100:.2f}%")
    print(f"Gross Profit:   ${res_1.gross_profit:,.2f}")
    print(f"Gross Loss:     ${res_1.gross_loss:,.2f}")
    print(f"Profit Factor:  {res_1.profit_factor:.2f}")
    print(f"Max Drawdown:   ${res_1.max_drawdown:,.2f} ({res_1.max_drawdown_pct * 100:.2f}%)")
    print(f"Avg Trade P&L:  ${res_1.average_trade_pnl:,.2f}")
    print(f"Cost Model Note: Baseline costs set to 0.0 (unfunded placeholder mode).")

    # 4. Trade Distribution
    long_trades = [t for t in res_1.trades if t.direction == "LONG"]
    short_trades = [t for t in res_1.trades if t.direction == "SHORT"]
    tp_hits = [t for t in res_1.trades if t.exit_reason == "TP_HIT"]
    sl_hits = [t for t in res_1.trades if t.exit_reason == "SL_HIT"]
    eod_hits = [t for t in res_1.trades if t.exit_reason == "END_OF_DATA"]

    print("\n--- 3. TRADE DISTRIBUTION ---")
    print(f"LONG Trades:     {len(long_trades)}")
    print(f"SHORT Trades:    {len(short_trades)}")
    print(f"TP_HIT Exits:    {len(tp_hits)} ({len(tp_hits)/len(res_1.trades)*100:.1f}%)")
    print(f"SL_HIT Exits:    {len(sl_hits)} ({len(sl_hits)/len(res_1.trades)*100:.1f}%)")
    print(f"END_OF_DATA:     {len(eod_hits)}")
    print(f"Rejected Setups: {len(res_1.rejections)}")

    # 5. Temporal Sanity Checks
    print("\n--- 4. TEMPORAL SANITY CHECKS ---")
    if res_1.trades:
        earliest_trade = res_1.trades[0]
        latest_trade = res_1.trades[-1]
        print(f"Earliest Trade Entry: {earliest_trade.entry_timestamp.isoformat()}")
        print(f"Latest Trade Exit:    {latest_trade.exit_timestamp.isoformat()}")

        # Verify entry always after confirmation
        all_temporal_ok = True
        for t in res_1.trades:
            if not (t.pullback_timestamp < t.confirmation_timestamp < t.entry_timestamp <= t.exit_timestamp):
                all_temporal_ok = False
                print(f"Temporal violation on trade {t.trade_id}!")
                break
        print(f"Chronological Flow Verification (Pullback < Confirm < Entry <= Exit): {'PASSED (100% valid)' if all_temporal_ok else 'FAILED'}")

    # 6. Spot Checks (~10 diverse trades)
    print("\n--- 5. MANUAL TRADE SPOT CHECKS ---")
    spot_candidates = []
    # Find winning longs
    win_longs = [t for t in long_trades if t.net_pnl > 0]
    # Find losing longs
    loss_longs = [t for t in long_trades if t.net_pnl < 0]
    # Find winning shorts
    win_shorts = [t for t in short_trades if t.net_pnl > 0]
    # Find losing shorts
    loss_shorts = [t for t in short_trades if t.net_pnl < 0]

    # Select samples
    if win_longs:
        spot_candidates.extend(win_longs[:3])
    if loss_longs:
        spot_candidates.extend(loss_longs[:3])
    if win_shorts:
        spot_candidates.extend(win_shorts[:2])
    if loss_shorts:
        spot_candidates.extend(loss_shorts[:2])

    candle_by_ts = {c.timestamp: c for c in candles}

    for idx, trade in enumerate(spot_candidates, 1):
        pb_c = candle_by_ts.get(trade.pullback_timestamp)
        conf_c = candle_by_ts.get(trade.confirmation_timestamp)
        entry_c = candle_by_ts.get(trade.entry_timestamp)
        exit_c = candle_by_ts.get(trade.exit_timestamp)

        print(f"\n[Spot Check #{idx}: Trade {trade.trade_id} | {trade.direction} | {trade.exit_reason}]")
        print(f"  1. Pullback Candle:     {trade.pullback_timestamp.isoformat()} | O={pb_c.open} H={pb_c.high} L={pb_c.low} C={pb_c.close}")
        print(f"  2. Confirmation Candle: {trade.confirmation_timestamp.isoformat()} | O={conf_c.open} H={conf_c.high} L={conf_c.low} C={conf_c.close}")
        print(f"  3. Entry Candle:        {trade.entry_timestamp.isoformat()} | Open={entry_c.open}")
        print(f"  4. Execution Levels:    Entry={trade.entry_price:.2f} | Stop={trade.stop_price:.2f} | Target(2R)={trade.target_price:.2f}")
        print(f"  5. Position & Risk:     Quantity={trade.quantity:.4f} | RiskAmount=${trade.risk_amount:.2f}")
        print(f"  6. Exit Candle:         {trade.exit_timestamp.isoformat()} | O={exit_c.open} H={exit_c.high} L={exit_c.low} C={exit_c.close}")
        print(f"  7. Result:              ExitPrice={trade.exit_price:.2f} | NetPnL=${trade.net_pnl:.2f} | R-Multiple={trade.r_multiple:.2f}R")

    if res_1.rejections:
        print(f"\n[Spot Check Rejection: Total {len(res_1.rejections)} rejections found]")
        rej = res_1.rejections[0]
        print(f"  Timestamp: {rej.timestamp.isoformat()} | Direction: {rej.direction} | Reason: {rej.reason} | Details: {rej.details}")

    # 7. Determinism Result
    print("\n--- 6. DETERMINISM VERIFICATION ---")
    print(f"Identical Backtest Runs (Run 1 == Run 2): {'PASSED (Bit-for-bit identical)' if is_deterministic else 'FAILED'}")


if __name__ == "__main__":
    run_validation()
