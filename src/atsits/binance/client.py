"""Binance Read-Only REST Client for Phase 9 market data and account status.

SECURITY CONTRACT:
- This client provides STRICTLY READ-ONLY Binance access.
- There is NO capability to place, cancel, modify, or query execution of orders.
- Credentials are loaded exclusively from environment variables at call time.
- Credentials are NEVER included in log output, error messages, or returned data.
- The client uses HMAC-SHA256 request signing only for authenticated read endpoints
  (e.g. account balance). Market data endpoints use no authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BINANCE_REST_BASE = "https://api.binance.com"
_TIMEOUT_SEC = 10.0


class BinanceClientError(Exception):
    """Raised when the Binance API returns an error or network fails.

    Credentials and API keys are NEVER included in the error message.
    """


def _safe_error(msg: str) -> BinanceClientError:
    """Return a BinanceClientError, ensuring no credentials appear in msg."""
    return BinanceClientError(msg)


class BinanceReadOnlyClient:
    """Read-only Binance REST client.

    Provides:
    - Public market data (klines, ticker price, exchange info) — unauthenticated.
    - Authenticated read-only account endpoints (account status, balances) — signed.

    FORBIDDEN (absent by design):
    - place_order / new_order
    - cancel_order
    - withdraw / transfer
    - Any mutation of account state
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = BINANCE_REST_BASE,
        timeout_sec: float = _TIMEOUT_SEC,
    ) -> None:
        # Credentials stored in private attrs — never logged or serialised
        self._api_key = api_key or ""
        self._api_secret = api_secret or ""
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_sec

    # ------------------------------------------------------------------
    # Public (unauthenticated) endpoints — market data
    # ------------------------------------------------------------------

    def get_server_time(self) -> int:
        """Return Binance server timestamp in milliseconds (unauthenticated)."""
        data = self._get_public("/api/v3/time")
        return int(data["serverTime"])

    def ping(self) -> bool:
        """Test connectivity to Binance REST API (unauthenticated)."""
        try:
            self._get_public("/api/v3/ping")
            return True
        except BinanceClientError:
            return False

    def get_exchange_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Return exchange trading rules for a symbol or globally (unauthenticated).

        Returns safe metadata: symbol status, base/quote assets, filters.
        Credentials never included.
        """
        params: Dict[str, str] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._get_public("/api/v3/exchangeInfo", params=params)

    def get_ticker_price(self, symbol: str) -> float:
        """Return latest last-trade price for symbol (unauthenticated).

        Args:
            symbol: Binance symbol (e.g. BTCUSDT).

        Returns:
            Latest price as float.
        """
        data = self._get_public("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return float(data["price"])

    def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch completed klines from Binance (unauthenticated).

        Args:
            symbol: Market pair (e.g. BTCUSDT).
            interval: Kline interval (e.g. 1h, 15m).
            limit: Number of klines to fetch (max 1000).
            start_ms: Optional start time in milliseconds.
            end_ms: Optional end time in milliseconds.

        Returns:
            List of dicts with OHLCV data. Currently-forming bar excluded.
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms

        raw: List[Any] = self._get_public("/api/v3/klines", params=params)

        now_ms = int(time.time() * 1000)
        candles: List[Dict[str, Any]] = []
        for item in raw:
            close_time_ms = int(item[6])
            # Exclude forming (unclosed) candle
            if close_time_ms > now_ms:
                continue
            open_time_ms = int(item[0])
            candles.append({
                "open_time": open_time_ms,
                "open_time_iso": datetime.fromtimestamp(
                    open_time_ms / 1000.0, tz=timezone.utc
                ).isoformat(),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time": close_time_ms,
                "symbol": symbol.upper(),
                "interval": interval,
            })

        return candles

    # ------------------------------------------------------------------
    # Authenticated read-only endpoints — account status / balances
    # ------------------------------------------------------------------

    def get_account_status(self) -> Dict[str, Any]:
        """Return account status (authenticated, read-only).

        Returns safe metadata: accountType, canTrade, canDeposit, canWithdraw,
        permissions list. Does NOT return balances (use get_balances()).

        SECURITY: API key is sent in header only. Secret never appears in output.
        """
        if not self._api_key or not self._api_secret:
            return {
                "account_type": "NOT CONFIGURED",
                "can_trade": False,
                "can_deposit": False,
                "can_withdraw": False,
                "permissions": [],
                "available": False,
                "message": "Binance API credentials not configured in .env (public market data mode active).",
            }

        raw = self._get_signed("/api/v3/account")
        return {
            "account_type": raw.get("accountType", "UNKNOWN"),
            "can_trade": bool(raw.get("canTrade", False)),
            "can_deposit": bool(raw.get("canDeposit", False)),
            "can_withdraw": bool(raw.get("canWithdraw", False)),
            "permissions": raw.get("permissions", []),
            "uid": raw.get("uid"),
        }

    def get_balances(
        self,
        assets: Optional[List[str]] = None,
        hide_zero: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return account asset balances (authenticated, read-only).

        Args:
            assets: Optional filter list (e.g. ['BTC', 'USDT']). None = all.
            hide_zero: Skip assets with zero free+locked.

        Returns:
            List of {'asset', 'free', 'locked', 'total'} dicts.

        SECURITY: Balances are real Binance data and used for READ ONLY.
        Real balances must NEVER be used as paper account starting equity.
        """
        if not self._api_key or not self._api_secret:
            return [{"error": "Binance API credentials not configured in .env", "status": "NOT CONFIGURED"}]

        raw = self._get_signed("/api/v3/account")
        balances_raw: List[Dict[str, str]] = raw.get("balances", [])

        result: List[Dict[str, Any]] = []
        filter_set = {a.upper() for a in assets} if assets else None

        for b in balances_raw:
            asset = b.get("asset", "")
            free = float(b.get("free", 0.0))
            locked = float(b.get("locked", 0.0))
            total = free + locked

            if filter_set and asset not in filter_set:
                continue
            if hide_zero and total == 0.0:
                continue

            result.append({
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
            })

        return result

    # ------------------------------------------------------------------
    # Internal helpers — never expose credentials in errors
    # ------------------------------------------------------------------

    def _get_public(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """HTTP GET to a public (unauthenticated) endpoint."""
        url = self._build_url(path, params or {})
        return self._http_get(url, headers={})

    def _get_signed(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """HTTP GET to an authenticated endpoint using HMAC-SHA256 signature.

        API key is sent as header. Secret is used only to compute the HMAC
        and is never serialised or logged.
        """
        all_params: Dict[str, Any] = dict(params or {})
        all_params["timestamp"] = int(time.time() * 1000)
        all_params["recvWindow"] = 5000

        query = urllib.parse.urlencode(all_params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        query += f"&signature={signature}"

        url = f"{self._base_url}{path}?{query}"
        headers = {"X-MBX-APIKEY": self._api_key}
        return self._http_get(url, headers=headers)

    def _build_url(self, path: str, params: Dict[str, Any]) -> str:
        if params:
            return f"{self._base_url}{path}?{urllib.parse.urlencode(params)}"
        return f"{self._base_url}{path}"

    def _http_get(self, url: str, headers: Dict[str, str]) -> Any:
        """Execute an HTTP GET and return parsed JSON, masking credentials in errors."""
        # Strip query string from logged URL to avoid leaking signature/key
        log_url = url.split("?")[0]
        logger.debug("Binance REST GET: %s", log_url)

        req = urllib.request.Request(url, headers={"User-Agent": "ATSITS/9.0", **headers})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as http_err:
            try:
                err_body = http_err.read().decode("utf-8")
                err_data = json.loads(err_body)
                code = err_data.get("code", http_err.code)
                msg = err_data.get("msg", str(http_err))
            except Exception:
                code = http_err.code
                msg = "HTTP error"
            # Never include credentials in raised error
            raise _safe_error(f"Binance API error [{code}]: {msg}") from None
        except Exception as exc:
            raise _safe_error(f"Binance network error: {type(exc).__name__}") from None

        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise _safe_error("Binance returned non-JSON response") from None
