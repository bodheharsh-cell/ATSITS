"""Factual experiment and performance reporting utilities."""

from typing import Dict, List, Optional
from atsits.learning.models import ConditionSlice, ExperimentResult, PerformanceMetrics


def format_metrics_table(metrics: PerformanceMetrics) -> str:
    """Format PerformanceMetrics into a readable Markdown table."""
    pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor is not None and metrics.profit_factor != float("inf") else ("inf" if metrics.profit_factor == float("inf") else "N/A")
    return f"""| Metric | Value |
| :--- | :--- |
| **Sample Size (Trades)** | {metrics.sample_size} |
| **Long Trades** | {metrics.long_trades} |
| **Short Trades** | {metrics.short_trades} |
| **Winning Trades** | {metrics.winning_trades} |
| **Losing Trades** | {metrics.losing_trades} |
| **Win Rate** | {metrics.win_rate * 100:.2f}% |
| **Gross Profit** | ${metrics.gross_profit:,.2f} |
| **Gross Loss** | ${metrics.gross_loss:,.2f} |
| **Net P&L** | ${metrics.net_pnl:,.2f} |
| **Profit Factor** | {pf_str} |
| **Average Trade P&L** | ${metrics.average_trade_pnl:,.2f} |
| **Average Winner** | ${metrics.average_winner:,.2f} |
| **Average Loser** | ${metrics.average_loser:,.2f} |
| **Max Drawdown** | ${metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct * 100:.2f}%) |
| **SL Exits / TP Exits / EOD** | {metrics.sl_exits} / {metrics.tp_exits} / {metrics.eod_exits} |
| **Total Realized R** | {metrics.total_r:.2f}R |
| **Average R** | {metrics.average_r:.3f}R |
| **Expectancy in R** | {metrics.expectancy_r:.3f}R |"""


def generate_experiment_markdown_report(result: ExperimentResult, hypothesis_desc: Optional[str] = None) -> str:
    """Generate a comprehensive human-readable Markdown report for an ExperimentResult."""
    is_start_str = result.is_start.isoformat() if result.is_start else "N/A"
    is_end_str = result.is_end.isoformat() if result.is_end else "N/A"
    oos_start_str = result.oos_start.isoformat() if result.oos_start else "N/A"
    oos_end_str = result.oos_end.isoformat() if result.oos_end else "N/A"

    diff_rows = []
    for k, diff in result.differences.items():
        rel_str = f"{diff.relative_diff_pct:+.2f}%" if diff.relative_diff_pct is not None else "N/A"
        diff_rows.append(f"| `{k}` | {diff.baseline_value:.2f} | {diff.candidate_value:.2f} | {diff.absolute_diff:+.2f} | {rel_str} |")
    diff_table = "\n".join(diff_rows)

    def _fmt_pf(pf: Optional[float]) -> str:
        if pf is None:
            return "N/A"
        if pf == float("inf"):
            return "inf"
        return f"{pf:.2f}"

    return f"""# ATSITS Experiment Report: {result.experiment_id}

## 1. Experiment Overview
- **Experiment ID**: `{result.experiment_id}`
- **Hypothesis ID**: `{result.hypothesis_id}`
- **Hypothesis Description**: {hypothesis_desc or "N/A"}
- **Baseline Strategy**: `{result.baseline_strategy_version}`
- **Candidate Strategy**: `{result.candidate_strategy_version}`
- **Candidate Parameter Changes**: `{result.candidate_params}`
- **Dataset ID**: `{result.dataset_id}` ({result.total_candles} total candles)
- **In-Sample Period**: {is_start_str} to {is_end_str} ({result.is_candle_count} candles)
- **Out-of-Sample Period**: {oos_start_str} to {oos_end_str} ({result.oos_candle_count} candles)
- **Execution Timestamp**: {result.created_at.isoformat()}

---

## 2. Out-of-Sample Performance Comparison

| Metric | Baseline ({result.baseline_strategy_version}) | Candidate ({result.candidate_strategy_version}) | Absolute Diff | Relative Diff (%) |
| :--- | :--- | :--- | :--- | :--- |
{diff_table}

---

## 3. Detailed In-Sample Metrics

### In-Sample Baseline
{format_metrics_table(result.is_baseline_metrics)}

### In-Sample Candidate
{format_metrics_table(result.is_candidate_metrics)}

---

## 4. Detailed Out-of-Sample Metrics

### Out-of-Sample Baseline
{format_metrics_table(result.oos_baseline_metrics)}

### Out-of-Sample Candidate
{format_metrics_table(result.oos_candidate_metrics)}

---

## 5. Validation Summary
- **Validation Status**: {"PASSED" if result.validation_passed else "NOT PASSED"}
- **Validation Detail**: {result.validation_summary}

---

## 6. Neutral Factual Interpretation
- Candidate strategy `{result.candidate_strategy_version}` produced an Out-of-Sample Net P&L of ${result.oos_candidate_metrics.net_pnl:,.2f} (vs Baseline ${result.oos_baseline_metrics.net_pnl:,.2f}) across {result.oos_candidate_metrics.sample_size} trades.
- Out-of-Sample Profit Factor: Candidate {_fmt_pf(result.oos_candidate_metrics.profit_factor)} vs Baseline {_fmt_pf(result.oos_baseline_metrics.profit_factor)}.
- Out-of-Sample Expectancy: Candidate {result.oos_candidate_metrics.expectancy_r:+.3f}R vs Baseline {result.oos_baseline_metrics.expectancy_r:+.3f}R.
- *Notice: Phase 5 does not autonomously promote or deploy strategies. Human review and approval remain mandatory.*
"""


def generate_condition_analysis_report(
    condition_slices: Dict[str, List[ConditionSlice]],
    strategy_version: str = "1.0.0",
) -> str:
    """Generate a Markdown report summarizing multidimensional condition slices."""
    def _fmt_pf(pf: Optional[float]) -> str:
        if pf is None:
            return "N/A"
        if pf == float("inf"):
            return "inf"
        return f"{pf:.2f}"

    sections = []
    for dimension, slices in condition_slices.items():
        rows = []
        for s in slices:
            rows.append(
                f"| `{s.condition_value}` | {s.sample_size} | {s.metrics.win_rate * 100:.1f}% | "
                f"${s.metrics.net_pnl:,.2f} | {_fmt_pf(s.metrics.profit_factor)} | {s.metrics.expectancy_r:+.3f}R |"
            )
        table_str = "\n".join(rows)
        section = f"""### Condition Dimension: `{dimension}`

| Slice Value | Trades | Win Rate | Net P&L | Profit Factor | Expectancy (R) |
| :--- | :--- | :--- | :--- | :--- | :--- |
{table_str}
"""
        sections.append(section)

    return f"""# ATSITS Condition Analysis Report (Strategy: {strategy_version})

{chr(10).join(sections)}
"""
