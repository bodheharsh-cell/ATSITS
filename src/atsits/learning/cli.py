"""CLI commands for ATSITS Learning and Experiment Engine."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from atsits.data.loader import load_candles_from_csv
from atsits.engine.backtester import BacktestEngine
from atsits.learning.analyzer import PerformanceAnalyzer
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.models import (
    ExperimentSpec,
    Hypothesis,
    HypothesisStatus,
)
from atsits.learning.registry import ExperimentRegistry
from atsits.learning.reports import (
    format_metrics_table,
    generate_condition_analysis_report,
    generate_experiment_markdown_report,
)
from atsits.learning.runner import ExperimentRunner
from atsits.models.backtest import BacktestConfig
from atsits.strategies.ema_pullback import EMAPullbackStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="ATSITS Learning + Experiment Engine CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze performance and condition slices of a dataset")
    analyze_parser.add_argument("--data", default="data/btcusdt_1h.csv", help="Path to historical OHLCV CSV")
    analyze_parser.add_argument("--equity", type=float, default=10000.0, help="Initial equity")

    # 2. Hypothesis command
    hypo_parser = subparsers.add_parser("hypothesis", help="Manage research hypotheses")
    hypo_sub = hypo_parser.add_subparsers(dest="hypo_action", help="Hypothesis action")

    hypo_create = hypo_sub.add_parser("create", help="Create a new hypothesis")
    hypo_create.add_argument("--id", required=True, help="Unique hypothesis ID")
    hypo_create.add_argument("--desc", required=True, help="Description")
    hypo_create.add_argument("--change", required=True, help="Proposed change description")
    hypo_create.add_argument("--rationale", required=True, help="Rationale")
    hypo_create.add_argument("--expected", required=True, help="Expected effect")

    hypo_list = hypo_sub.add_parser("list", help="List all hypotheses")

    # 3. Experiment command
    exp_parser = subparsers.add_parser("run-experiment", help="Run a controlled experiment")
    exp_parser.add_argument("--id", required=True, help="Experiment ID")
    exp_parser.add_argument("--hypothesis-id", required=True, help="Hypothesis ID")
    exp_parser.add_argument("--candidate-version", required=True, help="Candidate strategy version identifier")
    exp_parser.add_argument("--candidate-params", required=True, help="JSON string of candidate parameter changes")
    exp_parser.add_argument("--data", default="data/btcusdt_1h.csv", help="Path to historical OHLCV CSV")
    exp_parser.add_argument("--is-ratio", type=float, default=0.7, help="In-sample ratio (default: 0.7)")

    # 4. View report command
    view_parser = subparsers.add_parser("view-report", help="View a recorded experiment report")
    view_parser.add_argument("--id", required=True, help="Experiment ID to view")

    args = parser.parse_args()

    if args.command == "analyze":
        candles = load_candles_from_csv(args.data)
        strategy = EMAPullbackStrategy()
        engine = BacktestEngine(strategy=strategy, config=BacktestConfig(initial_equity=args.equity))
        res = engine.run(candles)

        analyzer = PerformanceAnalyzer(initial_equity=args.equity)
        overall_metrics = analyzer.analyze_backtest(res)
        condition_slices = analyzer.analyze_conditions(res.trades, strategy_version=strategy.VERSION)

        print("\n" + "=" * 60)
        print("ATSITS HISTORICAL PERFORMANCE SUMMARY")
        print("=" * 60)
        print(format_metrics_table(overall_metrics))
        print("\n" + generate_condition_analysis_report(condition_slices, strategy_version=strategy.VERSION))

    elif args.command == "hypothesis":
        reg = HypothesisRegistry()
        if args.hypo_action == "create":
            hyp = Hypothesis(
                hypothesis_id=args.id,
                created_at=datetime.now(timezone.utc),
                source="human_research",
                description=args.desc,
                baseline_strategy_version="1.0.0",
                proposed_change=args.change,
                rationale=args.rationale,
                expected_effect=args.expected,
                status=HypothesisStatus.PROPOSED,
                created_by="human",
            )
            reg.register(hyp)
            print(f"Registered hypothesis: {hyp.hypothesis_id}")
        elif args.hypo_action == "list":
            hyps = reg.list_all()
            print(f"\nRegistered Hypotheses ({len(hyps)} total):")
            for h in hyps:
                print(f" - [{h.status.value}] {h.hypothesis_id}: {h.description} (Change: {h.proposed_change})")

    elif args.command == "run-experiment":
        try:
            cand_params = json.loads(args.candidate_params)
        except Exception as err:
            print(f"Invalid JSON for --candidate-params: {err}", file=sys.stderr)
            sys.exit(1)

        spec = ExperimentSpec(
            experiment_id=args.id,
            hypothesis_id=args.hypothesis_id,
            baseline_strategy_version="1.0.0",
            candidate_strategy_version=args.candidate_version,
            candidate_params=cand_params,
            dataset_id=Path(args.data).stem,
            data_path=args.data,
            is_ratio=args.is_ratio,
            created_at=datetime.now(timezone.utc),
        )

        runner = ExperimentRunner()
        result = runner.run_experiment(spec)

        reg = ExperimentRegistry()
        reg.record(result)

        report = generate_experiment_markdown_report(result)
        report_path = Path("data/experiments") / f"{result.experiment_id}_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        print("\n" + report)
        print(f"\nReport saved to: {report_path}")

    elif args.command == "view-report":
        reg = ExperimentRegistry()
        res = reg.get(args.id)
        if res is None:
            print(f"Experiment '{args.id}' not found.", file=sys.stderr)
            sys.exit(1)
        print(generate_experiment_markdown_report(res))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
