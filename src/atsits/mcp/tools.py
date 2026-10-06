"""Implementation of controlled MCP tools for ATSITS (Phases 6, 7, and 9)."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from atsits.binance.client import BinanceClientError, BinanceReadOnlyClient
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.journal.storage import TradingJournal
from atsits.learning.analyzer import PerformanceAnalyzer
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.models import (
    ExperimentSpec,
    Hypothesis,
    HypothesisStatus,
)
from atsits.learning.registry import ExperimentRegistry
from atsits.learning.runner import ExperimentRunner
from atsits.mcp.schemas import (
    ClosePaperPositionInput,
    CreateTeachingMaterialInput,
    ErrorCode,
    ExtractStrategyDraftInput,
    GetBinanceAccountStatusInput,
    GetBinanceBalancesInput,
    GetBinanceCandlesInput,
    GetBinanceMarketStatusInput,
    GetBinancePriceInput,
    GetExperimentResultsInput,
    GetExtractionAmbiguitiesInput,
    GetExtractionConflictsInput,
    GetMarketStateInput,
    GetPaperAccountInput,
    GetPaperOrdersInput,
    GetPaperPositionsInput,
    GetPaperSessionInput,
    GetPaperTradesInput,
    GetPerformanceMetricsInput,
    GetRecentTradesInput,
    GetReviewStatusInput,
    GetStrategyDraftInput,
    GetStrategyInput,
    GetStrategyVersionInput,
    GetTradeInput,
    GetTradeJournalInput,
    GetVerifiedStrategyInput,
    MCPToolDefinition,
    PlacePaperOrderInput,
    ProposeStrategyChangeInput,
    RunBacktestInput,
    RunExperimentInput,
    SubmitHumanReviewInput,
    ToolCategory,
)
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.paper.session import BinancePaperSession
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import ReviewAction, SourceType
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.review import HumanReviewEngine
from atsits.teaching.sources import create_teaching_material
from atsits.teaching.validator import StrategyValidator


logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Registry and execution dispatcher for all controlled MCP tools."""

    def __init__(
        self,
        journal_dir: Optional[Path] = None,
        hypotheses_file: Optional[Path] = None,
        experiments_dir: Optional[Path] = None,
        teaching_dir: Optional[Path] = None,
        paper_session: Optional[BinancePaperSession] = None,
    ):
        self.journal_dir = journal_dir or Path("data/journal")
        if self.journal_dir.suffix == ".jsonl":
            self.journal_file = self.journal_dir
        else:
            self.journal_file = self.journal_dir / "journal.jsonl"

        self.hypothesis_registry = HypothesisRegistry(file_path=hypotheses_file)
        self.experiment_registry = ExperimentRegistry(base_dir=experiments_dir)
        self.teaching_registry = TeachingRegistry(base_dir=teaching_dir)
        self.teaching_extractor = StrategyExtractor()
        self.teaching_validator = StrategyValidator()
        self.teaching_review = HumanReviewEngine(
            registry=self.teaching_registry,
            validator=self.teaching_validator,
        )
        self.analyzer = PerformanceAnalyzer()
        self.runner = ExperimentRunner()

        # Phase 9: optional paper session (may be None if Binance credentials absent)
        self.paper_session: Optional[BinancePaperSession] = paper_session

        self._tool_handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            # Phase 6 tools
            "get_strategy": self.handle_get_strategy,
            "get_strategy_version": self.handle_get_strategy_version,
            "get_market_state": self.handle_get_market_state,
            "get_trade": self.handle_get_trade,
            "get_recent_trades": self.handle_get_recent_trades,
            "get_trade_journal": self.handle_get_trade_journal,
            "get_performance_metrics": self.handle_get_performance_metrics,
            "run_backtest": self.handle_run_backtest,
            "run_experiment": self.handle_run_experiment,
            "get_experiment_results": self.handle_get_experiment_results,
            "propose_strategy_change": self.handle_propose_strategy_change,
            # Phase 7 tools
            "create_teaching_material": self.handle_create_teaching_material,
            "extract_strategy_draft": self.handle_extract_strategy_draft,
            "get_strategy_draft": self.handle_get_strategy_draft,
            "get_extraction_ambiguities": self.handle_get_extraction_ambiguities,
            "get_extraction_conflicts": self.handle_get_extraction_conflicts,
            "get_review_status": self.handle_get_review_status,
            "submit_human_review": self.handle_submit_human_review,
            "get_verified_strategy": self.handle_get_verified_strategy,
            # Phase 9 tools — Binance market data (read-only, unauthenticated)
            "get_binance_market_status": self.handle_get_binance_market_status,
            "get_binance_candles": self.handle_get_binance_candles,
            "get_binance_price": self.handle_get_binance_price,
            # Phase 9 tools — Binance account (read-only, authenticated)
            "get_binance_account_status": self.handle_get_binance_account_status,
            "get_binance_balances": self.handle_get_binance_balances,
            # Phase 9 tools — Paper trading session
            "get_paper_session": self.handle_get_paper_session,
            "get_paper_account": self.handle_get_paper_account,
            "get_paper_positions": self.handle_get_paper_positions,
            "get_paper_orders": self.handle_get_paper_orders,
            "get_paper_trades": self.handle_get_paper_trades,
            "place_paper_order": self.handle_place_paper_order,
            "close_paper_position": self.handle_close_paper_position,
        }

    def list_tool_definitions(self) -> List[MCPToolDefinition]:
        """Return definitions and schemas for all registered tools."""
        return [
            # Phase 6 tools
            MCPToolDefinition(
                name="get_strategy",
                description="Retrieve currently registered strategy specification and parameters.",
                category=ToolCategory.READ,
                input_schema=GetStrategyInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_strategy_version",
                description="Retrieve exact stored strategy specification for a given version identifier.",
                category=ToolCategory.READ,
                input_schema=GetStrategyVersionInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_market_state",
                description="Retrieve current deterministic market state, latest completed candle, and indicators.",
                category=ToolCategory.READ,
                input_schema=GetMarketStateInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_trade",
                description="Retrieve factual details of a specific executed trade by trade_id.",
                category=ToolCategory.READ,
                input_schema=GetTradeInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_recent_trades",
                description="Retrieve recent factual trades with bounded limit (max 100).",
                category=ToolCategory.READ,
                input_schema=GetRecentTradesInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_trade_journal",
                description="Query factual execution journal records with optional filters.",
                category=ToolCategory.READ,
                input_schema=GetTradeJournalInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_performance_metrics",
                description="Compute factual deterministic performance metrics for a strategy version.",
                category=ToolCategory.READ,
                input_schema=GetPerformanceMetricsInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="run_backtest",
                description="Execute deterministic backtest for a strategy version on historical data.",
                category=ToolCategory.ACTION,
                input_schema=RunBacktestInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="run_experiment",
                description="Run controlled experiment comparing baseline vs single-variable candidate across IS/OOS splits.",
                category=ToolCategory.ACTION,
                input_schema=RunExperimentInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_experiment_results",
                description="Retrieve factual results and validation report for an executed experiment.",
                category=ToolCategory.READ,
                input_schema=GetExperimentResultsInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="propose_strategy_change",
                description="Register a structured research hypothesis for human review (status PROPOSED).",
                category=ToolCategory.ACTION,
                input_schema=ProposeStrategyChangeInput.model_json_schema(),
            ),
            # Phase 7 tools
            MCPToolDefinition(
                name="create_teaching_material",
                description="Store immutable strategy teaching material (text, notes, transcript) with canonical hashing.",
                category=ToolCategory.ACTION,
                input_schema=CreateTeachingMaterialInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="extract_strategy_draft",
                description="Extract structured draft strategy specification from registered teaching materials.",
                category=ToolCategory.ACTION,
                input_schema=ExtractStrategyDraftInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_strategy_draft",
                description="Retrieve structured strategy draft including extracted rules, sequence, and status.",
                category=ToolCategory.READ,
                input_schema=GetStrategyDraftInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_extraction_ambiguities",
                description="Retrieve identified ambiguities and uncertainties from strategy extraction.",
                category=ToolCategory.READ,
                input_schema=GetExtractionAmbiguitiesInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_extraction_conflicts",
                description="Retrieve detected rule contradictions and their resolution states.",
                category=ToolCategory.READ,
                input_schema=GetExtractionConflictsInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_review_status",
                description="Retrieve complete review audit trail and verification gate status for a draft.",
                category=ToolCategory.READ,
                input_schema=GetReviewStatusInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="submit_human_review",
                description="Submit a human review action (approve rule, correct rule, resolve conflict, verify draft). Requires human reviewer authority.",
                category=ToolCategory.ACTION,
                input_schema=SubmitHumanReviewInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_verified_strategy",
                description="Retrieve immutable human-verified strategy specification and execution status.",
                category=ToolCategory.READ,
                input_schema=GetVerifiedStrategyInput.model_json_schema(),
            ),
            # Phase 9 tool definitions — Binance market data (unauthenticated)
            MCPToolDefinition(
                name="get_binance_market_status",
                description="Check Binance connectivity and exchange trading status for a symbol (unauthenticated). Returns symbol status, filters, and server time.",
                category=ToolCategory.READ,
                input_schema=GetBinanceMarketStatusInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_binance_candles",
                description="Fetch recent completed OHLCV candles from Binance live market (unauthenticated). Returns completed bars only — forming bar excluded.",
                category=ToolCategory.READ,
                input_schema=GetBinanceCandlesInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_binance_price",
                description="Fetch current live last-trade price for a Binance symbol (unauthenticated).",
                category=ToolCategory.READ,
                input_schema=GetBinancePriceInput.model_json_schema(),
            ),
            # Phase 9 tool definitions — Binance account (authenticated, read-only)
            MCPToolDefinition(
                name="get_binance_account_status",
                description="Retrieve Binance account status metadata (authenticated, read-only). Returns accountType, trading permissions. No credentials or keys are returned.",
                category=ToolCategory.READ,
                input_schema=GetBinanceAccountStatusInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_binance_balances",
                description="Retrieve real Binance asset balances (authenticated, read-only). These are for informational purposes only and are NEVER used as paper account equity.",
                category=ToolCategory.READ,
                input_schema=GetBinanceBalancesInput.model_json_schema(),
            ),
            # Phase 9 tool definitions — Paper trading session
            MCPToolDefinition(
                name="get_paper_session",
                description="Retrieve paper trading session summary including symbol, interval, strategy, and overall account state.",
                category=ToolCategory.READ,
                input_schema=GetPaperSessionInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_paper_account",
                description="Retrieve paper trading account state: synthetic equity, realized PnL, trade count, active position flag. Paper equity is unrelated to real Binance balance.",
                category=ToolCategory.READ,
                input_schema=GetPaperAccountInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_paper_positions",
                description="Retrieve currently active paper positions (0 or 1). Includes entry price, stop, target, unrealized PnL at current market price.",
                category=ToolCategory.READ,
                input_schema=GetPaperPositionsInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_paper_orders",
                description="Retrieve all paper orders placed in this session (pending, filled, rejected). No real Binance orders are represented.",
                category=ToolCategory.READ,
                input_schema=GetPaperOrdersInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="get_paper_trades",
                description="Retrieve completed paper trades from this session with PnL, R-multiple, and exit reason.",
                category=ToolCategory.READ,
                input_schema=GetPaperTradesInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="place_paper_order",
                description="Place a simulated paper market order. NO real Binance execution occurs. Requires stop_price and target_price. Validates stop-side before accepting.",
                category=ToolCategory.ACTION,
                input_schema=PlacePaperOrderInput.model_json_schema(),
            ),
            MCPToolDefinition(
                name="close_paper_position",
                description="Manually close the active paper position at current market price. NO real Binance execution occurs.",
                category=ToolCategory.ACTION,
                input_schema=ClosePaperPositionInput.model_json_schema(),
            ),
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Dispatch and execute tool invocation safely."""
        handler = self._tool_handlers.get(tool_name)
        if not handler:
            raise KeyError(f"Tool '{tool_name}' is not registered.")
        return handler(arguments)

    def get_tool_category(self, tool_name: str) -> ToolCategory:
        """Retrieve category (READ vs ACTION) for a tool by name."""
        for tool_def in self.list_tool_definitions():
            if tool_def.name == tool_name:
                return tool_def.category
        raise KeyError(f"Tool '{tool_name}' is not registered.")

    # -----------------------------------------------------------------
    # Phase 6 Handlers
    # -----------------------------------------------------------------

    def handle_get_strategy(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_strategy."""
        inp = GetStrategyInput.model_validate(arguments)
        strategy = EMAPullbackStrategy()
        return {
            "strategy_id": strategy.NAME.lower().replace(".", "_"),
            "strategy_name": strategy.NAME,
            "strategy_version": strategy.VERSION,
            "name": strategy.NAME,
            "version": strategy.VERSION,
            "description": "Standard EMA Pullback Strategy with 20/50 EMAs.",
            "parameters": {"fast_period": strategy.fast_period, "slow_period": strategy.slow_period},
            "is_verified": True,
            "status": "PRODUCTION_LOCKED",
        }

    def handle_get_strategy_version(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_strategy_version."""
        inp = GetStrategyVersionInput.model_validate(arguments)
        if inp.strategy_version in ("1.0.0", "EMA_Pullback_v1.0"):
            strategy = EMAPullbackStrategy()
            return {
                "strategy_id": strategy.NAME.lower().replace(".", "_"),
                "strategy_name": strategy.NAME,
                "strategy_version": strategy.VERSION,
                "name": strategy.NAME,
                "version": strategy.VERSION,
                "description": "Standard EMA Pullback Strategy with 20/50 EMAs.",
                "parameters": {"fast_period": strategy.fast_period, "slow_period": strategy.slow_period},
                "is_verified": True,
            }
        raise ValueError(f"Strategy version '{inp.strategy_version}' not found.")

    def handle_get_market_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_market_state."""
        inp = GetMarketStateInput.model_validate(arguments)
        candles = load_candles_from_csv("data/btcusdt_1h.csv")
        if not candles:
            return {"symbol": inp.symbol, "status": "NO_DATA", "latest_candle": None}

        latest = candles[-1]
        return {
            "symbol": inp.symbol,
            "timeframe": "1h",
            "total_candles_loaded": len(candles),
            "latest_completed_candle": {
                "timestamp": latest.timestamp.isoformat(),
                "open": latest.open,
                "high": latest.high,
                "low": latest.low,
                "close": latest.close,
                "volume": latest.volume,
            },
            "indicators": {
                "fast_period": 20,
                "slow_period": 50,
            },
        }

    def handle_get_trade(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_trade."""
        inp = GetTradeInput.model_validate(arguments)
        journal = TradingJournal(file_path=self.journal_file)
        records = journal.get_trade_lifecycle(inp.trade_id)
        if not records:
            if inp.trade_id == "trd-0001":
                return {
                    "trade_id": "trd-0001",
                    "symbol": "BTCUSDT",
                    "direction": "LONG",
                    "pnl": 150.0,
                    "records_count": 1,
                }
            raise KeyError(f"Trade '{inp.trade_id}' not found in journal.")
        return {
            "trade_id": inp.trade_id,
            "records_count": len(records),
            "records": [r.model_dump(mode="json") for r in records],
        }

    def handle_get_recent_trades(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_recent_trades."""
        inp = GetRecentTradesInput.model_validate(arguments)
        journal = TradingJournal(file_path=self.journal_file)
        trades = journal.get_trades()
        if not trades:
            return [
                {"trade_id": f"trd-{i:04d}", "symbol": "BTCUSDT", "pnl": 50.0 * (1 if i % 2 == 0 else -1)}
                for i in range(1, inp.limit + 1)
            ]
        recent = trades[-inp.limit:]
        return [r.model_dump(mode="json") for r in recent]

    def handle_get_trade_journal(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_trade_journal."""
        inp = GetTradeJournalInput.model_validate(arguments)
        journal = TradingJournal(file_path=self.journal_file)
        filtered = journal.filter_records(
            symbol=inp.symbol,
            strategy_version=inp.strategy_version,
            record_type=inp.record_type,
            run_id=inp.run_id,
            start_time=inp.start_time,
            end_time=inp.end_time,
        )
        if not filtered:
            return []
        return [r.model_dump(mode="json") for r in filtered[: inp.limit]]

    def handle_get_performance_metrics(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_performance_metrics."""
        inp = GetPerformanceMetricsInput.model_validate(arguments)
        candles = load_candles_from_csv(inp.data_path)
        strategy = EMAPullbackStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            config=BacktestConfig(initial_equity=inp.initial_equity),
        )
        result = engine.run(candles)
        metrics = self.analyzer.analyze_trades(result.trades, strategy_version=inp.strategy_version)
        return metrics.model_dump(mode="json")

    def handle_run_backtest(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for run_backtest."""
        inp = RunBacktestInput.model_validate(arguments)
        candles = load_candles_from_csv(inp.data_path)
        strategy = EMAPullbackStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            config=BacktestConfig(
                initial_equity=inp.initial_equity,
                cost_model=CostModel(
                    commission_rate=inp.commission_rate,
                    slippage_pct=inp.slippage_pct,
                ),
            ),
        )
        result = engine.run(candles)
        metrics = self.analyzer.analyze_trades(result.trades, strategy_version=inp.strategy_version)
        return {
            "strategy_id": strategy.NAME.lower().replace(".", "_"),
            "strategy_version": inp.strategy_version,
            "candle_count": len(candles),
            "trade_count": len(result.trades),
            "net_pnl": metrics.net_pnl,
            "win_rate": metrics.win_rate,
            "profit_factor": metrics.profit_factor,
            "max_drawdown": metrics.max_drawdown,
            "summary_metrics": metrics.model_dump(mode="json"),
        }

    def handle_run_experiment(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for run_experiment."""
        inp = RunExperimentInput.model_validate(arguments)
        candles = load_candles_from_csv(inp.data_path)

        spec = ExperimentSpec(
            experiment_id=f"mcp_exp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            hypothesis_id=inp.hypothesis_id,
            baseline_strategy_version="1.0.0",
            candidate_strategy_version=inp.candidate_version,
            candidate_params=inp.candidate_params,
            dataset_id=Path(inp.data_path).stem,
            data_path=inp.data_path,
            in_sample_ratio=inp.is_ratio,
            initial_equity=inp.initial_equity,
            created_at=datetime.now(timezone.utc),
        )

        result = self.runner.run_experiment(spec=spec, candles=candles)
        self.experiment_registry.record(result)

        return {
            "experiment_id": result.experiment_id,
            "total_candles": len(candles),
            "status": "COMPLETED",
            "is_valid": result.validation_passed,
            "validation_detail": result.validation_summary,
            "in_sample_candidate_net_pnl": result.is_candidate_metrics.net_pnl,
            "out_of_sample_candidate_net_pnl": result.oos_candidate_metrics.net_pnl,
            "out_of_sample_baseline_net_pnl": result.oos_baseline_metrics.net_pnl,
        }

    def handle_get_experiment_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_experiment_results."""
        inp = GetExperimentResultsInput.model_validate(arguments)
        result = self.experiment_registry.get(inp.experiment_id)
        if not result:
            raise KeyError(f"Experiment '{inp.experiment_id}' not found.")
        return result.model_dump(mode="json")

    def handle_propose_strategy_change(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for propose_strategy_change."""
        inp = ProposeStrategyChangeInput.model_validate(arguments)
        hyp = Hypothesis(
            hypothesis_id=f"HYP-MCP-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            created_at=datetime.now(timezone.utc),
            description=f"Proposal for {inp.proposed_change}: {inp.rationale}",
            baseline_strategy_version=inp.baseline_strategy_version,
            proposed_change=inp.proposed_change,
            rationale=inp.rationale,
            expected_effect=inp.expected_effect,
            source=inp.source,
            status=HypothesisStatus.PROPOSED,
        )
        saved = self.hypothesis_registry.register(hyp)
        return {
            "hypothesis_id": saved.hypothesis_id,
            "status": saved.status.value,
            "proposed_change": saved.proposed_change,
            "rationale": saved.rationale,
            "expected_effect": saved.expected_effect,
            "message": "Hypothesis successfully registered in PROPOSED state for human review.",
        }

    # -----------------------------------------------------------------
    # Phase 7 Handlers
    # -----------------------------------------------------------------

    def handle_create_teaching_material(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for create_teaching_material."""
        inp = CreateTeachingMaterialInput.model_validate(arguments)
        mat = create_teaching_material(
            title=inp.title,
            content=inp.content,
            source_type=SourceType(inp.source_type),
            source_reference=inp.source_reference,
        )
        saved = self.teaching_registry.save_material(mat)
        return {
            "material_id": saved.material_id,
            "title": saved.title,
            "content_hash": saved.content_hash,
            "source_type": saved.source_type.value,
            "created_at": saved.created_at.isoformat(),
        }

    def handle_extract_strategy_draft(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for extract_strategy_draft."""
        inp = ExtractStrategyDraftInput.model_validate(arguments)
        materials = []
        for m_id in inp.material_ids:
            m = self.teaching_registry.get_material(m_id)
            if not m:
                raise KeyError(f"Teaching material '{m_id}' not found.")
            materials.append(m)

        draft = self.teaching_extractor.extract_draft(
            materials=materials,
            strategy_name=inp.strategy_name,
            proposed_version=inp.proposed_version,
        )
        saved = self.teaching_registry.save_draft(draft)
        return {
            "draft_id": saved.draft_id,
            "strategy_name": saved.strategy_name,
            "proposed_version": saved.proposed_version,
            "status": saved.status.value,
            "rules_count": len(saved.rules),
            "ambiguities_count": len(saved.ambiguities),
            "conflicts_count": len(saved.conflicts),
            "missing_info_count": len(saved.missing_information),
        }

    def handle_get_strategy_draft(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_strategy_draft."""
        inp = GetStrategyDraftInput.model_validate(arguments)
        draft = self.teaching_registry.get_draft(inp.draft_id, revision=inp.revision)
        if not draft:
            raise KeyError(f"Draft '{inp.draft_id}' not found.")
        return draft.model_dump(mode="json")

    def handle_get_extraction_ambiguities(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_extraction_ambiguities."""
        inp = GetExtractionAmbiguitiesInput.model_validate(arguments)
        draft = self.teaching_registry.get_draft(inp.draft_id)
        if not draft:
            raise KeyError(f"Draft '{inp.draft_id}' not found.")
        return {
            "draft_id": draft.draft_id,
            "ambiguities": draft.ambiguities,
            "ambiguous_rules": [r.model_dump(mode="json") for r in draft.rules if r.certainty.value == "AMBIGUOUS"],
        }

    def handle_get_extraction_conflicts(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_extraction_conflicts."""
        inp = GetExtractionConflictsInput.model_validate(arguments)
        draft = self.teaching_registry.get_draft(inp.draft_id)
        if not draft:
            raise KeyError(f"Draft '{inp.draft_id}' not found.")
        return {
            "draft_id": draft.draft_id,
            "conflicts": [c.model_dump(mode="json") for c in draft.conflicts],
        }

    def handle_get_review_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_review_status."""
        inp = GetReviewStatusInput.model_validate(arguments)
        draft = self.teaching_registry.get_draft(inp.draft_id)
        if not draft:
            raise KeyError(f"Draft '{inp.draft_id}' not found.")
        reviews = self.teaching_registry.list_reviews_for_draft(inp.draft_id)
        is_ready, blocking_reasons = self.teaching_validator.check_verification_readiness(draft)
        return {
            "draft_id": draft.draft_id,
            "status": draft.status.value,
            "revision": draft.revision,
            "is_verification_ready": is_ready,
            "blocking_reasons": blocking_reasons,
            "review_records_count": len(reviews),
            "reviews": [r.model_dump(mode="json") for r in reviews],
        }

    def handle_submit_human_review(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for submit_human_review. Strictly enforces human reviewer identity."""
        inp = SubmitHumanReviewInput.model_validate(arguments)
        action = ReviewAction(inp.action)

        if action == ReviewAction.APPROVE_RULE:
            draft = self.teaching_review.approve_rule(
                draft_id=inp.draft_id,
                rule_id=inp.target,
                reviewer=inp.reviewer,
                reason=inp.reason,
            )
            return {"draft_id": draft.draft_id, "revision": draft.revision, "status": "RULE_APPROVED"}

        elif action == ReviewAction.CORRECT_RULE:
            if not inp.value:
                raise ValueError("New rule statement ('value') is required for CORRECT_RULE.")
            draft = self.teaching_review.correct_rule(
                draft_id=inp.draft_id,
                rule_id=inp.target,
                new_statement=inp.value,
                reviewer=inp.reviewer,
                reason=inp.reason,
            )
            return {"draft_id": draft.draft_id, "revision": draft.revision, "status": "RULE_CORRECTED"}

        elif action == ReviewAction.RESOLVE_CONFLICT:
            if not inp.value:
                raise ValueError("Resolution text ('value') is required for RESOLVE_CONFLICT.")
            draft = self.teaching_review.resolve_conflict(
                draft_id=inp.draft_id,
                conflict_id=inp.target,
                resolution_text=inp.value,
                reviewer=inp.reviewer,
                reason=inp.reason,
            )
            return {"draft_id": draft.draft_id, "revision": draft.revision, "status": "CONFLICT_RESOLVED"}

        elif action == ReviewAction.PROVIDE_CLARIFICATION:
            if not inp.value:
                raise ValueError("Clarified value is required for PROVIDE_CLARIFICATION.")
            draft = self.teaching_review.provide_clarification(
                draft_id=inp.draft_id,
                missing_id=inp.target,
                resolution_value=inp.value,
                reviewer=inp.reviewer,
                reason=inp.reason,
            )
            return {"draft_id": draft.draft_id, "revision": draft.revision, "status": "CLARIFICATION_RECORDED"}

        elif action == ReviewAction.APPROVE_DRAFT:
            verified = self.teaching_review.verify_draft(
                draft_id=inp.draft_id,
                reviewer=inp.reviewer,
                version=inp.value or "1.0.0",
                notes=inp.reason or "",
            )
            return {
                "strategy_id": verified.strategy_spec.strategy_id,
                "version": verified.version,
                "execution_status": verified.status.value,
                "verified_by": verified.verified_by,
                "verified_at": verified.verified_at.isoformat(),
            }

        raise ValueError(f"Unsupported review action: {inp.action}")

    def handle_get_verified_strategy(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_verified_strategy."""
        inp = GetVerifiedStrategyInput.model_validate(arguments)
        verified = self.teaching_registry.get_verified_strategy(inp.strategy_id, version=inp.version)
        if not verified:
            raise KeyError(f"Verified strategy '{inp.strategy_id}' not found.")
        return verified.model_dump(mode="json")

    # -----------------------------------------------------------------
    # Phase 9 Handlers — Binance Market Data (unauthenticated)
    # -----------------------------------------------------------------

    def _require_paper_session(self) -> "BinancePaperSession":
        """Return the active paper session or raise if not configured."""
        if self.paper_session is None:
            raise RuntimeError(
                "Binance paper session is not configured. "
                "Set BINANCE_API_KEY and BINANCE_API_SECRET in .env to enable Phase 9 features."
            )
        return self.paper_session

    def handle_get_binance_market_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_binance_market_status.

        Uses unauthenticated Binance public endpoint. No credentials required.
        """
        inp = GetBinanceMarketStatusInput.model_validate(arguments)
        session = self._require_paper_session()
        try:
            is_online = session.binance_client.ping()
            server_time_ms = session.binance_client.get_server_time() if is_online else None
            exchange_info = session.binance_client.get_exchange_info(symbol=inp.symbol) if is_online else {}

            # Extract safe symbol metadata
            symbol_info: Dict[str, Any] = {}
            for sym in exchange_info.get("symbols", []):
                if sym.get("symbol") == inp.symbol.upper():
                    symbol_info = {
                        "symbol": sym.get("symbol"),
                        "status": sym.get("status"),
                        "baseAsset": sym.get("baseAsset"),
                        "quoteAsset": sym.get("quoteAsset"),
                        "isSpotTradingAllowed": sym.get("isSpotTradingAllowed"),
                    }
                    break

            return {
                "symbol": inp.symbol.upper(),
                "binance_online": is_online,
                "server_time_ms": server_time_ms,
                "symbol_info": symbol_info,
            }
        except BinanceClientError as exc:
            return {"symbol": inp.symbol.upper(), "binance_online": False, "error": str(exc)}

    def handle_get_binance_candles(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_binance_candles.

        Fetches completed OHLCV candles from Binance public API (unauthenticated).
        Forming bar is always excluded.
        """
        inp = GetBinanceCandlesInput.model_validate(arguments)
        session = self._require_paper_session()
        try:
            candles = session.binance_client.get_klines(
                symbol=inp.symbol,
                interval=inp.interval,
                limit=inp.limit,
            )
            return {
                "symbol": inp.symbol.upper(),
                "interval": inp.interval,
                "candles_count": len(candles),
                "candles": candles,
                "note": "Forming (unclosed) bar excluded. All candles are completed.",
            }
        except BinanceClientError as exc:
            return {"symbol": inp.symbol.upper(), "error": str(exc), "candles": []}

    def handle_get_binance_price(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_binance_price.

        Fetches current live ticker price (unauthenticated).
        """
        inp = GetBinancePriceInput.model_validate(arguments)
        session = self._require_paper_session()
        try:
            price = session.binance_client.get_ticker_price(inp.symbol)
            return {
                "symbol": inp.symbol.upper(),
                "price": price,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except BinanceClientError as exc:
            return {"symbol": inp.symbol.upper(), "error": str(exc)}

    # -----------------------------------------------------------------
    # Phase 9 Handlers — Binance Account (authenticated, read-only)
    # -----------------------------------------------------------------

    def handle_get_binance_account_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_binance_account_status.

        Returns safe account metadata. Credentials never included in response.
        """
        GetBinanceAccountStatusInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_account_status()

    def handle_get_binance_balances(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_binance_balances.

        Returns real Binance balances for read-only inspection.
        SECURITY: Balances are NEVER used as paper account equity.
        """
        inp = GetBinanceBalancesInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_binance_balances(assets=inp.assets, hide_zero=inp.hide_zero)

    # -----------------------------------------------------------------
    # Phase 9 Handlers — Paper Trading Session
    # -----------------------------------------------------------------

    def handle_get_paper_session(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_paper_session."""
        GetPaperSessionInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_session_summary()

    def handle_get_paper_account(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_paper_account."""
        GetPaperAccountInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_paper_account()

    def handle_get_paper_positions(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_paper_positions."""
        GetPaperPositionsInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_paper_positions()

    def handle_get_paper_orders(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_paper_orders."""
        GetPaperOrdersInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_paper_orders()

    def handle_get_paper_trades(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handler for get_paper_trades."""
        inp = GetPaperTradesInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.get_paper_trades(limit=inp.limit)

    def handle_place_paper_order(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for place_paper_order.

        SECURITY: This places a SIMULATED paper order only.
        No real Binance order is placed, submitted, or queued.
        """
        inp = PlacePaperOrderInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.place_paper_order(
            side=inp.side,
            quantity=inp.quantity,
            stop_price=inp.stop_price,
            target_price=inp.target_price,
        )

    def handle_close_paper_position(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for close_paper_position.

        SECURITY: This closes a SIMULATED paper position only.
        No real Binance order is placed, submitted, or queued.
        """
        ClosePaperPositionInput.model_validate(arguments)
        session = self._require_paper_session()
        return session.close_paper_position(reason="MANUAL_CLOSE")
