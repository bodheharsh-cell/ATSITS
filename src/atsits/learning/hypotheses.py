"""Hypothesis management and persistent registry."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Union
from atsits.learning.models import Hypothesis, HypothesisStatus


class HypothesisRegistry:
    """Local, append-only persistent storage for research hypotheses."""

    def __init__(self, file_path: Optional[Union[str, Path]] = None):
        if file_path is None:
            self.file_path = Path("data/hypotheses/hypotheses.jsonl").resolve()
        else:
            self.file_path = Path(file_path).resolve()

        self._hypotheses: Dict[str, Hypothesis] = {}
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if self.file_path.is_file():
            self._load()

    def _load(self) -> None:
        """Load registered hypotheses from file."""
        self._hypotheses.clear()
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    hyp = Hypothesis.model_validate_json(clean_line)
                    self._hypotheses[hyp.hypothesis_id] = hyp
                except Exception as err:
                    raise ValueError(f"Malformed hypothesis line #{line_idx} in '{self.file_path}': {err}") from err

    def register(self, hypothesis: Hypothesis) -> Hypothesis:
        """Register a new research hypothesis.

        Raises:
            ValueError: If a hypothesis with the same hypothesis_id already exists.
        """
        if hypothesis.hypothesis_id in self._hypotheses:
            raise ValueError(f"Hypothesis '{hypothesis.hypothesis_id}' is already registered.")

        self._hypotheses[hypothesis.hypothesis_id] = hypothesis
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(hypothesis.model_dump_json() + "\n")

        return hypothesis

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Retrieve hypothesis by its identifier."""
        return self._hypotheses.get(hypothesis_id)

    def list_all(self, status: Optional[HypothesisStatus] = None) -> List[Hypothesis]:
        """List all hypotheses, optionally filtered by status."""
        if status is None:
            return list(self._hypotheses.values())
        return [h for h in self._hypotheses.values() if h.status == status]

    def update_status(self, hypothesis_id: str, new_status: HypothesisStatus) -> Hypothesis:
        """Update the status of an existing hypothesis and append to record."""
        hyp = self._hypotheses.get(hypothesis_id)
        if hyp is None:
            raise KeyError(f"Hypothesis '{hypothesis_id}' not found.")

        # Create updated immutable model
        updated = Hypothesis(
            hypothesis_id=hyp.hypothesis_id,
            created_at=hyp.created_at,
            source=hyp.source,
            description=hyp.description,
            baseline_strategy_version=hyp.baseline_strategy_version,
            proposed_change=hyp.proposed_change,
            rationale=hyp.rationale,
            expected_effect=hyp.expected_effect,
            status=new_status,
            created_by=hyp.created_by,
        )

        self._hypotheses[hypothesis_id] = updated
        # Rewrite complete log to preserve latest status
        with open(self.file_path, "w", encoding="utf-8") as f:
            for h in self._hypotheses.values():
                f.write(h.model_dump_json() + "\n")

        return updated
