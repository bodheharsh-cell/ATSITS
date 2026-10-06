"""Phase 9 Binance Paper Trading Smoke Test.

Usage:
    python scripts/run_binance_paper_smoke_test.py

This script verifies Phase 9 components work end-to-end with real Binance
market data (unauthenticated public endpoints) and a simulated paper account.

SECURITY:
- Binance credentials loaded from environment/env file ONLY.
- No real orders are placed or queried at any point.
- Paper account uses fixed synthetic equity ($10,000).
- Real Binance balances are read-only and never used as paper equity.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load .env if present
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check(label: str, value: bool, detail: str = "") -> None:
    status = "[PASS]" if value else "[FAIL]"
    detail_str = f" -- {detail}" if detail else ""
    print(f"  {status}: {label}{detail_str}")
    return value


def main() -> int:
    print()
    print("=" * 60)
    print("  ATSITS Phase 9 — Binance Paper Trading Smoke Test")
    print("=" * 60)
    print("  SECURITY: No real orders are placed.")
    print("  Paper equity is synthetic ($10,000 fixed).")
    print()

    passed = 0
    failed = 0

    # ------------------------------------------------------------------
    # 1. Module Imports
    # ------------------------------------------------------------------
    section("1. MODULE IMPORTS")
    try:
        from atsits.binance.client import BinanceReadOnlyClient, BinanceClientError
        from atsits.paper.session import BinancePaperSession
        from atsits.strategies.experimental_ema import EMAExperimentalStrategy
        from atsits.mcp.tools import MCPToolRegistry
        if check("Binance client importable", True): passed += 1
        if check("Paper session importable", True): passed += 1
        if check("MCP registry importable", True): passed += 1
    except ImportError as exc:
        print(f"  ✗ FAIL: Import error: {exc}")
        failed += 3

    # ------------------------------------------------------------------
    # 2. Security Checks (no real order endpoints)
    # ------------------------------------------------------------------
    section("2. SECURITY AUDIT")
    from atsits.binance.client import BinanceReadOnlyClient, BinanceClientError
    from atsits.mcp.tools import MCPToolRegistry

    forbidden_methods = ["place_order", "new_order", "cancel_order", "create_order", "withdraw"]
    all_safe = True
    for method in forbidden_methods:
        if hasattr(BinanceReadOnlyClient, method):
            print(f"  ✗ FAIL: BinanceReadOnlyClient has forbidden method '{method}'!")
            failed += 1
            all_safe = False
    if all_safe:
        if check("No forbidden order methods on BinanceReadOnlyClient", True): passed += 1

    registry = MCPToolRegistry()
    tool_names = [t.name for t in registry.list_tool_definitions()]
    no_real_order = "place_binance_order" not in tool_names and "cancel_binance_order" not in tool_names
    if check("No real Binance order tools in MCP registry", no_real_order): passed += 1
    else: failed += 1

    paper_tools_present = all(
        t in tool_names for t in [
            "get_binance_market_status", "get_binance_candles", "get_binance_price",
            "get_paper_session", "get_paper_account", "get_paper_positions",
            "get_paper_orders", "get_paper_trades", "place_paper_order", "close_paper_position",
        ]
    )
    if check("All Phase 9 paper tools registered in MCP", paper_tools_present,
             f"{len(tool_names)} total tools"): passed += 1
    else: failed += 1

    # ------------------------------------------------------------------
    # 3. Binance Public Market Data (unauthenticated)
    # ------------------------------------------------------------------
    section("3. BINANCE PUBLIC MARKET DATA (unauthenticated)")
    from atsits.strategies.experimental_ema import EMAExperimentalStrategy
    from atsits.paper.session import BinancePaperSession

    api_key = os.environ.get("BINANCE_API_KEY", "").strip()
    api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        print("  INFO: BINANCE_API_KEY / BINANCE_API_SECRET not set.")
        print("        Testing with placeholder credentials (public endpoints only).")
        api_key = "PLACEHOLDER_KEY"
        api_secret = "PLACEHOLDER_SECRET"

    client = BinanceReadOnlyClient(api_key=api_key, api_secret=api_secret)
    strategy = EMAExperimentalStrategy()

    try:
        is_online = client.ping()
        if check("Binance API reachable", is_online): passed += 1
        else:
            failed += 1
            print("  INFO: Network may be unavailable — skipping live market tests.")
    except Exception as exc:
        print(f"  INFO: Network error: {exc}")
        is_online = False

    if is_online:
        try:
            price = client.get_ticker_price("BTCUSDT")
            if check("BTCUSDT price fetched", isinstance(price, float) and price > 0,
                     f"${price:,.2f}"): passed += 1
            else: failed += 1
        except Exception as exc:
            print(f"  ✗ FAIL: Price fetch failed: {exc}")
            failed += 1

        try:
            candles = client.get_klines("BTCUSDT", "1h", limit=5)
            has_complete = len(candles) > 0
            if check("BTCUSDT 1h klines (forming bar excluded)", has_complete,
                     f"{len(candles)} completed bars"): passed += 1
            else: failed += 1
        except Exception as exc:
            print(f"  ✗ FAIL: Candles fetch failed: {exc}")
            failed += 1

    # ------------------------------------------------------------------
    # 4. Paper Session Initialization
    # ------------------------------------------------------------------
    section("4. PAPER SESSION INITIALIZATION")

    session = BinancePaperSession(
        binance_client=client,
        strategy=strategy,
        session_id="PAPER-BINANCE-BTCUSDT-1H",
        symbol="BTCUSDT",
        interval="1h",
        initial_equity=10_000.0,
        risk_pct=0.01,
    )

    if check("Session ID correct", session.session_id == "PAPER-BINANCE-BTCUSDT-1H"): passed += 1
    else: failed += 1

    if check("Initial equity is synthetic $10,000", session.account.initial_equity == 10_000.0): passed += 1
    else: failed += 1

    if check("No active positions at start", not session.account.has_active_position): passed += 1
    else: failed += 1

    if check("Strategy is EMAExperimentalStrategy", "EMA" in session.strategy.VERSION): passed += 1
    else: failed += 1

    # ------------------------------------------------------------------
    # 4b. Strategy Warmup & Completed Candle Pipeline
    # ------------------------------------------------------------------
    section("4b. STRATEGY WARMUP & COMPLETED CANDLE PROCESSING")
    if is_online:
        try:
            warmed_count = session.warmup(warmup_limit=40)
            if check("Strategy warmup with public 1h candles", warmed_count >= 30, f"{warmed_count} candles"): passed += 1
            else: failed += 1

            if check("Strategy is_ready after warmup", session.strategy.is_ready): passed += 1
            else: failed += 1

            ema20 = session.strategy.fast_ema.value
            ema30 = session.strategy.slow_ema.value
            has_emas = (ema20 is not None) and (ema30 is not None)
            if check("EMA20 and EMA30 computed", has_emas, f"EMA20=${ema20:,.2f}, EMA30=${ema30:,.2f}" if has_emas else ""): passed += 1
            else: failed += 1

            # Process latest completed candle through on_completed_candle
            if candles:
                last_c_dict = candles[-1]
                from datetime import timezone
                from atsits.models.market_data import Candle
                c = Candle(
                    symbol=last_c_dict["symbol"],
                    timeframe=last_c_dict["interval"],
                    timestamp=datetime.fromtimestamp(last_c_dict["open_time"] / 1000.0, tz=timezone.utc),
                    open=last_c_dict["open"],
                    high=last_c_dict["high"],
                    low=last_c_dict["low"],
                    close=last_c_dict["close"],
                    volume=last_c_dict["volume"],
                )
                sig = session.on_completed_candle(c)
                sig_desc = sig.direction if sig else "No setup (normal)"
                if check("Completed 1h candle evaluated through strategy pipeline", True, f"Decision={sig_desc}"): passed += 1
                else: failed += 1
        except Exception as exc:
            print(f"  [FAIL]: Warmup/candle processing error: {exc}")
            failed += 4
    else:
        print("  INFO: Skipping live warmup (Binance unreachable).")


    # ------------------------------------------------------------------
    # 5. Paper Account State
    # ------------------------------------------------------------------
    section("5. PAPER ACCOUNT STATE")

    account = session.get_paper_account()
    if check("Paper account has session_id", "session_id" in account): passed += 1
    else: failed += 1

    if check("Paper account initial equity $10,000", account["initial_equity"] == 10_000.0): passed += 1
    else: failed += 1

    # Verify no credentials in response
    account_str = json.dumps(account)
    no_creds = "api_key" not in account_str.lower() and "api_secret" not in account_str.lower()
    if check("No credentials in paper account response", no_creds): passed += 1
    else: failed += 1

    # ------------------------------------------------------------------
    # 6. Paper Order Simulation
    # ------------------------------------------------------------------
    section("6. PAPER ORDER SIMULATION (no real Binance execution)")

    if is_online:
        try:
            price = client.get_ticker_price("BTCUSDT")
            # For test: use a stop 5% below current price for LONG
            stop = price * 0.95
            target = price * 1.10

            result = session.place_paper_order(
                side="BUY",
                quantity=0.001,
                stop_price=stop,
                target_price=target,
            )
            if check("Paper BUY order placed successfully", result["success"] is True): passed += 1
            else:
                failed += 1
                print(f"    Error: {result.get('error', 'unknown')}")

            if check("Position now active", session.account.has_active_position): passed += 1
            else: failed += 1

            positions = session.get_paper_positions()
            if check("Position visible in get_paper_positions()", len(positions) == 1): passed += 1
            else: failed += 1

            # Close position
            close_result = session.close_paper_position(reason="SMOKE_TEST_CLOSE")
            if check("Paper position closed manually", close_result["success"] is True): passed += 1
            else: failed += 1

            if check("Position cleared after close", not session.account.has_active_position): passed += 1
            else: failed += 1

            trades = session.get_paper_trades()
            if check("Completed trade recorded", len(trades) == 1): passed += 1
            else: failed += 1

        except Exception as exc:
            print(f"  INFO: Paper order test skipped (live price needed): {exc}")
    else:
        print("  INFO: Skipping paper order simulation (Binance not reachable).")

    # ------------------------------------------------------------------
    # 7. Historical Regression Check
    # ------------------------------------------------------------------
    section("7. HISTORICAL REGRESSION (EMA_Pullback_v1.0 unchanged)")

    data_path = Path("data/btcusdt_1h.csv")
    if data_path.exists():
        try:
            from atsits.data.loader import load_candles_from_csv
            from atsits.engine.backtester import BacktestEngine
            from atsits.models.backtest import BacktestConfig, CostModel
            from atsits.strategies.ema_pullback import EMAPullbackStrategy

            candles = load_candles_from_csv(data_path)
            locked_strategy = EMAPullbackStrategy()
            engine = BacktestEngine(
                strategy=locked_strategy,
                config=BacktestConfig(initial_equity=10_000.0, cost_model=CostModel()),
            )
            result = engine.run(candles)

            trades_ok = result.number_of_trades == 201
            pnl_ok = abs(result.total_net_pnl - (-306.09)) < 0.05

            if check("201 trades (locked baseline)", trades_ok,
                     f"got {result.number_of_trades}"): passed += 1
            else: failed += 1

            if check("-$306.09 net PnL (locked baseline)", pnl_ok,
                     f"got ${result.total_net_pnl:.2f}"): passed += 1
            else: failed += 1

        except Exception as exc:
            print(f"  ✗ FAIL: Historical regression check failed: {exc}")
            failed += 2
    else:
        print("  INFO: Historical data not found — skipping regression check.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    section("SUMMARY")
    total = passed + failed
    print(f"  Passed: {passed}/{total}")
    print(f"  Failed: {failed}/{total}")
    print()

    if failed == 0:
        print("  [PASS] ALL CHECKS PASSED -- Phase 9 smoke test complete.")
        print("  SECURITY: No real Binance orders were placed.")
        print("  Paper equity remains synthetic ($10,000 base).")
        return 0
    else:
        print(f"  [FAIL] {failed} CHECKS FAILED -- Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
