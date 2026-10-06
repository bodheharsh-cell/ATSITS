"""FastAPI Application for ATSITS Basic Local Web GUI (Phases 8.6, 8.7 & 9)."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from atsits.binance.client import BinanceClientError, BinanceReadOnlyClient
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.gemini.client import GeminiClient, _get_model_display_name
from atsits.gemini.config import (
    GeminiConfig,
    SUPPORTED_GEMINI_MODELS,
    get_supported_models,
    load_gemini_config,
    persist_gemini_model,
    persist_gemini_selection_mode,
    validate_model_id,
    validate_selection_target,
)
from atsits.gemini.exceptions import (
    AllModelsUnavailableError,
    CriticalTaskDowngradePreventedError,
    GeminiAPIError,
    GeminiAuthError,
    GeminiError,
    GeminiNotConfiguredError,
    GeminiQuotaExceededError,
)

from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.journal.models import TradeRecord
from atsits.journal.storage import TradingJournal
from atsits.learning.registry import ExperimentRegistry
from atsits.mcp.client import MCPClient
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.paper.session import BinancePaperSession
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from atsits.strategies.experimental_ema import EMAExperimentalStrategy
from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import DraftStatus, ReviewAction, SourceType
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.review import HumanReviewEngine
from atsits.teaching.sources import create_teaching_material
from atsits.teaching.validator import StrategyValidator


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------
class ChatMessageInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    message: str = Field(..., min_length=1, description="User chat query")


class SelectModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    model: Optional[str] = Field(default=None, description="Target Gemini model ID from whitelist or 'auto'")
    model_id: Optional[str] = Field(default=None, description="Target Gemini model ID from whitelist or 'auto'")
    mode: Optional[str] = Field(default=None, description="Selection mode: AUTO or MANUAL")
    persist: bool = Field(default=True, description="Whether to persist to .env")

    @property
    def target_model(self) -> str:
        return (self.model_id or self.model or "").strip()



class BacktestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_name: str = Field(default="EMA_Pullback_v1.0", description="Strategy identifier")
    initial_equity: float = Field(default=10000.0, ge=100.0, le=1000000.0, description="Starting capital")


class TeachExtractRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str = Field(..., min_length=5, description="Raw strategy rules or teaching text")


class TeachReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    draft_id: str = Field(..., min_length=1, description="Target draft strategy ID")
    action: str = Field(..., description="Action: APPROVE, CLARIFY, REJECT, VERIFY")
    clarifications: Optional[Dict[str, str]] = Field(default=None, description="Key-value clarifications")
    notes: Optional[str] = Field(default=None, description="Operator notes")


class PaperOrderRequest(BaseModel):
    """Request body for placing a simulated paper order.

    SECURITY: Only simulated — no real Binance order is ever placed.
    """
    model_config = ConfigDict(frozen=True)
    side: str = Field(..., description="BUY (LONG) or SELL (SHORT)")
    quantity: float = Field(..., gt=0.0, description="Position size in base asset units")
    stop_price: float = Field(..., gt=0.0, description="Stop loss price")
    target_price: float = Field(..., gt=0.0, description="Take profit price")


# ---------------------------------------------------------------------
# Web App Factory
# ---------------------------------------------------------------------
def create_app(
    gemini_config: Optional[GeminiConfig] = None,
    gemini_runtime: Optional[GeminiMCPRuntime] = None,
    mcp_client: Optional[MCPClient] = None,
    data_path: Optional[Path] = None,
    paper_session: Optional[BinancePaperSession] = None,
) -> FastAPI:
    """Create and configure the FastAPI web application."""

    app = FastAPI(
        title="ATSITS Local Web GUI",
        description="Local-first browser interface for ATSITS algorithmic trading research.",
        version="0.1.0",
    )

    config = gemini_config or load_gemini_config()
    client = GeminiClient(config=config)
    mcp = mcp_client or MCPClient()
    runtime = gemini_runtime or GeminiMCPRuntime(config=config, client=client, mcp_client=mcp)

    resolved_data_path = data_path or (
        Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv")
    )

    teaching_registry = TeachingRegistry()
    teaching_extractor = StrategyExtractor()
    teaching_validator = StrategyValidator()
    teaching_review = HumanReviewEngine(
        registry=teaching_registry,
        validator=teaching_validator,
    )
    experiment_registry = ExperimentRegistry()
    journal = TradingJournal(file_path=Path("data/journal/journal.jsonl"))

    template_path = Path(__file__).parent / "templates" / "index.html"

    # ------------------------------------------------------------------
    # Frontend HTML Route
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        if template_path.is_file():
            content = template_path.read_text(encoding="utf-8")
            return HTMLResponse(content=content)
        return HTMLResponse("<h3>ATSITS Web GUI template not found.</h3>", status_code=500)

    # ------------------------------------------------------------------
    # API: Health & Local Readiness Probe (Fast, zero external dependencies)
    # ------------------------------------------------------------------
    @app.get("/api/health")
    async def get_health():
        """Lightweight readiness probe returning immediate HTTP 200 without external network calls."""
        return {
            "status": "HEALTHY",
            "app": "ATSITS",
            "ready": True,
        }

    # ------------------------------------------------------------------
    # API: System Status
    # ------------------------------------------------------------------
    @app.get("/api/status")
    async def get_status():
        is_online = False
        gemini_status = "NOT_CONFIGURED"
        status_msg = ""
        probe_meta: Dict[str, Any] = {}

        if runtime.is_configured:
            try:
                if hasattr(runtime, "test_connection"):
                    is_online, status_msg, probe_meta = runtime.test_connection()
                    gemini_status = probe_meta.get("status", "ONLINE" if is_online else "OFFLINE")
                elif hasattr(runtime, "client") and hasattr(runtime.client, "test_connection"):
                    is_online, status_msg = runtime.client.test_connection()
                    gemini_status = "ONLINE" if is_online else "OFFLINE"
                else:
                    is_online = True
                    gemini_status = "ONLINE"
            except Exception as exc:
                is_online = False
                gemini_status = "OFFLINE"
                status_msg = str(exc)

        mcp_tools = mcp.list_tools() if hasattr(mcp, "list_tools") else []
        drafts = teaching_registry.list_drafts()
        verified = teaching_registry.list_verified_strategies()

        candle_count = 0
        if resolved_data_path.exists():
            try:
                candles = load_candles_from_csv(resolved_data_path)
                candle_count = len(candles)
            except Exception:
                pass

        cfg = getattr(runtime, "config", config)
        mode = getattr(runtime, "selection_mode", "AUTO")
        if mode == "AUTO":
            model_name = probe_meta.get("model", getattr(runtime, "current_model", cfg.model_name))
            display_name = probe_meta.get("display_name", f"⚡ Auto Router ({_get_model_display_name(model_name)})")
        else:
            model_name = getattr(cfg, "model_name", "gemini-2.5-flash-lite")
            display_name = getattr(cfg, "display_name", "Gemini 2.5 Flash Lite")

        # IMPORTANT: Never include GEMINI_API_KEY or masked key in JSON response
        return {
            "status": "READY",
            "gemini_online": is_online,
            "gemini_status": gemini_status,
            "gemini_status_message": status_msg,
            "gemini_model": model_name,
            "gemini_model_display": display_name,
            "gemini_display_name": display_name,
            "gemini_selection_mode": mode,
            "mcp_tool_count": len(mcp_tools),
            "dataset_candles": candle_count,
            "drafts_count": len(drafts),
            "verified_strategies_count": len(verified),
            "production_strategy": "EMA_Pullback_v1.0",
            "authority": "HUMAN_OPERATOR",
        }

    # ------------------------------------------------------------------
    # API: Model Selection & Registry (Phases 8.7 & 8.8)
    # ------------------------------------------------------------------
    @app.get("/api/models")
    async def list_models():
        """List supported Gemini models, current mode, active model, and health status."""
        cfg = getattr(runtime, "config", config)
        mode = getattr(runtime, "selection_mode", "AUTO")
        model_name = getattr(runtime, "current_model", cfg.model_name)
        display_name = getattr(cfg, "display_name", "Gemini 2.5 Flash Lite")
        health = {}
        if hasattr(runtime, "router") and hasattr(runtime.router, "health_tracker"):
            health = runtime.router.health_tracker.get_health_summary()

        return {
            "models": get_supported_models(),
            "mode": mode,
            "active_model_id": model_name,
            "active_display_name": display_name,
            "current_model": model_name,
            "current_display_name": display_name,
            "health": health,
        }

    @app.post("/api/model")
    async def set_model(req: SelectModelRequest):
        """Set active Gemini model after validating against whitelist or switch mode."""
        try:
            target = req.target_model
            mode_req = (req.mode or "").strip().upper()

            if mode_req == "AUTO" or target.lower() in ("auto", "router", "default"):
                clean_mode = runtime.set_mode("AUTO")
                if req.persist:
                    persist_gemini_selection_mode("AUTO")
                return {
                    "success": True,
                    "status": "ok",
                    "mode": "AUTO",
                    "model_id": "auto",
                    "current_model": runtime.current_model,
                    "display_name": "Automatic Router (Task-Aware)",
                    "message": "Switched to Automatic Task-Aware Model Router.",
                }

            if not target:
                raise ValueError("Model ID is required.")

            validated_model = validate_model_id(target)
            runtime.set_model(validated_model)
            if req.persist:
                persist_gemini_model(validated_model)
                persist_gemini_selection_mode("MANUAL")
            return {
                "success": True,
                "status": "ok",
                "mode": "MANUAL",
                "model_id": validated_model,
                "current_model": validated_model,
                "display_name": runtime.config.display_name,
                "message": f"Active Gemini model switched to {runtime.config.display_name}.",
            }
        except ValueError as val_err:
            raise HTTPException(status_code=400, detail=str(val_err))
        except Exception as exc:
            logger.error("Failed to set model: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to switch model: {exc}")

    # ------------------------------------------------------------------
    # API: Interactive Chat (with in-memory conversation and MCP tracking)
    # ------------------------------------------------------------------
    @app.post("/api/chat")
    async def chat(req: ChatMessageInput):
        if not runtime.is_configured:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Gemini API is not configured. Set GEMINI_API_KEY in .env to enable intelligent chat.",
                    "response": "Gemini is currently offline. All deterministic tools (Backtest, Strategy, Journal, Teach) remain fully functional.",
                    "mcp_calls": [],
                },
            )

        captured_calls: List[Dict[str, Any]] = []

        def on_mcp_tool(name: str, args: Dict[str, Any], result: Dict[str, Any]):
            captured_calls.append({
                "name": name,
                "args": args,
                "is_error": result.get("is_error", False),
            })

        cfg = getattr(runtime, "config", config)
        active_model = getattr(cfg, "model_name", "gemini-2.5-flash-lite")
        active_display = getattr(cfg, "display_name", "Gemini 2.5 Flash Lite")

        try:
            response_text = runtime.send_message(req.message, on_tool_call=on_mcp_tool)
            routing_meta = (
                runtime.last_routing_metadata.to_dict()
                if getattr(runtime, "last_routing_metadata", None)
                else None
            )
            return {
                "response": response_text,
                "mcp_calls": captured_calls,
                "model": getattr(runtime, "current_model", active_model),
                "routing": routing_meta,
            }
        except CriticalTaskDowngradePreventedError as crit_err:
            logger.warning("Critical task downgrade prevented: %s", crit_err)
            return {
                "error": "CRITICAL_DOWNGRADE_PREVENTED",
                "error_code": "CRITICAL_DOWNGRADE_PREVENTED",
                "message": str(crit_err),
                "response": str(crit_err),
                "model": getattr(runtime, "current_model", active_model),
                "mcp_calls": captured_calls,
            }
        except AllModelsUnavailableError as all_err:
            logger.warning("All Gemini models unavailable: %s", all_err)
            return {
                "error": "ALL_MODELS_UNAVAILABLE",
                "error_code": "ALL_MODELS_UNAVAILABLE",
                "message": str(all_err),
                "response": str(all_err),
                "model": getattr(runtime, "current_model", active_model),
                "mcp_calls": captured_calls,
            }
        except GeminiQuotaExceededError as q_err:
            logger.warning("Gemini quota exceeded: %s", q_err)
            return {
                "error": "QUOTA_EXHAUSTED",
                "error_code": "QUOTA_EXHAUSTED",
                "message": str(q_err),
                "response": str(q_err),
                "model": active_model,
                "mcp_calls": captured_calls,
            }
        except Exception as exc:
            logger.error("Chat generation error: %s", exc)
            err_msg = str(exc)
            if any(k in err_msg.lower() for k in ("429", "resource_exhausted", "quota")):
                err_msg = f"Gemini {active_display} quota exhausted. Switch to another available model or try again later."
                return {
                    "error": "QUOTA_EXHAUSTED",
                    "error_code": "QUOTA_EXHAUSTED",
                    "message": err_msg,
                    "response": err_msg,
                    "model": active_model,
                    "mcp_calls": captured_calls,
                }
            return {
                "error": err_msg,
                "response": f"Gemini Notice: {err_msg}",
                "model": active_model,
                "mcp_calls": captured_calls,
            }


    @app.post("/api/chat/reset")
    async def reset_chat():
        runtime.reset()
        return {"status": "ok", "message": "Conversation history cleared from memory."}

    # ------------------------------------------------------------------
    # API: Strategy Management
    # ------------------------------------------------------------------
    @app.get("/api/strategy")
    async def get_strategy():
        verified = teaching_registry.list_verified_strategies()
        drafts = teaching_registry.list_drafts()

        verified_data = []
        for v in verified:
            strat_name = getattr(v.strategy_spec, "strategy_name", "Strategy")
            verified_data.append({
                "draft_id": v.draft_id,
                "name": strat_name,
                "version": v.version,
                "status": v.status.value,
                "verified_by": v.verified_by,
                "verified_at": v.verified_at.isoformat(),
            })

        drafts_data = []
        for d in drafts:
            drafts_data.append({
                "draft_id": d.draft_id,
                "strategy_name": d.strategy_name,
                "status": d.status.value,
                "timeframe": d.timeframe,
                "rules_count": len(d.rules),
            })

        return {
            "production_strategy": {
                "name": "EMA_Pullback_v1.0",
                "version": "1.0.0",
                "status": "PRODUCTION_LOCKED",
                "parameters": {"fast_period": 20, "slow_period": 50},
            },
            "verified_strategies": verified_data,
            "draft_strategies": drafts_data,
        }

    # ------------------------------------------------------------------
    # API: Deterministic Backtesting (Strict Boundary Enforced)
    # ------------------------------------------------------------------
    @app.post("/api/backtest")
    async def backtest(req: BacktestRequest):
        # Strict boundary: only allow registered deterministic strategies
        supported_strats = ("EMA_Pullback_v1.0", "EMA_Pullback_EMA20_30_3R", "EMA_Pullback_v1.1_exp")
        if req.strategy_name not in supported_strats:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported strategy '{req.strategy_name}'. Only registered deterministic strategies are permitted: {supported_strats}.",
            )

        if not resolved_data_path.exists():
            raise HTTPException(status_code=404, detail="Historical dataset not found.")

        try:
            candles = load_candles_from_csv(resolved_data_path)
            if req.strategy_name in ("EMA_Pullback_EMA20_30_3R", "EMA_Pullback_v1.1_exp"):
                strategy = EMAExperimentalStrategy()
            else:
                strategy = EMAPullbackStrategy()

            cfg = BacktestConfig(
                initial_equity=req.initial_equity,
                cost_model=CostModel(),
            )
            engine = BacktestEngine(config=cfg, strategy=strategy)
            result = engine.run(candles)

            return {
                "strategy_name": req.strategy_name,
                "initial_equity": result.initial_equity,
                "final_equity": result.final_equity,
                "total_net_pnl": result.total_net_pnl,
                "total_return_pct": result.total_return_pct,
                "number_of_trades": result.number_of_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "max_drawdown_pct": result.max_drawdown_pct,
                "average_trade_pnl": result.average_trade_pnl,
            }
        except Exception as exc:
            logger.error("Backtest execution failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Backtest error: {exc}")

    # ------------------------------------------------------------------
    # API: Journal & Trade Records
    # ------------------------------------------------------------------
    @app.get("/api/journal")
    async def get_journal():
        trades = [r for r in journal.read_all() if isinstance(r, TradeRecord)]
        trades_data = []
        for t in trades:
            trades_data.append({
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                "entry_time": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else None,
                "exit_time": t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else None,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "net_pnl": t.realized_pnl or 0.0,
                "exit_reason": getattr(t, "exit_reason", "NORMAL"),
            })
        return {"total_trades": len(trades), "trades": trades_data}

    # ------------------------------------------------------------------
    # API: Experiments Registry
    # ------------------------------------------------------------------
    @app.get("/api/experiments")
    async def get_experiments():
        exps = experiment_registry.list_all()
        exps_data = []
        for e in exps:
            exps_data.append({
                "experiment_id": e.experiment_id,
                "hypothesis_id": e.hypothesis_id,
                "status": e.status.value,
                "baseline_strategy_version": e.baseline_strategy_version,
                "candidate_strategy_version": e.candidate_strategy_version,
                "validation_passed": e.validation_passed,
                "validation_summary": e.validation_summary,
            })
        return {"total_experiments": len(exps), "experiments": exps_data}

    # ------------------------------------------------------------------
    # API: Strategy Teaching Pipeline (Extraction & Human Review Gate)
    # ------------------------------------------------------------------
    @app.post("/api/teach/extract")
    async def teach_extract(req: TeachExtractRequest):
        try:
            material = create_teaching_material(
                title="Web GUI Strategy Input",
                content=req.text,
                source_type=SourceType.TEXT,
                source_reference="Human Operator (Web GUI)",
            )
            teaching_registry.save_material(material)
            draft = teaching_extractor.extract_draft(materials=[material])
            teaching_registry.save_draft(draft)

            rules_data = [
                {
                    "rule_id": r.rule_id,
                    "category": r.category.value,
                    "statement": r.statement,
                    "certainty": r.certainty.value,
                    "evidence": r.evidence,
                }
                for r in draft.rules
            ]

            missing_data = [
                {
                    "missing_id": m.missing_id,
                    "item_name": m.item_name,
                    "description": m.description,
                    "critical": m.critical,
                }
                for m in draft.missing_information
            ]

            return {
                "draft_id": draft.draft_id,
                "strategy_name": draft.strategy_name,
                "status": draft.status.value,
                "timeframe": draft.timeframe,
                "concepts": draft.concepts,
                "rules": rules_data,
                "missing_information": missing_data,
            }
        except Exception as exc:
            logger.error("Teaching extraction failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/teach/review")
    async def teach_review(req: TeachReviewRequest):
        reviewer_name = os.environ.get("ATSITS_OPERATOR_NAME") or "HumanOperator_Web"
        draft = teaching_registry.get_draft(req.draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail=f"Draft '{req.draft_id}' not found.")

        action_upper = req.action.upper()
        try:
            if action_upper == "APPROVE":
                approved_count = 0
                for r in list(draft.rules):
                    draft = teaching_review.approve_rule(
                        draft_id=draft.draft_id,
                        rule_id=r.rule_id,
                        reviewer=reviewer_name,
                        reason="Approved via ATSITS Web GUI",
                    )
                    approved_count += 1
                return {
                    "success": True,
                    "message": f"Successfully approved {approved_count} rules as {reviewer_name}.",
                    "status": "APPROVED",
                }

            elif action_upper == "CLARIFY":
                clarifications = req.clarifications or {}
                saved_count = 0
                for key, val in clarifications.items():
                    target_m = next(
                        (m for m in draft.missing_information if m.missing_id == key or m.item_name == key),
                        None,
                    )
                    if target_m:
                        draft = teaching_review.provide_clarification(
                            draft_id=draft.draft_id,
                            missing_id=target_m.missing_id,
                            resolution_value=val,
                            reviewer=reviewer_name,
                        )
                        saved_count += 1
                return {
                    "success": True,
                    "message": f"Saved clarifications for {saved_count} items.",
                    "status": "CLARIFIED",
                }

            elif action_upper == "REJECT":
                rejected = draft.model_copy(
                    update={"status": DraftStatus.REJECTED, "revision": draft.revision + 1}
                )
                teaching_registry.save_draft(rejected)
                return {
                    "success": True,
                    "message": f"Draft '{draft.draft_id}' marked as REJECTED.",
                    "status": "REJECTED",
                }

            elif action_upper == "VERIFY":
                verified = teaching_review.verify_draft(
                    draft_id=draft.draft_id,
                    reviewer=reviewer_name,
                )
                return {
                    "success": True,
                    "message": f"Strategy verified: {verified.strategy_spec.strategy_name} (v{verified.version})",
                    "status": verified.status.value,
                }

            else:
                raise HTTPException(status_code=400, detail=f"Unknown review action: '{req.action}'")

        except Exception as exc:
            return JSONResponse(status_code=400, content={"success": False, "message": str(exc)})

    # ------------------------------------------------------------------
    # API: Phase 9 — Binance Market Data (public, unauthenticated)
    # ------------------------------------------------------------------
    @app.get("/api/paper/market/status")
    async def paper_market_status(symbol: str = "BTCUSDT"):
        """Check Binance market connectivity and symbol status (unauthenticated)."""
        if paper_session is None:
            return {"binance_online": False, "paper_session_available": False,
                    "message": "Binance credentials not configured. Set BINANCE_API_KEY and BINANCE_API_SECRET in .env."}
        try:
            is_online = paper_session.binance_client.ping()
            server_time = paper_session.binance_client.get_server_time() if is_online else None
            return {
                "symbol": symbol.upper(),
                "binance_online": is_online,
                "paper_session_available": True,
                "server_time_ms": server_time,
                "session_id": paper_session.session_id,
            }
        except BinanceClientError as exc:
            return {"binance_online": False, "paper_session_available": True, "error": str(exc)}

    @app.get("/api/paper/market/price")
    async def paper_market_price(symbol: str = "BTCUSDT"):
        """Fetch current live price for a symbol (unauthenticated)."""
        if paper_session is None:
            return {"error": "Binance session not configured."}
        try:
            price = paper_session.binance_client.get_ticker_price(symbol)
            return {"symbol": symbol.upper(), "price": price, "fetched_at": datetime.now(timezone.utc).isoformat()}
        except BinanceClientError as exc:
            return {"symbol": symbol.upper(), "error": str(exc)}

    @app.get("/api/paper/market/candles")
    async def paper_market_candles(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 10):
        """Fetch recent completed klines from Binance (unauthenticated, max 100)."""
        if paper_session is None:
            return {"error": "Binance session not configured.", "candles": []}
        limit = max(1, min(limit, 100))
        try:
            candles = paper_session.binance_client.get_klines(symbol=symbol, interval=interval, limit=limit)
            return {"symbol": symbol.upper(), "interval": interval, "candles_count": len(candles), "candles": candles}
        except BinanceClientError as exc:
            return {"symbol": symbol.upper(), "error": str(exc), "candles": []}

    # ------------------------------------------------------------------
    # API: Phase 9 — Binance Account (authenticated, read-only)
    # ------------------------------------------------------------------
    @app.get("/api/paper/binance/account")
    async def binance_account_status():
        """Read-only Binance account metadata. No credentials in response."""
        if paper_session is None:
            return {"error": "Binance session not configured. Set BINANCE_API_KEY and BINANCE_API_SECRET in .env."}
        return paper_session.get_account_status()

    @app.get("/api/paper/binance/balances")
    async def binance_balances(hide_zero: bool = True):
        """Read-only Binance asset balances. NEVER used as paper equity."""
        if paper_session is None:
            return {"error": "Binance session not configured.", "balances": []}
        balances = paper_session.get_binance_balances(hide_zero=hide_zero)
        return {"balances": balances, "note": "Real Binance balances — read-only. Not connected to paper account equity."}

    # ------------------------------------------------------------------
    # API: Phase 9 — Paper Trading Session
    # ------------------------------------------------------------------
    @app.get("/api/paper/session")
    async def get_paper_session_route():
        """Return full paper session summary."""
        if paper_session is None:
            return {"paper_session_available": False,
                    "message": "Configure BINANCE_API_KEY and BINANCE_API_SECRET in .env to enable paper trading."}
        return paper_session.get_session_summary()

    @app.get("/api/paper/account")
    async def get_paper_account_route():
        """Return paper account state (synthetic equity, PnL, trade count)."""
        if paper_session is None:
            return {"paper_session_available": False, "message": "Binance session not configured."}
        return paper_session.get_paper_account()

    @app.get("/api/paper/positions")
    async def get_paper_positions_route():
        """Return active paper positions (0 or 1)."""
        if paper_session is None:
            return {"positions": [], "paper_session_available": False}
        return {"positions": paper_session.get_paper_positions()}

    @app.get("/api/paper/orders")
    async def get_paper_orders_route():
        """Return all paper orders in this session."""
        if paper_session is None:
            return {"orders": [], "paper_session_available": False}
        return {"orders": paper_session.get_paper_orders()}

    @app.get("/api/paper/trades")
    async def get_paper_trades_route(limit: int = 20):
        """Return completed paper trades (most recent first, max 100)."""
        if paper_session is None:
            return {"trades": [], "paper_session_available": False}
        limit = max(1, min(limit, 100))
        return {"trades": paper_session.get_paper_trades(limit=limit)}

    @app.post("/api/paper/order")
    async def place_paper_order_route(req: PaperOrderRequest):
        """Place a simulated paper market order.

        SECURITY: This NEVER places a real Binance order.
        Validates: side must be BUY or SELL, stop must be valid relative to current price.
        """
        if paper_session is None:
            raise HTTPException(status_code=503, detail="Binance session not configured.")

        side = req.side.upper()
        if side not in ("BUY", "SELL"):
            raise HTTPException(status_code=400, detail="side must be BUY or SELL.")

        result = paper_session.place_paper_order(
            side=side,
            quantity=req.quantity,
            stop_price=req.stop_price,
            target_price=req.target_price,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Order rejected."))
        return result

    @app.post("/api/paper/position/close")
    async def close_paper_position_route():
        """Manually close active paper position at current market price.

        SECURITY: This NEVER places a real Binance order.
        """
        if paper_session is None:
            raise HTTPException(status_code=503, detail="Binance session not configured.")
        result = paper_session.close_paper_position(reason="MANUAL_CLOSE")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Close failed."))
        return result

    return app
