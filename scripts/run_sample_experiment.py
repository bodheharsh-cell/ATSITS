"""Sample experiment execution script for ATSITS Phase 5."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.models import (
    ExperimentSpec,
    Hypothesis,
    HypothesisStatus,
)
from atsits.learning.registry import ExperimentRegistry
from atsits.learning.reports import generate_experiment_markdown_report
from atsits.learning.runner import ExperimentRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sample_experiment")


def main() -> None:
    logger.info("=" * 60)
    logger.info("ATSITS PHASE 5: RUNNING CONTROLLED SAMPLE EXPERIMENT")
    logger.info("=" * 60)

    # 1. Register a Research Hypothesis
    hypo_registry = HypothesisRegistry()
    hypo_id = "HYP-EMA-FAST-22"
    existing_hypo = hypo_registry.get(hypo_id)

    if existing_hypo is None:
        hypothesis = Hypothesis(
            hypothesis_id=hypo_id,
            created_at=datetime.now(timezone.utc),
            source="human_research",
            description="Testing whether increasing fast EMA period from 20 to 22 improves out-of-sample trend pullbacks on BTCUSDT 1H.",
            baseline_strategy_version="1.0.0",
            proposed_change="fast_period: 20 -> 22",
            rationale="A slightly longer fast EMA may smooth minor intrabar noise on 1H BTCUSDT pullbacks.",
            expected_effect="Modest reduction in false pullback triggers and reduced drawdown.",
            status=HypothesisStatus.TESTING,
            created_by="researcher_human",
        )
        hypo_registry.register(hypothesis)
        logger.info(f"Registered Hypothesis: {hypo_id}")
    else:
        hypothesis = existing_hypo
        logger.info(f"Loaded existing Hypothesis: {hypo_id}")

    # 2. Define Experiment Specification (70% IS / 30% OOS Chronological Split)
    exp_id = "EXP-2026-001"
    spec = ExperimentSpec(
        experiment_id=exp_id,
        hypothesis_id=hypo_id,
        baseline_strategy_version="1.0.0",
        candidate_strategy_version="1.0.1-candidate-ema22",
        candidate_params={"fast_period": 22, "slow_period": 50},
        dataset_id="btcusdt_1h_8760",
        data_path="data/btcusdt_1h.csv",
        initial_equity=10000.0,
        is_ratio=0.70,
        created_at=datetime.now(timezone.utc),
    )

    logger.info(f"Executing Experiment: {spec.experiment_id}")
    logger.info(f"Baseline: {spec.baseline_strategy_version} | Candidate: {spec.candidate_strategy_version}")
    logger.info(f"Data: {spec.data_path} | IS Ratio: {spec.is_ratio * 100:.0f}%")

    # 3. Run Experiment
    runner = ExperimentRunner(initial_equity=spec.initial_equity)
    result = runner.run_experiment(spec)

    # 4. Record Result in Append-Only Registry
    exp_registry = ExperimentRegistry()
    if exp_registry.get(exp_id) is None:
        exp_registry.record(result)
        logger.info(f"Recorded result in registry: {exp_id}")
    else:
        logger.info(f"Experiment {exp_id} already present in registry.")

    # 5. Generate and Output Factual Markdown Report
    report = generate_experiment_markdown_report(result, hypothesis_desc=hypothesis.description)
    report_file = Path("data/experiments") / f"{exp_id}_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Saved experiment report to: {report_file}")
    print("\n" + report)


if __name__ == "__main__":
    main()
