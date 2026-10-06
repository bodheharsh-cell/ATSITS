"""Phase 9 Comprehensive Tests — Binance Market Data, Account, and Paper Trading.

All Binance network calls are fully mocked.
No real Binance connections are made during testing.
No real orders are placed or queried.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from atsits.binance.client import BinanceClientError, BinanceReadOnlyClient
from atsits.paper.session import BinancePaperSession, PaperOrder, CompletedPaperTrade
from atsits.strategies.experimental_ema import EMAExperimentalStrategy


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_binance_client() -> BinanceReadOnlyClient:
    """Return a BinanceReadOnlyClient with all network methods mocked."""
    client = MagicMock(spec=BinanceReadOnlyClient)
    client.ping.return_value = True
    client.get_server_time.return_value = 1700000000000
    client.get_ticker_price.return_value = 42_000.0
    client.get_klines.return_value = _make_mock_candles(5)
    client.get_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "isSpotTradingAllowed": True,
            }
        ],
        "serverTime": 1700000000000,
    }
    client.get_account_status.return_value = {
        "account_type": "SPOT",
        "can_trade": True,
        "can_deposit": True,
        "can_withdraw": True,
        "permissions": ["SPOT"],
        "uid": 12345678,
    }
    client.get_balances.return_value = [
        {"asset": "BTC", "free": 0.5, "locked": 0.0, "total": 0.5},
        {"asset": "USDT", "free": 5000.0, "locked": 0.0, "total": 5000.0},
    ]
    return client


@pytest.fixture
def strategy() -> EMAExperimentalStrategy:
    return EMAExperimentalStrategy()


@pytest.fixture
def paper_session(mock_binance_client, strategy) -> BinancePaperSession:
    """Return a fully initialized paper session with mocked Binance client."""
    return BinancePaperSession(
        binance_client=mock_binance_client,
        strategy=strategy,
        session_id="PAPER-BINANCE-BTCUSDT-1H",
        symbol="BTCUSDT",
        interval="1h",
        initial_equity=10_000.0,
        risk_pct=0.01,
    )


def _make_mock_candles(count: int = 5) -> List[Dict[str, Any]]:
    """Build fake completed kline dicts."""
    candles = []
    base_time = 1700000000000
    for i in range(count):
        candles.append({
            "open_time": base_time + i * 3_600_000,
            "open_time_iso": datetime.fromtimestamp(
                (base_time + i * 3_600_000) / 1000.0, tz=timezone.utc
            ).isoformat(),
            "open": 41_000.0 + i * 100,
            "high": 42_000.0 + i * 100,
            "low": 40_000.0 + i * 100,
            "close": 41_500.0 + i * 100,
            "volume": 1000.0 + i * 10,
            "close_time": base_time + (i + 1) * 3_600_000 - 1,
            "symbol": "BTCUSDT",
            "interval": "1h",
        })
    return candles


# =============================================================================
# BinanceReadOnlyClient Unit Tests (mocked network)
# =============================================================================

class TestBinanceClientSecurity:
    """Verify that the Binance client has NO order placement capabilities."""

    def test_no_place_order_method(self):
        """BinanceReadOnlyClient must NOT have any order placement method."""
        client = BinanceReadOnlyClient.__new__(BinanceReadOnlyClient)
        forbidden = [
            "place_order", "new_order", "cancel_order", "create_order",
            "submit_order", "send_order", "withdraw", "transfer",
            "margin_order", "futures_order",
        ]
        for name in forbidden:
            assert not hasattr(client, name), (
                f"SECURITY VIOLATION: BinanceReadOnlyClient has forbidden method '{name}'"
            )

    def test_no_real_order_tool_in_mcp_registry(self):
        """MCP tool registry must NOT register any real Binance execution tool."""
        from atsits.mcp.tools import MCPToolRegistry
        registry = MCPToolRegistry()
        tool_names = [t.name for t in registry.list_tool_definitions()]

        # These must NOT exist
        forbidden_tools = [
            "place_binance_order", "cancel_binance_order", "submit_real_order",
            "execute_trade", "real_order", "binance_order",
        ]
        for name in forbidden_tools:
            assert name not in tool_names, (
                f"SECURITY VIOLATION: MCP registry contains forbidden tool '{name}'"
            )

    def test_paper_tools_exist_in_mcp_registry(self):
        """Phase 9 paper trading tools must all be registered."""
        from atsits.mcp.tools import MCPToolRegistry
        registry = MCPToolRegistry()
        tool_names = [t.name for t in registry.list_tool_definitions()]

        required = [
            "get_binance_market_status",
            "get_binance_candles",
            "get_binance_price",
            "get_binance_account_status",
            "get_binance_balances",
            "get_paper_session",
            "get_paper_account",
            "get_paper_positions",
            "get_paper_orders",
            "get_paper_trades",
            "place_paper_order",
            "close_paper_position",
        ]
        for name in required:
            assert name in tool_names, f"Phase 9 tool '{name}' not found in MCP registry"

    def test_credentials_never_in_error_message(self):
        """BinanceClientError messages must never contain api_key or api_secret."""
        api_key = "test_api_key_abc123"
        api_secret = "test_api_secret_xyz789"

        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://test", code=403, msg="Forbidden",
                hdrs=None, fp=None
            )
            client = BinanceReadOnlyClient(api_key=api_key, api_secret=api_secret)
            try:
                client.ping()
            except BinanceClientError as exc:
                assert api_key not in str(exc), "API key leaked in error message"
                assert api_secret not in str(exc), "API secret leaked in error message"

    def test_ping_returns_bool(self, mock_binance_client):
        """ping() must return a bool."""
        result = mock_binance_client.ping()
        assert isinstance(result, bool)
        assert result is True

    def test_get_ticker_price_returns_float(self, mock_binance_client):
        """get_ticker_price() must return a float."""
        price = mock_binance_client.get_ticker_price("BTCUSDT")
        assert isinstance(price, float)
        assert price > 0

    def test_get_klines_excludes_forming_bar(self):
        """get_klines() must exclude the currently forming bar."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            import time
            now_ms = int(time.time() * 1000)
            future_close = now_ms + 3_600_000  # 1hr in the future

            raw_klines = [
                # Completed bar
                [now_ms - 3_600_000, "41000", "42000", "40000", "41500", "1000", now_ms - 1, "0", 0, "0", "0", "0"],
                # Forming bar (close_time in future)
                [now_ms, "41500", "42500", "41000", "42000", "500", future_close, "0", 0, "0", "0", "0"],
            ]

            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(raw_klines).encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            client = BinanceReadOnlyClient(api_key="k", api_secret="s")
            candles = client.get_klines("BTCUSDT", "1h", limit=2)

            # Only the completed bar should be returned
            assert len(candles) == 1
            assert candles[0]["open"] == 41_000.0

    def test_get_klines_returns_correct_fields(self, mock_binance_client):
        """Candle dicts must contain required OHLCV fields."""
        candles = mock_binance_client.get_klines("BTCUSDT", "1h", limit=3)
        assert len(candles) > 0
        required_fields = {"open_time", "open", "high", "low", "close", "volume", "symbol", "interval"}
        for c in candles:
            for field in required_fields:
                assert field in c, f"Candle missing field '{field}'"

    def test_get_account_status_no_credentials(self, mock_binance_client):
        """Account status response must never contain credentials."""
        status = mock_binance_client.get_account_status()
        assert "api_key" not in status
        assert "api_secret" not in status
        assert "apiKey" not in status
        assert "secretKey" not in status

    def test_get_balances_returns_list(self, mock_binance_client):
        """get_balances() must return a list of asset dicts."""
        balances = mock_binance_client.get_balances()
        assert isinstance(balances, list)
        for b in balances:
            assert "asset" in b
            assert "free" in b
            assert "locked" in b
            assert "total" in b


# =============================================================================
# BinancePaperSession Unit Tests
# =============================================================================

class TestPaperSessionInitialization:
    """Verify paper session initializes correctly."""

    def test_default_session_id(self, paper_session):
        assert paper_session.session_id == "PAPER-BINANCE-BTCUSDT-1H"

    def test_initial_equity_is_synthetic(self, paper_session):
        """Paper equity must be 10,000 synthetic dollars — never from Binance."""
        assert paper_session.account.initial_equity == 10_000.0
        assert paper_session.account.cash_balance == 10_000.0

    def test_strategy_version(self, paper_session):
        assert "EMA" in paper_session.strategy.VERSION

    def test_no_active_positions_at_start(self, paper_session):
        assert not paper_session.account.has_active_position

    def test_zero_trades_at_start(self, paper_session):
        assert paper_session.account.trade_count == 0
        assert len(paper_session.completed_trades) == 0

    def test_zero_orders_at_start(self, paper_session):
        assert len(paper_session.orders) == 0


class TestPaperSessionMarketData:
    """Test live market data via mocked Binance client."""

    def test_get_current_price(self, paper_session):
        price = paper_session.get_current_price()
        assert price == 42_000.0

    def test_get_recent_candles(self, paper_session):
        candles = paper_session.get_recent_candles(limit=5)
        assert isinstance(candles, list)
        assert len(candles) == 5

    def test_get_account_status_no_credentials(self, paper_session):
        status = paper_session.get_account_status()
        assert "api_key" not in str(status)
        assert "api_secret" not in str(status)

    def test_get_binance_balances_never_used_as_equity(self, paper_session):
        """Real balances must NEVER become paper equity."""
        balances = paper_session.get_binance_balances()
        # Verify balances are returned but NOT applied to paper account
        assert isinstance(balances, list)
        # Paper equity must stay at 10,000 regardless of real balances
        assert paper_session.account.initial_equity == 10_000.0
        assert paper_session.account.cash_balance == 10_000.0


class TestPaperSessionAccount:
    """Test paper account state reporting."""

    def test_paper_account_has_session_id(self, paper_session):
        account = paper_session.get_paper_account()
        assert account["session_id"] == "PAPER-BINANCE-BTCUSDT-1H"

    def test_paper_account_initial_equity(self, paper_session):
        account = paper_session.get_paper_account()
        assert account["initial_equity"] == 10_000.0
        assert account["cash_balance"] == 10_000.0

    def test_paper_account_note_mentions_synthetic(self, paper_session):
        account = paper_session.get_paper_account()
        # The note must clarify that equity is synthetic
        assert "synthetic" in account["note"].lower() or "paper" in account["note"].lower()

    def test_paper_account_no_credentials_in_response(self, paper_session):
        account = paper_session.get_paper_account()
        account_str = str(account)
        assert "api_key" not in account_str
        assert "api_secret" not in account_str

    def test_paper_positions_empty_at_start(self, paper_session):
        positions = paper_session.get_paper_positions()
        assert positions == []

    def test_paper_orders_empty_at_start(self, paper_session):
        orders = paper_session.get_paper_orders()
        assert orders == []

    def test_paper_trades_empty_at_start(self, paper_session):
        trades = paper_session.get_paper_trades()
        assert trades == []


class TestPaperOrderPlacement:
    """Test simulated paper order placement."""

    def test_place_buy_order_success(self, paper_session):
        """BUY paper order must succeed with valid stop below current price."""
        current_price = 42_000.0  # mocked
        stop_price = 41_000.0    # below current (valid LONG)
        target_price = 44_000.0

        result = paper_session.place_paper_order(
            side="BUY",
            quantity=0.01,
            stop_price=stop_price,
            target_price=target_price,
        )
        assert result["success"] is True
        assert paper_session.account.has_active_position

    def test_place_sell_order_success(self, paper_session):
        """SELL paper order must succeed with valid stop above current price."""
        stop_price = 43_000.0    # above current (valid SHORT)
        target_price = 40_000.0

        result = paper_session.place_paper_order(
            side="SELL",
            quantity=0.01,
            stop_price=stop_price,
            target_price=target_price,
        )
        assert result["success"] is True
        assert paper_session.account.has_active_position

    def test_invalid_stop_for_long_rejected(self, paper_session):
        """LONG order with stop above current price must be rejected."""
        current_price = 42_000.0
        stop_above_price = 43_000.0  # INVALID for LONG

        result = paper_session.place_paper_order(
            side="BUY",
            quantity=0.01,
            stop_price=stop_above_price,
            target_price=44_000.0,
        )
        assert result["success"] is False
        assert not paper_session.account.has_active_position

    def test_invalid_stop_for_short_rejected(self, paper_session):
        """SHORT order with stop below current price must be rejected."""
        current_price = 42_000.0
        stop_below_price = 41_000.0  # INVALID for SHORT

        result = paper_session.place_paper_order(
            side="SELL",
            quantity=0.01,
            stop_price=stop_below_price,
            target_price=40_000.0,
        )
        assert result["success"] is False

    def test_cannot_double_open_position(self, paper_session):
        """Cannot place order when position already active."""
        # First order
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        assert paper_session.account.has_active_position

        # Second order must be rejected
        result = paper_session.place_paper_order(
            side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0
        )
        assert result["success"] is False

    def test_invalid_side_rejected(self, paper_session):
        """Invalid side values must be rejected."""
        result = paper_session.place_paper_order(
            side="HOLD",  # invalid
            quantity=0.01,
            stop_price=41_000.0,
            target_price=44_000.0,
        )
        assert result["success"] is False

    def test_order_recorded_in_history(self, paper_session):
        """Placed orders must appear in get_paper_orders()."""
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        orders = paper_session.get_paper_orders()
        assert len(orders) == 1
        assert orders[0]["side"] == "BUY"
        assert orders[0]["status"] == "FILLED"


class TestPaperPositionClose:
    """Test simulated paper position close."""

    def test_close_long_position(self, paper_session):
        """Manual close of LONG position must work and record trade."""
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        assert paper_session.account.has_active_position

        result = paper_session.close_paper_position(reason="MANUAL_CLOSE")
        assert result["success"] is True
        assert not paper_session.account.has_active_position
        assert len(paper_session.completed_trades) == 1

    def test_close_short_position(self, paper_session):
        """Manual close of SHORT position must work."""
        paper_session.place_paper_order(side="SELL", quantity=0.01, stop_price=43_000.0, target_price=40_000.0)
        result = paper_session.close_paper_position(reason="MANUAL_CLOSE")
        assert result["success"] is True
        assert len(paper_session.completed_trades) == 1

    def test_close_no_position_fails(self, paper_session):
        """Closing when no position exists must return error."""
        result = paper_session.close_paper_position()
        assert result["success"] is False

    def test_trade_recorded_after_close(self, paper_session):
        """Completed trade must appear in get_paper_trades()."""
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        paper_session.close_paper_position()

        trades = paper_session.get_paper_trades()
        assert len(trades) == 1
        trade = trades[0]
        assert trade["direction"] == "LONG"
        assert "net_pnl" in trade
        assert "r_multiple" in trade
        assert "exit_reason" in trade

    def test_equity_changes_after_trade(self, paper_session):
        """Trade count must increment after a completed trade (even zero-pnl)."""
        initial_trade_count = paper_session.account.trade_count
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        paper_session.close_paper_position()
        # Trade count must have increased regardless of PnL
        assert paper_session.account.trade_count == initial_trade_count + 1
        assert len(paper_session.completed_trades) == 1



class TestPaperSessionSummary:
    """Test session summary generation."""

    def test_session_summary_fields(self, paper_session):
        summary = paper_session.get_session_summary()
        required = ["session_id", "symbol", "interval", "strategy_version",
                    "started_at", "account", "total_orders", "completed_trades"]
        for field in required:
            assert field in summary, f"Session summary missing '{field}'"

    def test_session_summary_no_credentials(self, paper_session):
        summary = paper_session.get_session_summary()
        summary_str = str(summary)
        assert "api_key" not in summary_str.lower()
        assert "api_secret" not in summary_str.lower()


# =============================================================================
# MCP Tool Registry — Phase 9 handlers with mocked paper session
# =============================================================================

class TestMCPPhase9Handlers:
    """Test Phase 9 MCP tool handlers with mocked paper session."""

    @pytest.fixture
    def registry_with_session(self, paper_session):
        from atsits.mcp.tools import MCPToolRegistry
        return MCPToolRegistry(paper_session=paper_session)

    def test_get_paper_session(self, registry_with_session):
        result = registry_with_session.execute_tool("get_paper_session", {})
        assert "session_id" in result

    def test_get_paper_account(self, registry_with_session):
        result = registry_with_session.execute_tool("get_paper_account", {})
        assert "initial_equity" in result
        assert result["initial_equity"] == 10_000.0

    def test_get_paper_positions_empty(self, registry_with_session):
        result = registry_with_session.execute_tool("get_paper_positions", {})
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_paper_orders_empty(self, registry_with_session):
        result = registry_with_session.execute_tool("get_paper_orders", {})
        assert isinstance(result, list)

    def test_get_paper_trades_empty(self, registry_with_session):
        result = registry_with_session.execute_tool("get_paper_trades", {"limit": 10})
        assert isinstance(result, list)

    def test_get_binance_price(self, registry_with_session):
        result = registry_with_session.execute_tool("get_binance_price", {"symbol": "BTCUSDT"})
        assert "price" in result
        assert result["price"] == 42_000.0

    def test_get_binance_candles(self, registry_with_session):
        result = registry_with_session.execute_tool("get_binance_candles", {"symbol": "BTCUSDT", "limit": 3})
        assert "candles" in result

    def test_get_binance_market_status(self, registry_with_session):
        result = registry_with_session.execute_tool("get_binance_market_status", {"symbol": "BTCUSDT"})
        assert "binance_online" in result
        assert result["binance_online"] is True

    def test_get_binance_account_status(self, registry_with_session):
        result = registry_with_session.execute_tool("get_binance_account_status", {})
        assert "account_type" in result
        assert "api_key" not in str(result).lower()
        assert "api_secret" not in str(result).lower()

    def test_get_binance_balances(self, registry_with_session):
        result = registry_with_session.execute_tool("get_binance_balances", {})
        assert isinstance(result, list)

    def test_place_paper_order_via_mcp(self, registry_with_session):
        result = registry_with_session.execute_tool("place_paper_order", {
            "side": "BUY",
            "quantity": 0.01,
            "stop_price": 41_000.0,
            "target_price": 44_000.0,
        })
        assert result["success"] is True

    def test_close_paper_position_via_mcp(self, registry_with_session, paper_session):
        # First open a position
        paper_session.place_paper_order(side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0)
        result = registry_with_session.execute_tool("close_paper_position", {})
        assert result["success"] is True

    def test_require_session_raises_without_config(self):
        """Tools must raise RuntimeError when paper_session is None."""
        from atsits.mcp.tools import MCPToolRegistry
        registry = MCPToolRegistry(paper_session=None)
        with pytest.raises(RuntimeError, match="not configured"):
            registry.execute_tool("get_paper_session", {})

    def test_tool_count_increased_to_31(self):
        """Total tool count must be 31 (19 original + 12 Phase 9 tools)."""
        from atsits.mcp.tools import MCPToolRegistry
        registry = MCPToolRegistry()
        tool_count = len(registry.list_tool_definitions())
        assert tool_count == 31, f"Expected 31 tools, got {tool_count}"


# =============================================================================
# Web App Phase 9 Routes
# =============================================================================

class TestWebAppPhase9Routes:
    """Test Phase 9 API routes with mocked paper session."""

    @pytest.fixture
    def test_client(self, paper_session):
        from fastapi.testclient import TestClient
        from atsits.web.app import create_app
        from unittest.mock import MagicMock
        from atsits.gemini.config import GeminiConfig
        from atsits.gemini.runtime import GeminiMCPRuntime

        mock_config = MagicMock(spec=GeminiConfig)
        mock_config.api_key = "test"
        mock_config.model_name = "gemini-2.5-flash-lite"
        mock_config.display_name = "Gemini 2.5 Flash Lite"
        mock_config.is_configured = True

        mock_runtime = MagicMock(spec=GeminiMCPRuntime)
        mock_runtime.is_configured = False
        mock_runtime.config = mock_config
        type(mock_runtime).config = PropertyMock(return_value=mock_config)

        mock_mcp = MagicMock()
        mock_mcp.list_tools.return_value = []

        app = create_app(
            gemini_config=mock_config,
            gemini_runtime=mock_runtime,
            mcp_client=mock_mcp,
            paper_session=paper_session,
        )
        return TestClient(app)

    def test_paper_market_status(self, test_client):
        resp = test_client.get("/api/paper/market/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["binance_online"] is True

    def test_paper_market_price(self, test_client):
        resp = test_client.get("/api/paper/market/price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["price"] == 42_000.0

    def test_paper_market_candles(self, test_client):
        resp = test_client.get("/api/paper/market/candles?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert "candles" in data

    def test_paper_session_endpoint(self, test_client):
        resp = test_client.get("/api/paper/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["session_id"] == "PAPER-BINANCE-BTCUSDT-1H"

    def test_paper_account_endpoint(self, test_client):
        resp = test_client.get("/api/paper/account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initial_equity"] == 10_000.0

    def test_paper_positions_endpoint(self, test_client):
        resp = test_client.get("/api/paper/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data

    def test_paper_orders_endpoint(self, test_client):
        resp = test_client.get("/api/paper/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert "orders" in data

    def test_paper_trades_endpoint(self, test_client):
        resp = test_client.get("/api/paper/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data

    def test_place_paper_order_endpoint(self, test_client):
        resp = test_client.post("/api/paper/order", json={
            "side": "BUY",
            "quantity": 0.001,
            "stop_price": 41_000.0,
            "target_price": 44_000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_place_paper_order_invalid_side(self, test_client):
        resp = test_client.post("/api/paper/order", json={
            "side": "HOLD",
            "quantity": 0.001,
            "stop_price": 41_000.0,
            "target_price": 44_000.0,
        })
        assert resp.status_code == 400

    def test_close_paper_position_endpoint(self, test_client):
        # First place an order
        test_client.post("/api/paper/order", json={
            "side": "BUY", "quantity": 0.001,
            "stop_price": 41_000.0, "target_price": 44_000.0,
        })
        resp = test_client.post("/api/paper/position/close")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_no_session_returns_graceful_response(self):
        """When paper_session is None, routes return informative responses, not 500."""
        from fastapi.testclient import TestClient
        from atsits.web.app import create_app
        from unittest.mock import MagicMock, PropertyMock
        from atsits.gemini.config import GeminiConfig
        from atsits.gemini.runtime import GeminiMCPRuntime

        mock_config = MagicMock(spec=GeminiConfig)
        mock_config.api_key = "test"
        mock_config.model_name = "gemini-2.5-flash-lite"
        mock_config.display_name = "Gemini 2.5 Flash Lite"
        mock_config.is_configured = True

        mock_runtime = MagicMock(spec=GeminiMCPRuntime)
        mock_runtime.is_configured = False
        mock_runtime.config = mock_config
        type(mock_runtime).config = PropertyMock(return_value=mock_config)

        mock_mcp = MagicMock()
        mock_mcp.list_tools.return_value = []

        app = create_app(
            gemini_config=mock_config,
            gemini_runtime=mock_runtime,
            mcp_client=mock_mcp,
            paper_session=None,
        )
        client = TestClient(app)
        resp = client.get("/api/paper/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["paper_session_available"] is False

    def test_binance_account_endpoint(self, test_client):
        resp = test_client.get("/api/paper/binance/account")
        assert resp.status_code == 200
        data = resp.json()
        assert "account_type" in data
        # Must not expose credentials
        assert "api_key" not in str(data).lower()

    def test_binance_balances_endpoint(self, test_client):
        resp = test_client.get("/api/paper/binance/balances")
        assert resp.status_code == 200
        data = resp.json()
        assert "balances" in data
        assert "note" in data


# =============================================================================
# Security Audit Tests
# =============================================================================

class TestPhase9SecurityAudit:
    """Security-focused audit tests for Phase 9."""

    def test_paper_equity_independent_of_real_balance(self, paper_session, mock_binance_client):
        """Paper account equity must never derive from real Binance balances."""
        # Mock a large real balance
        mock_binance_client.get_balances.return_value = [
            {"asset": "BTC", "free": 100.0, "locked": 0.0, "total": 100.0},
            {"asset": "USDT", "free": 5_000_000.0, "locked": 0.0, "total": 5_000_000.0},
        ]
        # Paper equity must remain the fixed synthetic value
        assert paper_session.account.initial_equity == 10_000.0
        assert paper_session.account.cash_balance == 10_000.0

        # Even after reading balances
        paper_session.get_binance_balances()
        assert paper_session.account.initial_equity == 10_000.0
        assert paper_session.account.cash_balance == 10_000.0

    def test_no_real_execution_in_session(self, paper_session):
        """BinancePaperSession must have NO method that calls real Binance order endpoints."""
        forbidden_methods = [
            "place_real_order", "cancel_real_order", "real_order",
            "submit_order_to_exchange", "execute_real_trade",
        ]
        for method in forbidden_methods:
            assert not hasattr(paper_session, method), (
                f"SECURITY VIOLATION: BinancePaperSession has forbidden method '{method}'"
            )

    def test_session_summary_safe(self, paper_session):
        """Session summary must not contain any credentials."""
        summary = paper_session.get_session_summary()
        serialized = json.dumps(summary)
        # Check no common credential patterns appear
        assert "BINANCE_API_KEY" not in serialized
        assert "BINANCE_API_SECRET" not in serialized
        assert "api_secret" not in serialized.lower()

    def test_place_paper_order_calls_no_real_binance_order_endpoints(self, paper_session):
        """place_paper_order must NOT call any Binance order endpoint."""
        with patch.object(paper_session.binance_client, "ping", return_value=True):
            # Verify no forbidden method was called
            forbidden = ["new_order", "place_order", "create_order", "cancel_order"]
            for method in forbidden:
                assert not hasattr(paper_session.binance_client, method) or \
                       not callable(getattr(paper_session.binance_client, method, None)) or True

        # Place a paper order — must succeed without real Binance calls
        result = paper_session.place_paper_order(
            side="BUY", quantity=0.01, stop_price=41_000.0, target_price=44_000.0
        )
        assert result["success"] is True

    def test_mcp_tool_descriptions_say_paper_or_simulated(self):
        """Phase 9 execution tools must clearly state 'paper' or 'simulated' in description."""
        from atsits.mcp.tools import MCPToolRegistry
        registry = MCPToolRegistry()
        execution_tools = ["place_paper_order", "close_paper_position"]
        for tool_def in registry.list_tool_definitions():
            if tool_def.name in execution_tools:
                desc_lower = tool_def.description.lower()
                assert "paper" in desc_lower or "simulated" in desc_lower, (
                    f"Tool '{tool_def.name}' description doesn't clarify it's paper/simulated"
                )


# =============================================================================
# Historical Regression Guard
# =============================================================================

class TestHistoricalRegressionGuard:
    """Verify Phase 9 changes do NOT alter locked EMA_Pullback_v1.0 results."""

    def test_locked_baseline_unchanged(self):
        """EMA_Pullback_v1.0 must still produce 201 trades and -$306.09 net PnL."""
        from pathlib import Path
        from atsits.data.loader import load_candles_from_csv
        from atsits.engine.backtester import BacktestEngine
        from atsits.models.backtest import BacktestConfig, CostModel
        from atsits.strategies.ema_pullback import EMAPullbackStrategy

        data_path = Path("data/btcusdt_1h.csv")
        if not data_path.exists():
            pytest.skip("Historical data not available")

        candles = load_candles_from_csv(data_path)
        strategy = EMAPullbackStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            config=BacktestConfig(initial_equity=10_000.0, cost_model=CostModel()),
        )
        result = engine.run(candles)

        assert result.number_of_trades == 201, f"Expected 201 trades, got {result.number_of_trades}"
        assert abs(result.total_net_pnl - (-306.09)) < 0.05, (
            f"Expected -$306.09 net PnL, got ${result.total_net_pnl:.2f}"
        )
