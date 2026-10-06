"""ATSITS Learning and Experiment Engine package."""

from atsits.learning.analyzer import PerformanceAnalyzer
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.metrics import calculate_performance_metrics
from atsits.learning.models import (
    ConditionSlice,
    ExperimentResult,
    ExperimentSpec,
    ExperimentStatus,
    Hypothesis,
    HypothesisStatus,
    MetricDifference,
    PerformanceMetrics,
)
from atsits.learning.registry import ExperimentRegistry
from atsits.learning.reports import (
    format_metrics_table,
    generate_condition_analysis_report,
    generate_experiment_markdown_report,
)
from atsits.learning.runner import (
    BASELINE_PARAMS,
    ExperimentRunner,
    validate_one_variable_change,
)

__all__ = [
    "BASELINE_PARAMS",
    "ConditionSlice",
    "ExperimentRegistry",
    "ExperimentResult",
    "ExperimentRunner",
    "ExperimentSpec",
    "ExperimentStatus",
    "Hypothesis",
    "HypothesisRegistry",
    "HypothesisStatus",
    "MetricDifference",
    "PerformanceAnalyzer",
    "PerformanceMetrics",
    "calculate_performance_metrics",
    "format_metrics_table",
    "generate_condition_analysis_report",
    "generate_experiment_markdown_report",
    "validate_one_variable_change",
]
