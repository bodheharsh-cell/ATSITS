"""ATSITS Phase 8 — ICT Strategy Integration Package.

This package provides infrastructure for representing, validating, and progressively
executing ICT (Inner Circle Trader) strategy concepts as verified through the Phase 7
Human Teaching Pipeline.

CRITICAL CONSTRAINT:
No concept definition, parameter, threshold, session time, lookback period, confirmation
rule, entry condition, invalidation condition, or target logic is assumed or invented here.
All such definitions MUST originate from human teaching material ingested through Phase 7.

Concepts without verified human-taught definitions remain:
  VERIFIED_BUT_NOT_EXECUTABLE  — concept recognized, structure defined, but no deterministic rule.
  UNRESOLVED                   — concept referenced but not yet defined at all.
"""

from atsits.strategies.ict.models import (
    ConceptCertainty,
    ConceptStatus,
    FVGDirection,
    FVGRecord,
    ICTConcept,
    ICTConceptCategory,
    ICTStrategySpec,
    LiquidityLevel,
    LiquidityType,
    SessionDefinition,
    SwingPoint,
    SwingPointType,
    TimeframeRole,
)
from atsits.strategies.ict.registry import ICTConceptRegistry
from atsits.strategies.ict.concepts import CONCEPT_CATALOG
from atsits.strategies.ict.validator import ICTConceptValidator
from atsits.strategies.ict.extractor import ICTConceptExtractor

__all__ = [
    # Models
    "ConceptCertainty",
    "ConceptStatus",
    "FVGDirection",
    "FVGRecord",
    "ICTConcept",
    "ICTConceptCategory",
    "ICTStrategySpec",
    "LiquidityLevel",
    "LiquidityType",
    "SessionDefinition",
    "SwingPoint",
    "SwingPointType",
    "TimeframeRole",
    # Core components
    "ICTConceptRegistry",
    "CONCEPT_CATALOG",
    "ICTConceptValidator",
    "ICTConceptExtractor",
]
