"""ATSITS Unified Interactive CLI and Operator Runtime (Phase 8.5)."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.gemini.client import GeminiClient
from atsits.gemini.config import (
    GeminiConfig,
    SUPPORTED_GEMINI_MODELS,
    load_gemini_config,
    persist_gemini_model,
    validate_model_id,
)
from atsits.gemini.exceptions import GeminiError, GeminiNotConfiguredError
from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.journal.models import TradeRecord
from atsits.journal.storage import TradingJournal
from atsits.learning.registry import ExperimentRegistry
from atsits.mcp.client import MCPClient
from atsits.mcp.permissions import PermissionLevel, PermissionPolicy
from atsits.mcp.server import MCPServer
from atsits.models.backtest import BacktestConfig, CostModel
from atsits.strategies.ema_pullback import EMAPullbackStrategy
from atsits.strategies.experimental_ema import EMAExperimentalStrategy
from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import DraftStatus, ReviewAction, SourceType
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.review import HumanReviewEngine
from atsits.teaching.sources import create_teaching_material
from atsits.teaching.validator import StrategyValidator

BANNER = r"""
======================================================================
  ATSITS -- Algorithmic Trading Strategy Iteration & Teaching System
             Deterministic Platform + Gemini Reasoning Runtime
======================================================================
"""


class ATSITSCLI:
    """Unified CLI Controller for ATSITS."""

    def __init__(
        self,
        gemini_config: Optional[GeminiConfig] = None,
        mcp_client: Optional[MCPClient] = None,
        data_path: Optional[Path] = None,
    ):
        self.config = gemini_config or load_gemini_config()
        self.gemini_client = GeminiClient(config=self.config)
        self.mcp_client = mcp_client or MCPClient()
        self.gemini_runtime = GeminiMCPRuntime(
            config=self.config,
            client=self.gemini_client,
            mcp_client=self.mcp_client,
        )

        self.data_path = data_path or (Path("data/btcusdt_1h.csv") if Path("data/btcusdt_1h.csv").exists() else Path("data/raw/BTCUSDT_1h.csv"))
        self.teaching_registry = TeachingRegistry()
        self.teaching_extractor = StrategyExtractor()
        self.teaching_validator = StrategyValidator()
        self.teaching_review = HumanReviewEngine(
            registry=self.teaching_registry,
            validator=self.teaching_validator,
        )
        self.experiment_registry = ExperimentRegistry()
        self.journal = TradingJournal(file_path=Path("data/journal/journal.jsonl"))

    # ------------------------------------------------------------------
    # Command: Status
    # ------------------------------------------------------------------
    def status(self) -> None:
        """Display complete system status, models, data, and Gemini connection."""
        print("\n--- ATSITS SYSTEM STATUS ---")
        print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Architecture: Phases 0-8.5 (Deterministic Engine + Gemini Runtime)")
        print(f"Authority: HUMAN OPERATOR (Mandatory Human Review Gate)")

        # Data status
        if self.data_path.exists():
            try:
                candles = load_candles_from_csv(self.data_path)
                print(f"Dataset: {self.data_path} ({len(candles):,} candles, {candles[0].timestamp.strftime('%Y-%m-%d')} to {candles[-1].timestamp.strftime('%Y-%m-%d')})")
            except Exception as e:
                print(f"Dataset: {self.data_path} (Error loading: {e})")
        else:
            print(f"Dataset: {self.data_path} (File not found)")

        # Strategies & Teaching
        print(f"Production Strategy: EMA_Pullback_v1.0 [PRODUCTION LOCKED]")
        verified = self.teaching_registry.list_verified_strategies()
        drafts = self.teaching_registry.list_drafts()
        materials = self.teaching_registry.list_materials()
        print(f"Teaching Pipeline: {len(materials)} materials, {len(drafts)} drafts, {len(verified)} verified strategies")

        # Experiments & Journal
        experiments = self.experiment_registry.list_all()
        print(f"Experiments: {len(experiments)} registered")
        trades = [r for r in self.journal.read_all() if isinstance(r, TradeRecord)]
        print(f"Journal: {len(trades)} trades recorded ({self.journal.count()} total journal events)")

        # MCP Tools
        tools = self.mcp_client.list_tools()
        print(f"MCP Server: {len(tools)} tools active (In-process)")

        # Gemini Configuration & Probe
        mode_str = getattr(self.gemini_runtime, "selection_mode", "AUTO")
        print(f"Gemini Mode: {mode_str} ({'Automatic Task-Aware Router' if mode_str == 'AUTO' else 'Manual Selection'})")
        print(f"Gemini Model: {self.config.display_name} ({self.config.model_name})")
        print(f"Gemini API Key: {self.config.masked_key}")
        print("Supported Gemini Models:")
        for m_id, info in SUPPORTED_GEMINI_MODELS.items():
            mark = "[*]" if m_id == self.config.model_name else "[ ]"
            status_flag = ""
            if hasattr(self.gemini_runtime, "router"):
                is_avail = self.gemini_runtime.router.health_tracker.is_available(m_id)
                status_flag = " [AVAILABLE]" if is_avail else " [COOLDOWN]"
            print(f"  {mark} {info.display_name:22} ({m_id}){status_flag}")
        if self.config.is_configured:
            print("Testing Gemini connection...", end=" ", flush=True)
            success, msg = self.gemini_client.test_connection()
            if success:
                print(f"[ONLINE] {msg}")
            else:
                print(f"[ERROR] {msg}")
        else:
            print("Gemini Status: [OFFLINE] (GEMINI_API_KEY not configured. Deterministic features fully active.)")
        print("----------------------------\n")

    def set_model(self, model_id: str, persist: bool = False) -> None:
        """Switch the active Gemini model or mode dynamically and optionally persist to .env."""
        clean_target = (model_id or "").strip()
        if clean_target.lower() in ("auto", "router", "default"):
            self.gemini_runtime.set_mode("AUTO")
            self.config = self.gemini_runtime.config
            self.gemini_client = self.gemini_runtime.client
            if persist:
                from atsits.gemini.config import persist_gemini_selection_mode
                persist_gemini_selection_mode("AUTO")
            print("Active Gemini mode set to: ⚡ AUTO (Automatic Task-Aware Model Router)")
            if persist:
                print("Configuration saved to .env")
            return

        clean_id = validate_model_id(clean_target)
        self.gemini_runtime.set_model(clean_id)
        self.config = self.gemini_runtime.config
        self.gemini_client = self.gemini_runtime.client
        if persist:
            persist_gemini_model(clean_id)
            from atsits.gemini.config import persist_gemini_selection_mode
            persist_gemini_selection_mode("MANUAL")
        print(f"Active Gemini model set to: {self.config.display_name} ({self.config.model_name})")
        if persist:
            print("Configuration saved to .env")


    # ------------------------------------------------------------------
    # Command: Backtest
    # ------------------------------------------------------------------
    def backtest(
        self,
        strategy_name: str = "EMA_Pullback_v1.0",
        initial_equity: float = 10000.0,
    ) -> None:
        """Run deterministic backtest on historical dataset."""
        print(f"\nRunning deterministic backtest for strategy: {strategy_name}...")
        if not self.data_path.exists():
            print(f"Error: Dataset not found at {self.data_path}")
            return

        candles = load_candles_from_csv(self.data_path)
        if strategy_name in ("EMA_Pullback_EMA20_30_3R", "EMA_Pullback_v1.1_exp", "EMA20_30_3R", "experimental"):
            strategy = EMAExperimentalStrategy()
        else:
            strategy = EMAPullbackStrategy()
        cfg = BacktestConfig(
            initial_equity=initial_equity,
            cost_model=CostModel(),
        )
        engine = BacktestEngine(config=cfg, strategy=strategy)
        results = engine.run(candles)

        print("\n--- BACKTEST EXECUTION RESULTS ---")
        print(f"Strategy:         {strategy_name}")
        print(f"Dataset:          {self.data_path.name} ({len(candles):,} candles)")
        print(f"Initial Equity:   ${results.initial_equity:,.2f}")
        print(f"Final Equity:     ${results.final_equity:,.2f}")
        print(f"Total Net PnL:    ${results.total_net_pnl:+,.2f}")
        print(f"Total Return:     {results.total_return_pct * 100:+.2f}%")
        print(f"Total Trades:     {results.number_of_trades}")
        print(f"Winning Trades:   {results.winning_trades}")
        print(f"Losing Trades:    {results.losing_trades}")
        print(f"Win Rate:         {results.win_rate * 100:.2f}%")
        print(f"Profit Factor:    {results.profit_factor:.2f}")
        print(f"Max Drawdown:     {results.max_drawdown_pct * 100:.2f}%")
        print(f"Average Trade:    ${results.average_trade_pnl:+,.2f}")
        print("----------------------------------\n")

    # ------------------------------------------------------------------
    # Command: Journal
    # ------------------------------------------------------------------
    def show_journal(self, limit: int = 10) -> None:
        """Display recent journal trades and metrics."""
        trades = [r for r in self.journal.read_all() if isinstance(r, TradeRecord)]
        print(f"\n--- TRADING JOURNAL ({len(trades)} total trades) ---")
        if not trades:
            print("No trades found in journal.")
            print("------------------------------------\n")
            return

        recent = trades[-limit:]
        print(f"{'Trade ID':<10} {'Entry Time':<20} {'Exit Time':<20} {'Dir':<6} {'Entry':<10} {'Exit':<10} {'PnL ($)':<10}")
        print("-" * 90)
        for t in reversed(recent):
            entry_str = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-"
            exit_str = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-"
            direction = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
            pnl_str = f"{t.realized_pnl:+,.2f}" if t.realized_pnl is not None else "-"
            print(f"{t.trade_id:<10} {entry_str:<20} {exit_str:<20} {direction:<6} {t.entry_price:<10.2f} {t.exit_price:<10.2f} {pnl_str:<10}")
        print("------------------------------------\n")

    # ------------------------------------------------------------------
    # Command: Experiments
    # ------------------------------------------------------------------
    def show_experiments(self) -> None:
        """Display registered learning experiments and hypotheses."""
        experiments = self.experiment_registry.list_all()
        print(f"\n--- EXPERIMENT REGISTRY ({len(experiments)} experiments) ---")
        if not experiments:
            print("No experiments found in registry.")
        else:
            for exp in experiments:
                print(f"  - ID: {exp.experiment_id} | Hypothesis: {exp.hypothesis_id} | Status: {exp.status.value}")
                print(f"    Baseline: {exp.baseline_strategy_version} | Candidate: {exp.candidate_strategy_version}")
        print("-----------------------------------------\n")

    # ------------------------------------------------------------------
    # Command: Strategy
    # ------------------------------------------------------------------
    def show_strategy(self, action: str = "list", target_id: Optional[str] = None) -> None:
        """Manage and view strategies and verification state."""
        if action == "list":
            print("\n--- STRATEGIES & DRAFTS ---")
            print("  * Production Strategy: EMA_Pullback_v1.0 (Locked baseline)")
            verified = self.teaching_registry.list_verified_strategies()
            print(f"\nVerified Strategies ({len(verified)}):")
            for v in verified:
                strat_name = getattr(v.strategy_spec, "strategy_name", v.strategy_spec.strategy_name if hasattr(v.strategy_spec, "strategy_name") else "Strategy")
                print(f"  - [{v.draft_id}] {strat_name} (v{v.version}) | Status: {v.status.value} | Verified by {v.verified_by}")

            drafts = self.teaching_registry.list_drafts()
            print(f"\nDraft Strategies ({len(drafts)}):")
            for d in drafts:
                print(f"  - [{d.draft_id}] {d.strategy_name} | Status: {d.status.value}")
            print("---------------------------\n")

        elif action == "show":
            if not target_id:
                print("Error: Specify strategy or draft ID to show. e.g. strategy show <id>")
                return
            draft = self.teaching_registry.get_draft(target_id)
            if draft:
                print(f"\n--- DRAFT STRATEGY: {draft.strategy_name} [{draft.draft_id}] ---")
                print(f"Status:       {draft.status.value}")
                print(f"Timeframe:    {draft.timeframe or 'Not specified'}")
                print(f"Concepts:     {', '.join(draft.concepts) if draft.concepts else 'None'}")
                print(f"Rules ({len(draft.rules)}):")
                for r in draft.rules:
                    print(f"  [{r.category.value}] {r.statement} (Certainty: {r.certainty.value}, Status: {r.status.value})")
                print(f"Missing Info ({len(draft.missing_information)}):")
                for m in draft.missing_information:
                    print(f"  - [{m.item_name}] {m.description} (Critical: {m.critical}, Status: {m.status.value})")
                print(f"Conflicts ({len(draft.conflicts)}):")
                for c in draft.conflicts:
                    print(f"  - {c.description} (Status: {c.status.value})")
                print("--------------------------------------------------\n")
                return

            verified_strat = self.teaching_registry.get_verified_strategy(target_id)
            if verified_strat:
                print(f"\n--- VERIFIED STRATEGY: {verified_strat.strategy_spec.strategy_name} [{verified_strat.draft_id}] ---")
                print(f"Version:      v{verified_strat.version}")
                print(f"Verified By:  {verified_strat.verified_by} at {verified_strat.verified_at}")
                print(f"Status:       {verified_strat.status.value}")
                print(f"Notes:        {verified_strat.notes}")
                print("------------------------------------------------------\n")
                return

            print(f"Strategy or Draft ID '{target_id}' not found.")

        elif action == "verify":
            if not target_id:
                print("Error: Specify draft ID to verify. e.g. strategy verify <draft_id>")
                return
            reviewer_name = os.environ.get("ATSITS_OPERATOR_NAME") or "HumanOperator_Harsh"
            print(f"Running Human Verification Gate on draft '{target_id}' as '{reviewer_name}'...")
            try:
                verified = self.teaching_review.verify_draft(
                    draft_id=target_id,
                    reviewer=reviewer_name,
                )
                print(f"[SUCCESS] Strategy verified: {verified.strategy_spec.strategy_name} (v{verified.version})")
                print(f"Execution Status: {verified.status.value}")
            except Exception as e:
                print(f"[REJECTED] Verification gate failed: {e}")

    # ------------------------------------------------------------------
    # Command: Teach (Interactive Teaching Pipeline)
    # ------------------------------------------------------------------
    def teach(
        self,
        teaching_text: Optional[str] = None,
        filepath: Optional[str] = None,
    ) -> None:
        """Execute the interactive Strategy Teaching Pipeline."""
        print("\n========================================================")
        print("          ATSITS STRATEGY TEACHING PIPELINE             ")
        print("========================================================")

        raw_text = teaching_text
        source_name = "Interactive CLI"

        if filepath:
            p = Path(filepath)
            if not p.is_file():
                print(f"Error: File not found at {filepath}")
                return
            with open(p, "r", encoding="utf-8") as f:
                raw_text = f.read()
            source_name = p.name
        elif not raw_text:
            print("Enter strategy notes / rules (Type 'END' on a new line when finished):")
            lines = []
            while True:
                try:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    break
            raw_text = "\n".join(lines).strip()

        if not raw_text:
            print("No teaching material provided. Aborting.")
            return

        print(f"\n[Step 1/5] Ingesting teaching material ({len(raw_text)} chars)...")
        material = create_teaching_material(
            title="CLI Strategy Teaching Material",
            content=raw_text,
            source_type=SourceType.TEXT,
            source_reference="Human Operator (CLI)",
        )
        self.teaching_registry.save_material(material)
        print(f"Material registered: ID={material.material_id}")

        print("\n[Step 2/5] Running deterministic Strategy Extraction...")
        draft = self.teaching_extractor.extract_draft(materials=[material])
        self.teaching_registry.save_draft(draft)
        print(f"Draft extracted: ID={draft.draft_id} | Name: {draft.strategy_name}")

        print("\n[Step 3/5] Extracted Strategy Draft Summary:")
        print(f"  - Strategy Name:    {draft.strategy_name}")
        print(f"  - Timeframe:        {draft.timeframe or 'Not specified'}")
        print(f"  - Concepts:         {', '.join(draft.concepts) if draft.concepts else 'None'}")
        print(f"  - Extracted Rules:  {len(draft.rules)}")
        for r in draft.rules:
            print(f"     * [{r.category.value}] {r.statement} (Certainty: {r.certainty.value})")
        print(f"  - Missing Items:    {len(draft.missing_information)}")
        for m in draft.missing_information:
            print(f"     * [{m.item_name}] {m.description}")
        print(f"  - Conflicts:        {len(draft.conflicts)}")
        for c in draft.conflicts:
            print(f"     * {c.description}")

        # Step 4: Gemini Analysis if available
        if self.config.is_configured:
            print("\n[Step 4/5] Consulting Gemini Reasoning Layer for recommendations...")
            try:
                def on_tool(name: str, args: dict, res: dict):
                    print(f"  [MCP Tool] {name}({args}) -> {'OK' if not res.get('is_error') else 'ERR'}")

                analysis = self.gemini_runtime.teach(
                    teaching_text=raw_text,
                    source_name=source_name,
                    on_tool_call=on_tool,
                )
                print("\n--- GEMINI REASONING FEEDBACK ---")
                print(analysis)
                print("---------------------------------")
            except Exception as e:
                print(f"Gemini analysis unavailable: {e}")
        else:
            print("\n[Step 4/5] Gemini reasoning skipped (offline mode).")

        # Step 5: Interactive Human Review Loop
        print("\n[Step 5/5] HUMAN OPERATOR REVIEW GATE (Mandatory Authority)")
        print("Choose an action:")
        print("  [A] Approve Rules      - Confirm and accept extracted rules")
        print("  [C] Clarify / Correct  - Provide clarifications for missing parameters")
        print("  [R] Reject Draft       - Discard draft")
        print("  [S] Skip               - Leave draft saved in current state")
        print("  [V] Verify Draft       - Run formal verification gate for execution readiness")

        reviewer_name = os.environ.get("ATSITS_OPERATOR_NAME") or "HumanOperator_Harsh"

        try:
            choice = input(f"\nEnter choice [A/C/R/S/V] (Operator: {reviewer_name}): ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            choice = "S"

        if choice == "A":
            approved_count = 0
            for r in draft.rules:
                self.teaching_review.approve_rule(
                    draft_id=draft.draft_id,
                    rule_id=r.rule_id,
                    reviewer=reviewer_name,
                    reason="Human operator confirmed rule in CLI",
                )
                approved_count += 1
            print(f"Successfully approved {approved_count} rules. Draft updated.")

        elif choice == "C":
            if draft.missing_information:
                print("\nUnresolved Missing Information:")
                for m in draft.missing_information:
                    print(f"  Item: {m.item_name} ({m.description})")
                    val = input(f"  Enter value/clarification for '{m.item_name}' (or leave blank to skip): ").strip()
                    if val:
                        self.teaching_review.provide_clarification(
                            draft_id=draft.draft_id,
                            missing_id=m.missing_id,
                            resolution_value=val,
                            reviewer=reviewer_name,
                        )
                        print(f"  Saved clarification for '{m.item_name}'.")
            else:
                print("No missing information records found to clarify.")

        elif choice == "R":
            reason = input("Rejection reason: ").strip() or "Rejected by human operator"
            rejected_draft = draft.model_copy(
                update={"status": DraftStatus.REJECTED, "revision": draft.revision + 1}
            )
            self.teaching_registry.save_draft(rejected_draft)
            print(f"Draft '{draft.draft_id}' marked as REJECTED.")

        elif choice == "V":
            try:
                verified = self.teaching_review.verify_draft(
                    draft_id=draft.draft_id,
                    reviewer=reviewer_name,
                )
                print(f"[SUCCESS] Strategy verified and locked: {verified.strategy_spec.strategy_name} (v{verified.version})")
                print(f"Executability Status: {verified.status.value}")
            except Exception as e:
                print(f"[REJECTED] Verification failed: {e}")

        else:
            print(f"Draft '{draft.draft_id}' preserved in registry for future review.")

    # ------------------------------------------------------------------
    # Command: Chat (Interactive Multi-Turn Gemini Reasoning)
    # ------------------------------------------------------------------
    def chat(self, initial_prompt: Optional[str] = None) -> None:
        """Start an interactive chat session with Gemini and MCP tools."""
        if not self.config.is_configured:
            print("\n[GEMINI OFFLINE] GEMINI_API_KEY is not configured.")
            print("To enable Gemini chat, set GEMINI_API_KEY in your environment or .env file.")
            print("Deterministic CLI commands (status, backtest, journal, teach, etc.) remain fully functional.\n")
            return

        print("\n--- ATSITS GEMINI INTELLIGENT CHAT ---")
        print("Type your message or query below. Type '/exit' or 'exit' to return.")
        print("Gemini will autonomously query ATSITS via MCP tools as needed.")
        print("--------------------------------------\n")

        def handle_tool(name: str, args: dict, res: dict):
            status_text = "OK" if not res.get("is_error") else f"ERROR: {res.get('error')}"
            print(f"  [MCP Tool] {name}({args}) -> {status_text}")

        if initial_prompt:
            print(f"\nHuman: {initial_prompt}")
            try:
                resp = self.gemini_runtime.send_message(initial_prompt, on_tool_call=handle_tool)
                print(f"\nATSITS Assistant:\n{resp}\n")
            except Exception as e:
                print(f"\nError: {e}\n")

        while True:
            try:
                user_msg = input("\nHuman: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting chat session.")
                break

            if not user_msg:
                continue
            if user_msg.lower() in ("exit", "quit", "/exit", "/quit"):
                print("Exiting chat session.")
                break
            if user_msg.lower() in ("/reset", "reset"):
                self.gemini_runtime.reset()
                print("Conversation history reset.")
                continue

            try:
                resp = self.gemini_runtime.send_message(user_msg, on_tool_call=handle_tool)
                print(f"\nATSITS Assistant:\n{resp}")
            except Exception as e:
                print(f"\nGemini error: {e}")

    # ------------------------------------------------------------------
    # Help & REPL
    # ------------------------------------------------------------------
    def help(self) -> None:
        """Print help information."""
        print("""
Available Commands:
  status               - Show system status, data, strategies, journal, and Gemini API status
  backtest             - Run deterministic backtest on historical dataset
  journal [limit]      - Show recent trade journal entries and statistics
  experiments          - View registered hypotheses and experiment runs
  strategy list        - List all registered strategies and drafts
  strategy show <id>   - Show details of a specific strategy or draft
  strategy verify <id> - Execute human verification gate on a strategy draft
  teach [text|file]    - Start the interactive Strategy Teaching & Extraction Pipeline
  chat [prompt]        - Start interactive reasoning chat with Gemini and ATSITS MCP tools
  help                 - Show this help message
  exit / quit          - Exit the CLI

Slash Commands (inside REPL or chat):
  /status, /backtest, /journal, /experiments, /strategy, /teach, /chat, /help, /exit
""")

    def repl(self) -> None:
        """Start the interactive ATSITS REPL shell."""
        print(BANNER)
        print("Type 'help' or '/help' for a list of available commands.")
        print("Type 'status' or '/status' to inspect system health.\n")

        while True:
            try:
                line = input("atsits> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting ATSITS.")
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            # Normalize slash commands
            if cmd.startswith("/"):
                cmd = cmd[1:]

            if cmd in ("exit", "quit"):
                print("Exiting ATSITS.")
                break
            elif cmd == "status":
                self.status()
            elif cmd == "backtest":
                strat = args[0] if args else "EMA_Pullback_v1.0"
                self.backtest(strategy_name=strat)
            elif cmd == "journal":
                limit = int(args[0]) if args and args[0].isdigit() else 10
                self.show_journal(limit=limit)
            elif cmd == "experiments":
                self.show_experiments()
            elif cmd == "strategy":
                sub = args[0] if args else "list"
                target = args[1] if len(args) > 1 else None
                self.show_strategy(action=sub, target_id=target)
            elif cmd == "teach":
                text = " ".join(args) if args else None
                self.teach(teaching_text=text)
            elif cmd == "chat":
                prompt = " ".join(args) if args else None
                self.chat(initial_prompt=prompt)
            elif cmd == "model":
                if args:
                    try:
                        self.set_model(args[0], persist=True)
                    except ValueError as e:
                        print(f"Error: {e}")
                else:
                    print(f"Current Gemini Model: {self.config.display_name} ({self.config.model_name})")
                    print("Supported Models:")
                    for m_id, info in SUPPORTED_GEMINI_MODELS.items():
                        mark = "[*]" if m_id == self.config.model_name else "[ ]"
                        print(f"  {mark} {m_id:24} - {info.display_name}")
            elif cmd in ("help", "?"):
                self.help()
            else:
                print(f"Unknown command: '{cmd}'. Type 'help' for available commands.")


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="atsits",
        description="ATSITS -- Algorithmic Trading Strategy Iteration & Teaching System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # status
    status_p = subparsers.add_parser("status", help="Show system status and component health")
    status_p.add_argument("--model", "-m", default=None, help="Gemini model ID to probe")

    # backtest
    bt_p = subparsers.add_parser("backtest", help="Run deterministic backtest")
    bt_p.add_argument("--strategy", default="EMA_Pullback_v1.0", help="Strategy version/name")
    bt_p.add_argument("--equity", type=float, default=10000.0, help="Initial equity")

    # journal
    j_p = subparsers.add_parser("journal", help="Show trading journal")
    j_p.add_argument("--limit", type=int, default=10, help="Number of trades to display")

    # experiments
    subparsers.add_parser("experiments", help="List registered hypotheses and experiments")

    # strategy
    strat_p = subparsers.add_parser("strategy", help="Strategy management")
    strat_p.add_argument("action", choices=["list", "show", "verify"], default="list", nargs="?")
    strat_p.add_argument("target_id", nargs="?", default=None, help="Strategy or Draft ID")

    # teach
    teach_p = subparsers.add_parser("teach", help="Strategy Teaching Pipeline")
    teach_p.add_argument("--file", "-f", default=None, help="Path to text/markdown file with strategy notes")
    teach_p.add_argument("--text", "-t", default=None, help="Inline strategy text")
    teach_p.add_argument("--model", "-m", default=None, help="Gemini model ID to use for extraction")

    # chat
    chat_p = subparsers.add_parser("chat", help="Intelligent Gemini chat with ATSITS MCP")
    chat_p.add_argument("prompt", nargs="*", default=None, help="Initial prompt")
    chat_p.add_argument("--model", "-m", default=None, help="Gemini model ID to use for this chat session")

    # web
    web_p = subparsers.add_parser("web", help="Start the ATSITS Local Web GUI")
    web_p.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    web_p.add_argument("--host", default="127.0.0.1", help="Host binding (default: 127.0.0.1)")

    # repl
    subparsers.add_parser("repl", help="Start interactive REPL shell")

    return parser


def main() -> None:
    """CLI Entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    cli = ATSITSCLI()

    # Apply command-line model override if provided
    if hasattr(args, "model") and args.model:
        try:
            cli.set_model(args.model)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    if args.command is None or args.command == "repl":
        cli.repl()
    elif args.command == "status":
        cli.status()
    elif args.command == "backtest":
        cli.backtest(strategy_name=args.strategy, initial_equity=args.equity)
    elif args.command == "journal":
        cli.show_journal(limit=args.limit)
    elif args.command == "experiments":
        cli.show_experiments()
    elif args.command == "strategy":
        cli.show_strategy(action=args.action, target_id=args.target_id)
    elif args.command == "teach":
        cli.teach(teaching_text=args.text, filepath=args.file)
    elif args.command == "chat":
        prompt_str = " ".join(args.prompt) if args.prompt else None
        cli.chat(initial_prompt=prompt_str)
    elif args.command == "web":
        from atsits.web.server import run_server
        run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
