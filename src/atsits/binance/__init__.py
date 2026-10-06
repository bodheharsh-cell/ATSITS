"""ATSITS Binance Integration — Phase 9: Read-Only Market Data + Account Status.

SECURITY CONTRACT:
- This module provides STRICTLY READ-ONLY Binance access.
- No order placement, cancellation, or modification capabilities exist.
- Binance credentials are NEVER exposed to browser, JavaScript, Gemini, MCP
  tool arguments, logs, journal entries, or error messages.
- Only BINANCE_API_KEY and BINANCE_API_SECRET environment variables are used.
- No real balances are used as paper account balances.
"""

from atsits.binance.client import BinanceReadOnlyClient, BinanceClientError

__all__ = [
    "BinanceReadOnlyClient",
    "BinanceClientError",
]
