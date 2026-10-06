"""Compare Baseline EMA20/50 + 2R vs Experimental EMA20/30 + 3R."""

from pathlib import Path
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from atsits.strategies.experimental_ema import EMAExperimentalStrategy


def main():
    data_path = Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv")
    candles = load_candles_from_csv(data_path)
    cfg = BacktestConfig(initial_equity=10000.0, cost_model=CostModel())

    # 1. Baseline
    base_engine = BacktestEngine(strategy=EMAPullbackStrategy(), config=cfg)
    base_res = base_engine.run(candles, run_id="baseline_run")

    # 2. Experimental
    exp_engine = BacktestEngine(strategy=EMAExperimentalStrategy(), config=cfg)
    exp_res = exp_engine.run(candles, run_id="experimental_run")

    base_longs = len([t for t in base_res.trades if t.direction == "LONG"])
    base_shorts = len([t for t in base_res.trades if t.direction == "SHORT"])
    base_tp = len([t for t in base_res.trades if t.exit_reason == "TP_HIT"])
    base_sl = len([t for t in base_res.trades if t.exit_reason == "SL_HIT"])
    base_eod = len([t for t in base_res.trades if t.exit_reason == "END_OF_DATA"])

    exp_longs = len([t for t in exp_res.trades if t.direction == "LONG"])
    exp_shorts = len([t for t in exp_res.trades if t.direction == "SHORT"])
    exp_tp = len([t for t in exp_res.trades if t.exit_reason == "TP_HIT"])
    exp_sl = len([t for t in exp_res.trades if t.exit_reason == "SL_HIT"])
    exp_eod = len([t for t in exp_res.trades if t.exit_reason == "END_OF_DATA"])

    print("==================================================")
    print("STRATEGY COMPARISON: LOCKED BASELINE vs EXPERIMENTAL")
    print("==================================================")
    print(f"Dataset: {data_path.name} | Candles: {len(candles):,} | Period: {candles[0].timestamp.isoformat()} to {candles[-1].timestamp.isoformat()}")
    print("")
    print("--- 1. LOCKED PRODUCTION BASELINE (EMA20/50 + 2R) ---")
    print(f"Strategy Version: {base_engine.strategy.VERSION}")
    print(f"Fast EMA:         {base_engine.strategy.fast_period}")
    print(f"Slow EMA:         {base_engine.strategy.slow_period}")
    print(f"Take Profit:      {base_engine.strategy.take_profit_rr}R")
    print(f"Total Trades:     {base_res.number_of_trades}")
    print(f"Long Trades:      {base_longs}")
    print(f"Short Trades:     {base_shorts}")
    print(f"Winning Trades:   {base_res.winning_trades}")
    print(f"Losing Trades:    {base_res.losing_trades}")
    print(f"Win Rate:         {base_res.win_rate * 100:.2f}%")
    print(f"Gross Profit:     ${base_res.gross_profit:,.2f}")
    print(f"Gross Loss:       ${base_res.gross_loss:,.2f}")
    print(f"Net PnL:          ${base_res.total_net_pnl:+,.2f} ({base_res.total_return_pct * 100:+.2f}%)")
    print(f"Profit Factor:    {base_res.profit_factor:.2f}")
    print(f"Max Drawdown:     ${base_res.max_drawdown:,.2f} ({base_res.max_drawdown_pct * 100:.2f}%)")
    print(f"Average Trade:    ${base_res.average_trade_pnl:+,.2f}")
    print(f"TP Exits:         {base_tp}")
    print(f"SL Exits:         {base_sl}")
    print(f"EOD Exits:        {base_eod}")
    print(f"Rejected Setups:  {len(base_res.rejections)}")
    print("")
    print("--- 2. EXPERIMENTAL STRATEGY (EMA20/30 + 3R) ---")
    print(f"Strategy Version: {exp_engine.strategy.VERSION}")
    print(f"Fast EMA:         {exp_engine.strategy.fast_period}")
    print(f"Slow EMA:         {exp_engine.strategy.slow_period}")
    print(f"Take Profit:      {exp_engine.strategy.take_profit_rr}R")
    print(f"Total Trades:     {exp_res.number_of_trades}")
    print(f"Long Trades:      {exp_longs}")
    print(f"Short Trades:     {exp_shorts}")
    print(f"Winning Trades:   {exp_res.winning_trades}")
    print(f"Losing Trades:    {exp_res.losing_trades}")
    print(f"Win Rate:         {exp_res.win_rate * 100:.2f}%")
    print(f"Gross Profit:     ${exp_res.gross_profit:,.2f}")
    print(f"Gross Loss:       ${exp_res.gross_loss:,.2f}")
    print(f"Net PnL:          ${exp_res.total_net_pnl:+,.2f} ({exp_res.total_return_pct * 100:+.2f}%)")
    print(f"Profit Factor:    {exp_res.profit_factor:.2f}")
    print(f"Max Drawdown:     ${exp_res.max_drawdown:,.2f} ({exp_res.max_drawdown_pct * 100:.2f}%)")
    print(f"Average Trade:    ${exp_res.average_trade_pnl:+,.2f}")
    print(f"TP Exits:         {exp_tp}")
    print(f"SL Exits:         {exp_sl}")
    print(f"EOD Exits:        {exp_eod}")
    print(f"Rejected Setups:  {len(exp_res.rejections)}")
    print("==================================================")


if __name__ == "__main__":
    main()
