"""ATSITS Phase 7: Strategy Teaching & Verified Strategy Extraction Package."""

from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import (
    ConflictRecord,
    ConflictStatus,
    DraftStatus,
    DraftStrategy,
    ExtractedRule,
    MissingInfoStatus,
    MissingInformationRecord,
    ReviewAction,
    ReviewRecord,
    RuleCategory,
    RuleCertainty,
    RuleStatus,
    SourceType,
    StrategyExecutionStatus,
    TeachingMaterial,
    VerifiedStrategy,
)
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.review import HumanReviewEngine
from atsits.teaching.sources import compute_canonical_content_hash, create_teaching_material
from atsits.teaching.validator import StrategyValidator

__all__ = [
    "SourceType",
    "TeachingMaterial",
    "RuleCategory",
    "RuleCertainty",
    "RuleStatus",
    "ExtractedRule",
    "ConflictStatus",
    "ConflictRecord",
    "MissingInfoStatus",
    "MissingInformationRecord",
    "DraftStatus",
    "DraftStrategy",
    "ReviewAction",
    "ReviewRecord",
    "StrategyExecutionStatus",
    "VerifiedStrategy",
    "TeachingRegistry",
    "StrategyExtractor",
    "StrategyValidator",
    "HumanReviewEngine",
    "compute_canonical_content_hash",
    "create_teaching_material",
]
