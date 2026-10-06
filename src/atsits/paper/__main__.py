"""CLI entrypoint for running the ATSITS Paper Trading Engine."""

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import signal
import sys
import time
from atsits.journal.storage import TradingJournal
from atsits.paper.runtime import PaperRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("atsits.paper")


def main() -> None:
    """Run paper trading session with CLI parameters."""
    parser = argparse.ArgumentParser(description="ATSITS Paper Trading Engine")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading symbol (default: BTCUSDT)")
    parser.add_argument("--interval", default="1h", help="Kline interval (default: 1h)")
    parser.add_argument("--equity", type=float, default=10000.0, help="Initial paper starting equity")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk percentage per trade (default: 0.01)")
    parser.add_argument("--warmup-csv", type=str, default=None, help="Path to CSV for indicator warmup")
    parser.add_argument("--warmup-rest", action="store_true", help="Fetch 100 historical klines from public Binance REST")
    parser.add_argument("--journal-dir", type=str, default="data/journal", help="Journal storage directory")
    args = parser.parse_args()

    session_id = f"paper_{args.symbol.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    journal_path = Path(args.journal_dir) / f"{session_id}.jsonl"
    journal = TradingJournal(file_path=journal_path)

    logger.info("=" * 60)
    logger.info(f"Starting ATSITS Paper Trading Session: {session_id}")
    logger.info(f"Symbol: {args.symbol} | Interval: {args.interval} | Capital: ${args.equity:.2f} | Risk: {args.risk * 100:.1f}%")
    logger.info(f"Journal File: {journal_path}")
    logger.info("=" * 60)

    runtime = PaperRuntime(
        symbol=args.symbol,
        interval=args.interval,
        session_id=session_id,
        initial_equity=args.equity,
        risk_pct=args.risk,
        journal=journal,
    )

    # Warmup
    if args.warmup_csv:
        logger.info(f"Warming up indicators from CSV: {args.warmup_csv}")
        runtime.warmup(csv_path=args.warmup_csv)
    elif args.warmup_rest:
        logger.info("Warming up indicators from public Binance REST API...")
        runtime.warmup(use_public_rest=True)
    else:
        # Check if data/btcusdt_1h.csv exists
        default_csv = Path("data/btcusdt_1h.csv")
        if default_csv.is_file():
            logger.info(f"Warming up indicators from default historical CSV: {default_csv}")
            runtime.warmup(csv_path=default_csv)

    # Signal handlers for clean shutdown
    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received. Terminating paper session...")
        runtime.stop()
        summary = runtime.get_summary()
        logger.info("=" * 60)
        logger.info("ATSITS PAPER TRADING SESSION SUMMARY")
        logger.info(f"Session: {summary['session_id']}")
        logger.info(f"Final Balance: ${summary['cash_balance']:.2f} | Equity: ${summary['equity']:.2f}")
        logger.info(f"Realized PnL: ${summary['realized_pnl']:.2f} | Total Trades: {summary['trade_count']}")
        logger.info(f"Total Fees: ${summary['total_fees']:.2f} | Total Slippage: ${summary['total_slippage']:.2f}")
        logger.info(f"Observer Completed Candles: {summary['observer_completed_candles']}")
        logger.info("=" * 60)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    runtime.start(in_background=True)
    logger.info("Paper trading runtime is now active. Monitoring live Binance market feed (Ctrl+C to stop)...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_handler(None, None)


if __name__ == "__main__":
    main()
