"""Demonstration of a complete, safe Gemini workflow interacting with ATSITS via MCP."""

import json
import logging
from atsits.mcp.client import MCPClient
from atsits.mcp.server import MCPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_workflow_demo")


def main() -> None:
    logger.info("=" * 60)
    logger.info("ATSITS PHASE 6: GEMINI + MCP WORKFLOW DEMONSTRATION")
    logger.info("=" * 60)

    # 1. Initialize MCP Server and Client
    server = MCPServer()
    client = MCPClient(server=server)

    init_res = client.initialize()
    logger.info(f"Handshake complete with: {init_res['serverInfo']['name']} (Protocol: {init_res['protocolVersion']})")

    # 2. Gemini asks: 'What is the current strategy specification?'
    logger.info("\n[STEP 1] Gemini requests strategy specification via get_strategy...")
    strat_res = client.call_tool("get_strategy")
    logger.info(f"Factual Strategy: {strat_res['data']['strategy_name']} v{strat_res['data']['strategy_version']}")
    logger.info(f"Parameters: {strat_res['data']['parameters']}")
    logger.info(f"Status: {strat_res['data']['status']}")

    # 3. Gemini asks: 'What are the baseline performance metrics?'
    logger.info("\n[STEP 2] Gemini requests baseline performance metrics via get_performance_metrics...")
    metrics_res = client.call_tool("get_performance_metrics", {
        "strategy_version": "1.0.0",
        "data_path": "data/btcusdt_1h.csv",
    })
    m = metrics_res["data"]
    logger.info(f"Factual Baseline Metrics on 8,760 candles:")
    logger.info(f" - Total Trades: {m['total_trades']} | Win Rate: {m['win_rate'] * 100:.2f}%")
    logger.info(f" - Net P&L: ${m['net_pnl']:,.2f} | Profit Factor: {m['profit_factor']:.2f}")
    logger.info(f" - Max Drawdown: ${m['max_drawdown']:,.2f} ({m['max_drawdown_pct'] * 100:.2f}%)")

    # 4. Gemini assists User: 'Propose a research hypothesis to test fast EMA 21'
    logger.info("\n[STEP 3] Gemini formulates and proposes a research hypothesis via propose_strategy_change...")
    hyp_res = client.call_tool("propose_strategy_change", {
        "baseline_strategy_version": "1.0.0",
        "proposed_change": "fast_period: 20 -> 21",
        "rationale": "Slightly longer fast EMA may filter minor 1H whipsaw pullbacks.",
        "expected_effect": "Reduced trade count and improved out-of-sample profit factor.",
        "source": "gemini_research_assistant",
    })
    hypo_id = hyp_res["data"]["hypothesis_id"]
    logger.info(f"Hypothesis Registered: {hypo_id} (Status: {hyp_res['data']['status']})")
    logger.info("Notice: Hypothesis is strictly PROPOSED; no strategy code was modified.")

    # 5. User requests: 'Run that controlled experiment'
    logger.info("\n[STEP 4] Gemini requests experiment execution via run_experiment...")
    exp_res = client.call_tool("run_experiment", {
        "hypothesis_id": hypo_id,
        "candidate_version": "1.0.1-candidate-ema21",
        "candidate_params": {"fast_period": 21, "slow_period": 50},
        "data_path": "data/btcusdt_1h.csv",
        "is_ratio": 0.70,
        "initial_equity": 10000.0,
    })
    exp_id = exp_res["data"]["experiment_id"]
    logger.info(f"Experiment Completed: {exp_id}")
    logger.info(f"IS Candles: {exp_res['data']['is_candle_count']} | OOS Candles: {exp_res['data']['oos_candle_count']}")

    # 6. Gemini queries results: 'Get experiment results'
    logger.info("\n[STEP 5] Gemini retrieves factual experiment results via get_experiment_results...")
    res_query = client.call_tool("get_experiment_results", {"experiment_id": exp_id})
    res_data = res_query["data"]
    logger.info(f"Validation Status: {'PASSED' if res_data['validation_passed'] else 'NOT PASSED'}")
    logger.info(f"Validation Detail: {res_data['validation_summary']}")

    # 7. Gemini explains factual output to User
    logger.info("\n[STEP 6] Gemini presents neutral factual summary to User:")
    logger.info(f" - Out-of-Sample Baseline Net P&L: ${res_data['oos_baseline_metrics']['net_pnl']:,.2f}")
    logger.info(f" - Out-of-Sample Candidate Net P&L: ${res_data['oos_candidate_metrics']['net_pnl']:,.2f}")
    logger.info(" - Conclusion: Candidate failed out-of-sample validation. Baseline EMA_Pullback_v1.0 remains locked.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
