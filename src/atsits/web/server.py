"""Local web server runner binding strictly to 127.0.0.1 (Phases 8.6 & 9).

SECURITY:
- Binance credentials loaded from environment ONLY (BINANCE_API_KEY, BINANCE_API_SECRET).
- Credentials are NEVER passed to Gemini, MCP tool args, browser, or logs.
- Paper session uses fixed synthetic equity — real Binance balance is NEVER used.
"""

import logging
import os
import sys
import uvicorn

from atsits.web.app import create_app

logger = logging.getLogger(__name__)


def _build_paper_session():
    """Attempt to build a BinancePaperSession from environment credentials.

    Returns None if BINANCE_API_KEY or BINANCE_API_SECRET are not set.
    Credentials are loaded at startup and stored in private client attrs only.
    """
    api_key = os.environ.get("BINANCE_API_KEY", "").strip()
    api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()
    has_creds = bool(api_key and api_secret)

    if not has_creds:
        logger.info(
            "BINANCE_API_KEY / BINANCE_API_SECRET not set in environment. "
            "Initializing paper session in PUBLIC MARKET DATA MODE. "
            "Public klines, live price feeds, and simulated paper execution will be active. "
            "Account status and balances will report 'NOT CONFIGURED'."
        )

    try:
        from atsits.binance.client import BinanceReadOnlyClient
        from atsits.paper.session import BinancePaperSession
        from atsits.strategies.experimental_ema import EMAExperimentalStrategy

        from atsits.journal.storage import TradingJournal
        from pathlib import Path

        journal_path = Path("data/journal/paper_journal.jsonl")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal = TradingJournal(journal_path)

        client = BinanceReadOnlyClient(api_key=api_key, api_secret=api_secret)
        strategy = EMAExperimentalStrategy()
        session = BinancePaperSession(
            binance_client=client,
            strategy=strategy,
            session_id="PAPER-BINANCE-BTCUSDT-1H",
            symbol="BTCUSDT",
            interval="1h",
            initial_equity=10_000.0,
            risk_pct=0.01,
            journal=journal,
        )
        # Warm up EMA indicators from recent Binance public historical klines
        logger.info("Warming up paper session strategy from Binance public historical klines...")
        try:
            warmed = session.warmup(warmup_limit=100)
            logger.info("Paper session warmup complete: %d candles, is_ready=%s", warmed, session.strategy.is_ready)
        except Exception as exc:
            logger.warning("Paper session warmup failed (will retry on first candle): %s", exc)

        logger.info(
            "Phase 9 paper session initialized: %s (mode=%s, strategy=%s, equity=%.2f, rr=%.1fR)",
            session.session_id,
            "AUTHENTICATED_READ" if has_creds else "PUBLIC_MARKET_ONLY",
            strategy.VERSION,
            session.account.initial_equity,
            session.strategy.take_profit_rr,
        )
        return session
    except Exception as exc:
        logger.warning("Failed to initialize Binance paper session: %s", exc)
        return None


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Launch the ATSITS Local Web GUI server."""
    # Enforce strictly local binding
    if host not in ("127.0.0.1", "localhost"):
        print(f"[SECURITY WARNING] Binding to '{host}' is rejected. Enforcing 127.0.0.1 for local isolation.")
        host = "127.0.0.1"

    paper_session = _build_paper_session()
    app = create_app(paper_session=paper_session)

    print("=" * 65)
    print("       ATSITS LOCAL WEB GUI (Phase 8.6 / 9)")
    print("=" * 65)
    print(f"Local Server URL:  http://{host}:{port}")
    print("Bound strictly to: 127.0.0.1 (Localhost only)")
    if paper_session is not None:
        print(f"Paper Session:     {paper_session.session_id} [ACTIVE]")
        print(f"Paper Strategy:    {paper_session.strategy.VERSION}")
        print(f"Paper Equity:      ${paper_session.account.initial_equity:,.2f} (synthetic)")
    else:
        print("Paper Session:     NOT CONFIGURED (set BINANCE_API_KEY + BINANCE_API_SECRET)")
    print("Press Ctrl+C to stop the server.")
    print("=" * 65)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port_arg = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port_arg = int(sys.argv[1])
    run_server(port=port_arg)
