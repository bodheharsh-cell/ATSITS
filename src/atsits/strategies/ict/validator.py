"""Validation and executability verification engine for ICT concepts and strategy specs."""

from collections import defaultdict
import logging
from typing import Dict, List, Optional, Set, Tuple
from atsits.strategies.ict.models import (
    ConceptStatus,
    ICTConcept,
    ICTStrategySpec,
    is_valid_human_authority,
)
from atsits.strategies.ict.registry import ICTConceptRegistry

logger = logging.getLogger(__name__)


class ICTConceptValidator:
    """Validates ICT concept dependencies, cycle freedom, completeness, and executability boundaries."""

    def __init__(self, registry: Optional[ICTConceptRegistry] = None):
        self.registry = registry

    def validate_dependencies(
        self, concepts: List[ICTConcept]
    ) -> Tuple[bool, List[str]]:
        """Validate concept dependency graph for missing dependencies and circular references.

        Args:
            concepts: List of concepts to validate together.

        Returns:
            Tuple of (is_valid, list_of_error_messages).
        """
        errors: List[str] = []
        concept_map: Dict[str, ICTConcept] = {c.concept_id: c for c in concepts}

        # 1. Missing dependency check
        for c in concepts:
            for dep in c.dependencies:
                prereq_id = dep.to_concept_id
                if prereq_id not in concept_map:
                    # Check registry if available
                    if self.registry and self.registry.get_concept(prereq_id):
                        continue
                    errors.append(
                        f"Concept '{c.concept_id}' depends on '{prereq_id}', which is not registered or resolved."
                    )

        # 2. Cycle detection via Depth-First Search
        # Graph: from_concept_id -> [to_concept_id, ...]
        adj: Dict[str, List[str]] = defaultdict(list)
        for c in concepts:
            for dep in c.dependencies:
                adj[c.concept_id].append(dep.to_concept_id)

        # 0 = unvisited, 1 = visiting (on current stack), 2 = visited
        visited: Dict[str, int] = defaultdict(int)
        path: List[str] = []

        def dfs(node: str) -> None:
            visited[node] = 1
            path.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in concept_map:
                    continue
                if visited[neighbor] == 1:
                    # Cycle detected
                    cycle_start = path.index(neighbor)
                    cycle_nodes = " -> ".join(path[cycle_start:] + [neighbor])
                    errors.append(f"Circular dependency detected: {cycle_nodes}")
                elif visited[neighbor] == 0:
                    dfs(neighbor)
            path.pop()
            visited[node] = 2

        for node in concept_map:
            if visited[node] == 0:
                dfs(node)

        is_valid = len(errors) == 0
        return is_valid, errors

    def check_concept_executability(
        self, concept: ICTConcept
    ) -> Tuple[bool, List[str]]:
        """Evaluate whether an individual ICT concept is complete and ready for execution.

        Returns:
            Tuple of (is_executable, list_of_blocking_reasons).
        """
        blocking_reasons: List[str] = []

        # Check definition
        if not concept.definition or not concept.definition.strip():
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' lacks a deterministic definition from human teaching."
            )

        # Check parameters
        for p in concept.parameters:
            if not p.is_resolved:
                blocking_reasons.append(
                    f"Concept '{concept.concept_id}' has unresolved parameter: '{p.name}' ({p.description})."
                )

        # Check OHLCV representation
        if not concept.ohlcv_representation or not concept.ohlcv_representation.strip():
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' lacks explicit OHLCV candle mapping."
            )

        # Check lookahead safety
        if concept.lookahead_safe is not True:
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' has not been confirmed lookahead-safe."
            )

        # Check source traceability
        if not concept.source_material_ids:
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' lacks source material traceability (source_material_ids is empty)."
            )

        # Check human authority
        if not concept.human_verified_by or not concept.human_verified_by.strip():
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' lacks human verification record."
            )
        elif not is_valid_human_authority(concept.human_verified_by):
            blocking_reasons.append(
                f"Concept '{concept.concept_id}' human verification record '{concept.human_verified_by}' "
                "is invalid (cannot be an AI agent, automated system, or generic role label)."
            )

        # Check unresolved questions
        if concept.unresolved_questions:
            for q in concept.unresolved_questions:
                blocking_reasons.append(
                    f"Concept '{concept.concept_id}' has unanswered question: '{q}'."
                )

        # Check concept dependencies
        if concept.dependencies and self.registry:
            for dep in concept.dependencies:
                prereq = self.registry.get_concept(dep.to_concept_id)
                if not prereq:
                    blocking_reasons.append(
                        f"Concept '{concept.concept_id}' depends on '{dep.to_concept_id}' which is not registered."
                    )
                elif prereq.status != ConceptStatus.EXECUTABLE:
                    blocking_reasons.append(
                        f"Concept '{concept.concept_id}' depends on '{dep.to_concept_id}' which is not EXECUTABLE (status={prereq.status.value})."
                    )

        is_executable = len(blocking_reasons) == 0
        return is_executable, blocking_reasons

    def check_strategy_executability(
        self,
        spec: ICTStrategySpec,
        registry: Optional[ICTConceptRegistry] = None,
    ) -> Tuple[bool, List[str]]:
        """Evaluate whether a composed ICT StrategySpec is fully executable.

        Returns:
            Tuple of (is_executable, list_of_blocking_reasons).
        """
        reg = registry or self.registry
        blocking_reasons: List[str] = []

        # 1. Verification & human authority check
        if not spec.is_verified:
            blocking_reasons.append("Strategy specification has not received human verification.")
        if not spec.verified_by or not spec.verified_by.strip():
            blocking_reasons.append("Strategy specification lacks human verified_by identifier.")
        elif not is_valid_human_authority(spec.verified_by):
            blocking_reasons.append(
                f"Strategy specification human authority identifier '{spec.verified_by}' "
                "is invalid (cannot be an AI agent, automated system, or generic role label)."
            )

        # 2. Source traceability check
        if not spec.source_material_ids:
            blocking_reasons.append("Strategy specification lacks source material traceability (source_material_ids is empty).")

        # 3. Timeframe completeness check
        if not spec.timeframes or not spec.has_complete_timeframes:
            blocking_reasons.append("Strategy specification lacks assigned timeframes or has incomplete timeframe role assignments.")

        # 4. Session completeness check
        for s in spec.sessions:
            if s.enabled and not s.is_fully_defined:
                blocking_reasons.append(f"Enabled session '{s.name}' lacks complete timezone, start/end times, or applicable days.")

        # 5. Composition check
        if not spec.concept_ids:
            blocking_reasons.append("Strategy specification contains zero composed concepts.")

        # 6. Composed concept validity check
        composed_concepts: List[ICTConcept] = []
        for cid in spec.concept_ids:
            c = reg.get_concept(cid) if reg else None
            if not c:
                blocking_reasons.append(f"Referenced concept '{cid}' is not registered in ICT concept registry.")
            else:
                composed_concepts.append(c)
                is_exec, c_reasons = self.check_concept_executability(c)
                if not is_exec:
                    for r in c_reasons:
                        blocking_reasons.append(f"Composed concept '{cid}' is not executable: {r}")

        # 7. Dependency check among composed concepts
        if composed_concepts:
            is_dep_valid, dep_errors = self.validate_dependencies(composed_concepts)
            if not is_dep_valid:
                blocking_reasons.extend(dep_errors)

        # 8. Sequencing check
        if not spec.sequence_steps:
            blocking_reasons.append("Strategy specification lacks explicit execution sequencing steps.")

        # 9. Risk rule check
        if spec.risk_per_trade is None or spec.risk_per_trade <= 0:
            blocking_reasons.append("Strategy specification lacks valid risk_per_trade.")

        # 10. Unresolved items check
        if spec.unresolved_items:
            for item in spec.unresolved_items:
                blocking_reasons.append(f"Unresolved strategy item: '{item}'.")

        is_executable = len(blocking_reasons) == 0
        return is_executable, blocking_reasons
