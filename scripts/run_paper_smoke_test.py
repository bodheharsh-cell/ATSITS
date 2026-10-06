"""Smoke test for ATSITS Paper Trading Runtime against live public Binance stream."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from atsits.journal.storage import TradingJournal
from atsits.paper.runtime import PaperRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smoke_test")


def main() -> None:
    session_id = f"smoke_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    journal_path = Path("data/journal") / f"{session_id}.jsonl"
    journal = TradingJournal(file_path=journal_path)

    logger.info("Initializing PaperRuntime for BTCUSDT 1h...")
    runtime = PaperRuntime(
        symbol="BTCUSDT",
        interval="1h",
        session_id=session_id,
        initial_equity=10000.0,
        risk_pct=0.01,
        journal=journal,
    )

    # Bootstrap warmup from local CSV if available
    csv_path = Path("data/btcusdt_1h.csv")
    if csv_path.is_file():
        logger.info(f"Warming up indicators from {csv_path}...")
        runtime.warmup(csv_path=csv_path, limit=100)
    else:
        logger.info("Warming up indicators via public Binance REST...")
        runtime.warmup(use_public_rest=True, limit=100)

    logger.info(f"Strategy ready: {runtime.strategy.is_ready} (EMA20: {runtime.strategy.fast_ema.value:.2f}, EMA50: {runtime.strategy.slow_ema.value:.2f})")

    logger.info("Starting live public stream for 5 seconds...")
    runtime.start(in_background=True)

    time.sleep(5)

    logger.info("Stopping live paper runtime...")
    runtime.stop()

    summary = runtime.get_summary()
    logger.info("=" * 60)
    logger.info("SMOKE TEST COMPLETED SUCCESSFULLY")
    logger.info(f"Session: {summary['session_id']}")
    logger.info(f"Equity: ${summary['equity']:.2f} | Balance: ${summary['cash_balance']:.2f}")
    logger.info(f"Observer Completed Candles: {summary['observer_completed_candles']}")
    logger.info(f"Journal Entries Recorded: {journal.count()}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
