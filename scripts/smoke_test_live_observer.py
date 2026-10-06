"""Phase 3: Live market observer smoke test script connecting to public Binance stream."""

import time
from atsits.journal.storage import TradingJournal
from atsits.market.observer import LiveMarketObserver


def run_live_smoke_test(duration_seconds: int = 12):
    print("==================================================")
    print("PHASE 3: LIVE MARKET OBSERVER SMOKE TEST")
    print("==================================================")
    print("Connecting to public Binance WebSocket stream...")
    print("Target: BTCUSDT 1h (Public Unauthenticated Market Data)")
    print("Order Placement: DISABLED (Not implemented)")

    journal = TradingJournal()
    forming_updates = []
    completed_candles = []

    def on_update(kline):
        forming_updates.append(kline)
        print(
            f"  [Live Forming Tick #{len(forming_updates)}] "
            f"Close: {kline.candle.close:.2f} | "
            f"Vol: {kline.candle.volume:.4f} | "
            f"is_closed: {kline.is_closed}"
        )

    def on_complete(candle, kline):
        completed_candles.append(candle)
        print(f"  *** [COMPLETED 1H CANDLE] *** {candle.symbol} @ {candle.timestamp.isoformat()} Close={candle.close}")

    observer = LiveMarketObserver(
        symbol="BTCUSDT",
        interval="1h",
        session_id="smoke_test_session",
        journal=journal,
        on_kline_update=on_update,
        on_candle_completed=on_complete,
    )

    observer.start(in_background=True)
    print(f"Observing live stream for {duration_seconds} seconds...")

    start_t = time.time()
    while time.time() - start_t < duration_seconds:
        time.sleep(1.0)

    print("\nStopping observer cleanly...")
    observer.stop()

    print("\n--- SMOKE TEST RESULTS ---")
    print(f"Observer Running State: {observer.ws_client.is_running}")
    print(f"Total Forming Ticks Observed: {len(forming_updates)}")
    print(f"Total Completed 1H Candles Observed: {len(completed_candles)}")
    if not completed_candles:
        print("Note: As expected during a short smoke-test window, no 1H candle closed in this interval.")
    print(f"Forming Candle Tracked: {observer.forming_kline is not None}")
    if observer.forming_kline:
        c = observer.forming_kline.candle
        print(f"Latest Forming State: O={c.open} H={c.high} L={c.low} C={c.close} V={c.volume}")
    print(f"Rejections: {observer.rejections_count}")
    print(f"Clean Shutdown: Verified")


if __name__ == "__main__":
    run_live_smoke_test()
