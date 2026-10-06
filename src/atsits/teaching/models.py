"""Data models for ATSITS Phase 7 Strategy Teaching & Verified Extraction."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.strategy import StrategySpec
from atsits.models.types import FrozenMapping


class SourceType(str, Enum):
    """Supported types of strategy teaching material."""

    TEXT = "TEXT"
    TRANSCRIPT = "TRANSCRIPT"
    NOTES = "NOTES"
    DOCUMENT = "DOCUMENT"
    EXAMPLE = "EXAMPLE"
    IMAGE = "IMAGE"
    CHART = "CHART"
    ANNOTATED_CHART = "ANNOTATED_CHART"
    OTHER = "OTHER"


class TeachingMaterial(BaseModel):
    """Immutable record of source teaching material provided by a human operator.

    Content is preserved immutably and identified by a deterministic canonical SHA-256 hash.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    material_id: str = Field(..., min_length=1, description="Unique identifier for the teaching material")
    source_type: SourceType = Field(..., description="Format or source classification of teaching material")
    title: str = Field(..., min_length=1, description="Descriptive title of the teaching material")
    content: str = Field(..., description="Raw text or representation of the teaching material")
    source_reference: Optional[str] = Field(
        default=None,
        description="External source attribution or reference if available (URL, book, author, etc.)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when material was registered",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Deterministic SHA-256 hash of canonicalized content",
    )
    version: str = Field(default="1.0.0", description="Material version string")
    metadata: FrozenMapping = Field(
        default_factory=dict,
        description="Immutable metadata dictionary associated with the material",
    )


class RuleCategory(str, Enum):
    """Categories classifying extracted strategy rules."""

    SETUP = "SETUP"
    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    RISK = "RISK"
    INVALIDATION = "INVALIDATION"
    FILTER = "FILTER"
    EXCEPTION = "EXCEPTION"
    SEQUENCE = "SEQUENCE"
    EXECUTION = "EXECUTION"
    OTHER = "OTHER"


class RuleCertainty(str, Enum):
    """Certainty level of an extracted rule."""

    EXPLICIT = "EXPLICIT"  # Directly and unambiguously stated in source
    INFERRED = "INFERRED"  # Reasonable deduction from context, but not directly stated
    AMBIGUOUS = "AMBIGUOUS"  # Multiple conflicting or vague interpretations possible
    MISSING = "MISSING"  # Rule required for deterministic execution is completely absent


class RuleStatus(str, Enum):
    """Status of an extracted rule in the review lifecycle."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


class ExtractedRule(BaseModel):
    """Structured rule extracted from teaching material with full source traceability."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule")
    category: RuleCategory = Field(..., description="Rule classification")
    statement: str = Field(..., min_length=1, description="Human-readable rule statement")
    structured_representation: Optional[FrozenMapping] = Field(
        default=None,
        description="Structured key-value representation of the rule logic",
    )
    source_material_id: str = Field(..., description="ID of source material containing the rule")
    source_reference: Optional[str] = Field(
        default=None,
        description="Exact location in source (section, paragraph, timestamp, or explicit note if unavailable)",
    )
    evidence: str = Field(
        ...,
        description="Exact excerpt, quote, or factual evidence from source material",
    )
    certainty: RuleCertainty = Field(..., description="Certainty classification of the extracted rule")
    status: RuleStatus = Field(default=RuleStatus.PROPOSED, description="Review status of the rule")


class ConflictStatus(str, Enum):
    """Resolution status of a detected rule conflict."""

    UNRESOLVED = "UNRESOLVED"
    RESOLVED_BY_HUMAN = "RESOLVED_BY_HUMAN"


class ConflictRecord(BaseModel):
    """Record of contradictory statements or rules identified in teaching material."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    conflict_id: str = Field(..., min_length=1, description="Unique identifier for the conflict")
    rule_a_id: str = Field(..., description="ID of first conflicting rule")
    rule_b_id: str = Field(..., description="ID of second conflicting rule")
    source_a: str = Field(..., description="Source location or reference for Rule A")
    source_b: str = Field(..., description="Source location or reference for Rule B")
    description: str = Field(..., description="Explanation of why Rule A and Rule B contradict")
    status: ConflictStatus = Field(
        default=ConflictStatus.UNRESOLVED,
        description="Resolution status",
    )
    resolution: Optional[str] = Field(
        default=None,
        description="Human explanation of how the conflict was resolved",
    )


class MissingInfoStatus(str, Enum):
    """Resolution status of a detected missing information item."""

    UNRESOLVED = "UNRESOLVED"
    RESOLVED_BY_HUMAN = "RESOLVED_BY_HUMAN"


class MissingInformationRecord(BaseModel):
    """Record of a parameter or condition required for deterministic execution that is absent."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    missing_id: str = Field(..., min_length=1, description="Unique identifier for missing item")
    item_name: str = Field(..., min_length=1, description="Name of missing specification item")
    description: str = Field(..., description="Detailed description of what is missing")
    critical: bool = Field(
        default=True,
        description="Whether this item is strictly required for deterministic execution",
    )
    status: MissingInfoStatus = Field(
        default=MissingInfoStatus.UNRESOLVED,
        description="Resolution status",
    )
    resolution: Optional[str] = Field(
        default=None,
        description="Value or clarification provided by human operator",
    )


class DraftStatus(str, Enum):
    """Status of a draft strategy in the extraction and review lifecycle."""

    DRAFT = "DRAFT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"


class DraftStrategy(BaseModel):
    """Structured draft representation of a strategy extracted from teaching material."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    draft_id: str = Field(..., min_length=1, description="Unique identifier for the draft")
    material_ids: List[str] = Field(..., min_length=1, description="List of source material IDs extracted from")
    strategy_name: str = Field(..., min_length=1, description="Name of the strategy")
    proposed_version: str = Field(default="1.0.0", description="Proposed version string")
    description: str = Field(default="", description="Detailed narrative description of the strategy")
    market_scope: str = Field(default="CRYPTO", description="Market scope (e.g. CRYPTO, FX, EQUITIES)")
    timeframe: Optional[str] = Field(default=None, description="Operating timeframe (e.g. 1H, 15m)")
    instruments: List[str] = Field(default_factory=list, description="Target trading instruments")
    concepts: List[str] = Field(default_factory=list, description="Core trading concepts identified")
    rules: List[ExtractedRule] = Field(default_factory=list, description="All extracted rules")
    entry_conditions: List[ExtractedRule] = Field(default_factory=list, description="Entry setup and trigger rules")
    exit_conditions: List[ExtractedRule] = Field(default_factory=list, description="Exit conditions")
    stop_loss: Optional[ExtractedRule] = Field(default=None, description="Stop loss definition rule")
    take_profit: Optional[ExtractedRule] = Field(default=None, description="Take profit definition rule")
    position_sizing: Optional[ExtractedRule] = Field(default=None, description="Position sizing rule")
    risk_rules: List[ExtractedRule] = Field(default_factory=list, description="Risk management rules")
    invalidation_rules: List[ExtractedRule] = Field(default_factory=list, description="Setup invalidation rules")
    filters: List[ExtractedRule] = Field(default_factory=list, description="Filter rules (trend, time, session)")
    exceptions: List[ExtractedRule] = Field(default_factory=list, description="Exception handling rules")
    sequencing: List[str] = Field(
        default_factory=list,
        description="Explicitly ordered execution sequence steps",
    )
    examples: List[str] = Field(default_factory=list, description="Extracted examples or walkthroughs")
    assumptions: List[str] = Field(default_factory=list, description="Explicitly stated assumptions")
    ambiguities: List[str] = Field(default_factory=list, description="Unresolved vague or ambiguous statements")
    conflicts: List[ConflictRecord] = Field(default_factory=list, description="Detected rule conflicts")
    missing_information: List[MissingInformationRecord] = Field(
        default_factory=list,
        description="Identified missing parameters required for deterministic execution",
    )
    extraction_notes: str = Field(default="", description="Extraction metadata, methodology, and notes")
    confidence_scores: FrozenMapping = Field(
        default_factory=dict,
        description="Itemized extraction confidence scores",
    )
    status: DraftStatus = Field(default=DraftStatus.DRAFT, description="Current lifecycle status")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Draft creation timestamp",
    )
    revision: int = Field(default=1, description="Sequential revision number of this draft")


class ReviewAction(str, Enum):
    """Actions that a human operator can perform during strategy review."""

    APPROVE_RULE = "APPROVE_RULE"
    REJECT_RULE = "REJECT_RULE"
    CORRECT_RULE = "CORRECT_RULE"
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    PROVIDE_CLARIFICATION = "PROVIDE_CLARIFICATION"
    APPROVE_DRAFT = "APPROVE_DRAFT"
    REJECT_DRAFT = "REJECT_DRAFT"


class ReviewRecord(BaseModel):
    """Immutable record of a human review action."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    review_id: str = Field(..., min_length=1, description="Unique identifier for the review action")
    draft_id: str = Field(..., min_length=1, description="Target draft identifier")
    reviewer: str = Field(..., min_length=1, description="Human reviewer identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of review action",
    )
    action: ReviewAction = Field(..., description="Action performed")
    target: str = Field(..., description="Target entity ID or field being reviewed")
    original_value: Optional[str] = Field(default=None, description="Original value before review")
    new_value: Optional[str] = Field(default=None, description="New value or correction provided by reviewer")
    reason: Optional[str] = Field(default=None, description="Explanation or rationale for review action")
    status: str = Field(default="COMPLETED", description="Outcome status of review record")


class StrategyExecutionStatus(str, Enum):
    """Execution status for human-verified strategy specifications."""

    VERIFIED_BUT_NOT_EXECUTABLE = "VERIFIED_BUT_NOT_EXECUTABLE"
    EXECUTABLE = "EXECUTABLE"
    PRODUCTION_LOCKED = "PRODUCTION_LOCKED"


class VerifiedStrategy(BaseModel):
    """A human-verified strategy specification with execution status and audit lineage."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_spec: StrategySpec = Field(..., description="Underlying deterministic StrategySpec")
    draft_id: str = Field(..., description="ID of draft strategy that was verified")
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of verification",
    )
    verified_by: str = Field(..., min_length=1, description="Human authority who verified the strategy")
    status: StrategyExecutionStatus = Field(..., description="Executability and production lock status")
    version: str = Field(..., min_length=1, description="Verified immutable strategy version")
    notes: str = Field(default="", description="Verification notes or execution constraints")
    source_materials: List[str] = Field(default_factory=list, description="List of source material IDs")
