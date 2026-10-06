"""Append-only persistent registry for ICT concepts and ICT strategy specifications."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from atsits.strategies.ict.models import ICTConcept, ICTStrategySpec

logger = logging.getLogger(__name__)


class ICTConceptRegistry:
    """Manages append-only JSONL persistence for ICT concepts and strategy specs."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("data/ict")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.concepts_file = self.base_dir / "concepts.jsonl"
        self.strategies_file = self.base_dir / "strategies.jsonl"

    def save_concept(self, concept: ICTConcept) -> ICTConcept:
        """Append an ICT concept snapshot to the append-only log.

        Never overwrites previous versions; appends new revision snapshot.
        """
        data = concept.model_dump(mode="json")
        with open(self.concepts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        logger.debug("Saved ICT concept %s (v%s, status=%s)", concept.concept_id, concept.version, concept.status.value)
        return concept

    def get_concept(self, concept_id: str, version: Optional[str] = None) -> Optional[ICTConcept]:
        """Retrieve an ICT concept by concept_id.

        If version is None, returns the most recently appended version.
        """
        if not self.concepts_file.exists():
            return None

        matching: List[ICTConcept] = []
        with open(self.concepts_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("concept_id") == concept_id:
                    matching.append(ICTConcept.model_validate(record))

        if not matching:
            return None

        if version is not None:
            for c in matching:
                if c.version == version:
                    return c
            return None

        return matching[-1]

    def get_concept_versions(self, concept_id: str) -> List[ICTConcept]:
        """Retrieve complete chronological version history for an ICT concept."""
        if not self.concepts_file.exists():
            return []

        matching: List[ICTConcept] = []
        with open(self.concepts_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("concept_id") == concept_id:
                    matching.append(ICTConcept.model_validate(record))
        return matching

    def list_concepts(self) -> List[ICTConcept]:
        """List the latest version of all registered ICT concepts."""
        if not self.concepts_file.exists():
            return []

        concepts_by_id: Dict[str, ICTConcept] = {}
        with open(self.concepts_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = ICTConcept.model_validate(json.loads(line))
                concepts_by_id[c.concept_id] = c

        return list(concepts_by_id.values())

    def save_strategy_spec(self, spec: ICTStrategySpec) -> ICTStrategySpec:
        """Append an ICTStrategySpec snapshot to the append-only log."""
        data = spec.model_dump(mode="json")
        with open(self.strategies_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        logger.debug("Saved ICT strategy spec %s (v%s, verified=%s)", spec.strategy_id, spec.version, spec.is_verified)
        return spec

    def get_strategy_spec(self, strategy_id: str, version: Optional[str] = None) -> Optional[ICTStrategySpec]:
        """Retrieve an ICTStrategySpec by strategy_id and optional version."""
        if not self.strategies_file.exists():
            return None

        matching: List[ICTStrategySpec] = []
        with open(self.strategies_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("strategy_id") == strategy_id:
                    matching.append(ICTStrategySpec.model_validate(record))

        if not matching:
            return None

        if version is not None:
            for s in matching:
                if s.version == version:
                    return s
            return None

        return matching[-1]

    def get_strategy_spec_versions(self, strategy_id: str) -> List[ICTStrategySpec]:
        """Retrieve complete chronological version history for an ICT strategy specification."""
        if not self.strategies_file.exists():
            return []

        matching: List[ICTStrategySpec] = []
        with open(self.strategies_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("strategy_id") == strategy_id:
                    matching.append(ICTStrategySpec.model_validate(record))
        return matching

    def list_strategy_specs(self) -> List[ICTStrategySpec]:
        """List the latest version of all registered ICT strategy specs."""
        if not self.strategies_file.exists():
            return []

        specs_by_id: Dict[str, ICTStrategySpec] = {}
        with open(self.strategies_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                s = ICTStrategySpec.model_validate(json.loads(line))
                specs_by_id[s.strategy_id] = s

        return list(specs_by_id.values())
