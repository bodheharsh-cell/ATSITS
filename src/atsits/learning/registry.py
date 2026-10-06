"""Experiment Registry providing append-only persistence and retrieval for experiment records."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Union
from atsits.learning.models import ExperimentResult


class ExperimentRegistry:
    """Append-only persistent registry for ATSITS research experiments."""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        if base_dir is None:
            self.base_dir = Path("data/experiments").resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

        self.journal_file = self.base_dir / "experiments.jsonl"
        self._results: Dict[str, ExperimentResult] = {}
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if self.journal_file.is_file():
            self._load()

    def _load(self) -> None:
        """Load experiment results from journal file."""
        self._results.clear()
        with open(self.journal_file, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    res = ExperimentResult.model_validate_json(clean_line)
                    self._results[res.experiment_id] = res
                except Exception as err:
                    raise ValueError(f"Malformed experiment line #{line_idx} in '{self.journal_file}': {err}") from err

    def record(self, result: ExperimentResult) -> ExperimentResult:
        """Record an experiment result.

        Raises:
            ValueError: If an experiment with the same experiment_id is already recorded.
        """
        if result.experiment_id in self._results:
            raise ValueError(f"Experiment '{result.experiment_id}' is already recorded in the registry.")

        self._results[result.experiment_id] = result

        # 1. Append to journal file
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(result.model_dump_json() + "\n")

        # 2. Save standalone individual JSON result
        indiv_file = self.base_dir / f"{result.experiment_id}.json"
        with open(indiv_file, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json(indent=2) + "\n")

        return result

    def get(self, experiment_id: str) -> Optional[ExperimentResult]:
        """Retrieve an experiment result by identifier."""
        return self._results.get(experiment_id)

    def list_all(self) -> List[ExperimentResult]:
        """List all recorded experiment results."""
        return list(self._results.values())
