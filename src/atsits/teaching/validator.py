"""Validation and executability verification engine for strategy drafts."""

import logging
from typing import Dict, List, Optional, Tuple
from atsits.models.strategy import StrategySpec
from atsits.teaching.models import (
    ConflictStatus,
    DraftStatus,
    DraftStrategy,
    MissingInfoStatus,
    RuleCertainty,
    StrategyExecutionStatus,
    VerifiedStrategy,
)

logger = logging.getLogger(__name__)


class StrategyValidator:
    """Evaluates draft completeness, verification gate prerequisites, and deterministic execution compatibility."""

    def __init__(self):
        pass

    def check_verification_readiness(self, draft: DraftStrategy) -> Tuple[bool, List[str]]:
        """Validate whether a draft meets all prerequisites for human verification.

        Returns:
            Tuple of (is_ready, list_of_blocking_reasons)
        """
        blocking_reasons: List[str] = []

        # Gate 1: Check for unresolved critical missing information
        for m in draft.missing_information:
            if m.critical and m.status == MissingInfoStatus.UNRESOLVED:
                blocking_reasons.append(f"Unresolved critical missing information: '{m.item_name}' ({m.description})")

        # Gate 2: Check for unresolved conflicts
        for c in draft.conflicts:
            if c.status == ConflictStatus.UNRESOLVED:
                blocking_reasons.append(f"Unresolved rule conflict: {c.description} (Rules {c.rule_a_id} vs {c.rule_b_id})")

        # Gate 3: Check for unresolved critical ambiguities
        for r in draft.rules:
            if r.certainty == RuleCertainty.AMBIGUOUS:
                blocking_reasons.append(f"Unresolved ambiguous rule: {r.rule_id} ('{r.statement}')")

        # Gate 4: Source traceability check for all rules
        for r in draft.rules:
            if not r.source_material_id:
                blocking_reasons.append(f"Rule {r.rule_id} lacks source material traceability.")
            if not r.evidence:
                blocking_reasons.append(f"Rule {r.rule_id} lacks source evidence/quote.")

        # Gate 5: Essential trading elements must be defined
        if not draft.entry_conditions:
            blocking_reasons.append("Draft lacks defined entry conditions.")
        if not draft.stop_loss and not any(m.item_name == "stop_loss" and m.status == MissingInfoStatus.RESOLVED_BY_HUMAN for m in draft.missing_information):
            blocking_reasons.append("Draft lacks defined stop loss specification.")

        is_ready = len(blocking_reasons) == 0
        return is_ready, blocking_reasons

    def evaluate_executability(self, draft: DraftStrategy) -> StrategyExecutionStatus:
        """Determine whether the verified strategy matches existing ATSITS deterministic execution capabilities.

        Distinguishes:
        - EXECUTABLE: Directly supported by deterministic engine (e.g. EMA pullback on 1H BTCUSDT).
        - VERIFIED_BUT_NOT_EXECUTABLE: Verified valid rules, but ATSITS does not yet possess deterministic executor logic for all components.
        """
        # Supported deterministic baseline: EMA Pullback
        has_ema = any("EMA" in c for c in draft.concepts)
        has_pullback = any("Pullback" in c for c in draft.concepts)
        has_confirmation = any("Confirmation" in c for c in draft.concepts)

        # Check for unsupported concepts (e.g., Fair Value Gap, Liquidity Sweep, Order Block)
        unsupported_concepts = {"Fair Value Gap", "Liquidity Sweep", "Order Block", "Break of Structure", "Market Structure Shift"}
        contains_unsupported = any(c in unsupported_concepts for c in draft.concepts)

        if contains_unsupported:
            logger.info("Strategy contains verified concepts without deterministic executor in Phase 7.")
            return StrategyExecutionStatus.VERIFIED_BUT_NOT_EXECUTABLE

        if has_ema and has_pullback and has_confirmation:
            return StrategyExecutionStatus.EXECUTABLE

        return StrategyExecutionStatus.VERIFIED_BUT_NOT_EXECUTABLE

    def build_strategy_spec(self, draft: DraftStrategy, version: str) -> StrategySpec:
        """Convert a verified draft into the standard ATSITS StrategySpec model.

        Extracts parameters deterministically without guessing or hallucinating.
        """
        params: Dict[str, Any] = {}

        # Extract parameters from rules or resolved missing info
        for r in draft.rules:
            if r.structured_representation:
                for k, v in r.structured_representation.items():
                    if k in ("fast", "slow", "risk_per_trade", "r_multiple"):
                        params[k] = v

        for m in draft.missing_information:
            if m.status == MissingInfoStatus.RESOLVED_BY_HUMAN and m.resolution:
                try:
                    if "." in m.resolution:
                        params[m.item_name] = float(m.resolution)
                    elif m.resolution.isdigit():
                        params[m.item_name] = int(m.resolution)
                    else:
                        params[m.item_name] = m.resolution
                except ValueError:
                    params[m.item_name] = m.resolution

        # Map fast/slow to standard keys if present
        if "fast" in params:
            params["fast_period"] = params.pop("fast")
        if "slow" in params:
            params["slow_period"] = params.pop("slow")

        return StrategySpec(
            strategy_id=draft.strategy_name.lower().replace(" ", "_"),
            name=draft.strategy_name,
            version=version,
            description=draft.description,
            parameters=params,
            is_verified=True,
        )
