"""ICT concept and domain models for ATSITS Phase 8.

All models represent the STRUCTURE for holding ICT knowledge.
No actual ICT rules, thresholds, or definitions are encoded here.
Every field that represents a trading rule or threshold must be populated
exclusively from verified human teaching material via Phase 7.

Concept Lifecycle:
  UNDEFINED → TAUGHT → VERIFIED → DETERMINISTIC → EXECUTABLE

A concept cannot skip lifecycle stages. Promotion to EXECUTABLE requires:
  - Explicit deterministic definition (from human teaching)
  - All parameter values resolved (no MISSING or AMBIGUOUS items)
  - No unresolved dependencies
  - Lookahead-safe OHLCV representation confirmed
  - Human verification record on file
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from atsits.models.types import FrozenMapping


def is_valid_human_authority(identifier: Optional[str]) -> bool:
    """Validate that an identifier represents a legitimate, specific human operator.

    Rejects:
    - None or empty/whitespace
    - Known AI/automation keywords (gemini, ai, llm, system, auto, extractor, bot, agent)
    - Generic role labels (human, operator, user, person, reviewer, admin, anonymous)
    """
    if not identifier or not identifier.strip():
        return False
    ident_lower = identifier.strip().lower()
    ai_keywords = ("gemini", "ai", "llm", "system", "auto", "extractor", "bot", "agent")
    if any(kw in ident_lower for kw in ai_keywords):
        return False
    generic_labels = {"human", "operator", "user", "person", "reviewer", "admin", "anonymous"}
    if ident_lower in generic_labels:
        return False
    return True


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ICTConceptCategory(str, Enum):
    """Category labels for ICT concept types.

    These are structural categories only. They do NOT define what each concept
    means. Definitions must come from human teaching material.
    """

    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    LIQUIDITY = "LIQUIDITY"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    DISPLACEMENT = "DISPLACEMENT"
    FAIR_VALUE_GAP = "FAIR_VALUE_GAP"
    ORDER_BLOCK = "ORDER_BLOCK"
    BREAK_OF_STRUCTURE = "BREAK_OF_STRUCTURE"
    MARKET_STRUCTURE_SHIFT = "MARKET_STRUCTURE_SHIFT"
    PREMIUM = "PREMIUM"
    DISCOUNT = "DISCOUNT"
    DEALING_RANGE = "DEALING_RANGE"
    SESSION = "SESSION"
    ENTRY_MODEL = "ENTRY_MODEL"
    INVALIDATION = "INVALIDATION"
    TARGET = "TARGET"
    RISK = "RISK"
    OTHER = "OTHER"


class ConceptStatus(str, Enum):
    """Lifecycle status of an ICT concept in the teaching → execution pipeline.

    Stages must be traversed in order:
      UNDEFINED → TAUGHT → VERIFIED → DETERMINISTIC → EXECUTABLE

    SUSPENDED: Concept was previously advanced but has been suspended pending
    clarification or correction (e.g., new teaching material conflicts).
    """

    UNDEFINED = "UNDEFINED"
    TAUGHT = "TAUGHT"
    VERIFIED = "VERIFIED"
    DETERMINISTIC = "DETERMINISTIC"
    EXECUTABLE = "EXECUTABLE"
    SUSPENDED = "SUSPENDED"


class ConceptCertainty(str, Enum):
    """Certainty level of the concept definition as extracted from teaching material."""

    EXPLICIT = "EXPLICIT"       # Directly and unambiguously stated
    INFERRED = "INFERRED"       # Reasonable deduction but not directly stated
    AMBIGUOUS = "AMBIGUOUS"     # Multiple competing interpretations possible
    MISSING = "MISSING"         # Required for execution but absent from teaching


class TimeframeRole(str, Enum):
    """Role a timeframe plays in a multi-timeframe ICT strategy.

    Exact timeframe values (e.g., '4H', '15m') must be taught by the human operator.
    This enum defines only the structural ROLE, not the specific timeframe.
    """

    HIGHER_TIMEFRAME = "HIGHER_TIMEFRAME"       # Context / bias / structure
    EXECUTION_TIMEFRAME = "EXECUTION_TIMEFRAME" # Trade setup detection
    ENTRY_TIMEFRAME = "ENTRY_TIMEFRAME"         # Precise entry trigger
    UNASSIGNED = "UNASSIGNED"                   # Role not yet taught


class SwingPointType(str, Enum):
    """Structural classification of a swing point.

    What specifically constitutes a swing high or swing low
    (lookback period, wick vs body, etc.) must be defined by human teaching.
    """

    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"


class FVGDirection(str, Enum):
    """Directional classification of a Fair Value Gap.

    The exact three-candle formation conditions must be taught.
    """

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class LiquidityType(str, Enum):
    """Classification of liquidity level types.

    These are structural categories only. Which types are relevant
    and how each is defined must come from human teaching material.
    """

    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"
    PREVIOUS_HIGH = "PREVIOUS_HIGH"
    PREVIOUS_LOW = "PREVIOUS_LOW"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    EXTERNAL = "EXTERNAL"
    INTERNAL = "INTERNAL"
    UNSPECIFIED = "UNSPECIFIED"


# ---------------------------------------------------------------------------
# Core ICT Concept Model
# ---------------------------------------------------------------------------


class ICTConceptParameter(BaseModel):
    """A single named parameter within an ICT concept definition.

    Parameters must originate from human teaching. Values are optional
    until resolved through the teaching pipeline.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    param_id: str = Field(..., min_length=1, description="Parameter identifier")
    name: str = Field(..., min_length=1, description="Human-readable parameter name")
    description: str = Field(..., description="What this parameter controls or defines")
    value: Optional[Any] = Field(
        default=None,
        description="Resolved value. None = UNRESOLVED (requires human teaching)",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty of this parameter's value",
    )
    source_material_id: Optional[str] = Field(
        default=None,
        description="ID of teaching material that defined this parameter",
    )
    resolution_note: Optional[str] = Field(
        default=None,
        description="Human explanation of how this parameter was resolved",
    )

    @property
    def is_resolved(self) -> bool:
        """True only if the parameter has an explicit, non-ambiguous value."""
        return (
            self.value is not None
            and self.certainty in (ConceptCertainty.EXPLICIT, ConceptCertainty.INFERRED)
        )


class ConceptDependency(BaseModel):
    """Declares a dependency from one concept to another.

    Dependencies must be taught — not assumed from generic ICT knowledge.
    """

    model_config = ConfigDict(frozen=True)

    from_concept_id: str = Field(..., description="Dependent concept ID")
    to_concept_id: str = Field(..., description="Prerequisite concept ID")
    relationship: str = Field(
        ...,
        description="Nature of the dependency (e.g., 'requires', 'follows', 'confirms')",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.AMBIGUOUS,
        description="Certainty of this dependency relationship",
    )
    source_material_id: Optional[str] = Field(
        default=None,
        description="Teaching material that established this dependency",
    )


class ICTConcept(BaseModel):
    """Structured representation of a single ICT trading concept.

    Progresses through ConceptStatus lifecycle:
      UNDEFINED → TAUGHT → VERIFIED → DETERMINISTIC → EXECUTABLE

    An ICTConcept is NOT executable until all of the following hold:
      - status == EXECUTABLE
      - all parameters are resolved (is_resolved == True for all)
      - no unresolved dependencies
      - ohlcv_representation is present
      - lookahead_safe == True
      - human_verified_by is set

    DO NOT invent definitions. Every field that represents a trading rule,
    threshold, or condition must be populated from human teaching material.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    concept_id: str = Field(..., min_length=1, description="Unique concept identifier")
    category: ICTConceptCategory = Field(..., description="Structural category of concept")
    name: str = Field(..., min_length=1, description="Human-readable concept name")
    description: str = Field(
        default="",
        description="Structural description (what this concept COULD mean — not its actual definition)",
    )
    definition: Optional[str] = Field(
        default=None,
        description="Explicit deterministic definition — populated ONLY from human teaching",
    )
    parameters: List[ICTConceptParameter] = Field(
        default_factory=list,
        description="Named parameters governing this concept's deterministic behavior",
    )
    dependencies: List[ConceptDependency] = Field(
        default_factory=list,
        description="Ordered prerequisite concepts",
    )
    source_material_ids: List[str] = Field(
        default_factory=list,
        description="Teaching material IDs that contributed to this concept",
    )
    source_evidence: Optional[str] = Field(
        default=None,
        description="Direct quote or excerpt from teaching material",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty of the overall concept definition",
    )
    status: ConceptStatus = Field(
        default=ConceptStatus.UNDEFINED,
        description="Lifecycle status",
    )
    ohlcv_representation: Optional[str] = Field(
        default=None,
        description=(
            "Precise deterministic description of how this concept maps to OHLCV candle data. "
            "Must be explicit, unambiguous, and lookahead-free. "
            "REQUIRED before status can advance to DETERMINISTIC or EXECUTABLE."
        ),
    )
    lookahead_safe: Optional[bool] = Field(
        default=None,
        description=(
            "Explicitly confirmed to be free of lookahead bias. "
            "None = not yet verified. Must be True for EXECUTABLE status."
        ),
    )
    human_verified_by: Optional[str] = Field(
        default=None,
        description="Human operator who verified this concept",
    )
    human_verified_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of human verification",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Concept creation timestamp",
    )
    version: str = Field(default="0.1.0", description="Concept version string")
    unresolved_questions: List[str] = Field(
        default_factory=list,
        description=(
            "Explicit list of questions that must be answered by human teaching "
            "before this concept can advance to DETERMINISTIC status. "
            "These are generated by the system — NOT invented trading rules."
        ),
    )
    metadata: FrozenMapping = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    @property
    def is_executable(self) -> bool:
        """True only when ALL execution requirements are satisfied."""
        return (
            self.status == ConceptStatus.EXECUTABLE
            and self.definition is not None
            and self.ohlcv_representation is not None
            and self.lookahead_safe is True
            and is_valid_human_authority(self.human_verified_by)
            and len(self.source_material_ids) > 0
            and len(self.unresolved_questions) == 0
            and all(p.is_resolved for p in self.parameters)
        )

    @property
    def unresolved_parameters(self) -> List[ICTConceptParameter]:
        """List of parameters that still require human teaching."""
        return [p for p in self.parameters if not p.is_resolved]

    @property
    def blocking_items(self) -> List[str]:
        """Return all items blocking this concept from becoming EXECUTABLE."""
        items = []
        if self.definition is None:
            items.append("No deterministic definition from human teaching")
        if self.ohlcv_representation is None:
            items.append("No OHLCV representation defined")
        if self.lookahead_safe is not True:
            items.append("Lookahead safety not confirmed")
        if self.human_verified_by is None:
            items.append("No human verification record")
        elif not is_valid_human_authority(self.human_verified_by):
            items.append(f"Human verification record '{self.human_verified_by}' is not an authorized human authority")
        if not self.source_material_ids:
            items.append("No source material traceability (source_material_ids is empty)")
        for p in self.unresolved_parameters:
            items.append(f"Unresolved parameter: '{p.name}' ({p.description})")
        for q in self.unresolved_questions:
            items.append(f"Unanswered question: {q}")
        return items


# ---------------------------------------------------------------------------
# Session Definition
# ---------------------------------------------------------------------------


class SessionDefinition(BaseModel):
    """Represents a named trading session.

    Session names, timezones, start/end times, and applicable days
    MUST be defined by human teaching material.

    Do not hardcode London, New York, Asian session times or kill zones.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., min_length=1, description="Unique session identifier")
    name: str = Field(..., min_length=1, description="Session name (e.g. 'London', 'NY_AM')")
    timezone: Optional[str] = Field(
        default=None,
        description="IANA timezone string. None = not yet taught.",
    )
    start_time: Optional[str] = Field(
        default=None,
        description="Local session start time (HH:MM format). None = not yet taught.",
    )
    end_time: Optional[str] = Field(
        default=None,
        description="Local session end time (HH:MM format). None = not yet taught.",
    )
    applicable_days: List[str] = Field(
        default_factory=list,
        description="Day names (e.g. ['Monday', 'Tuesday']). Empty = not yet taught.",
    )
    enabled: bool = Field(
        default=False,
        description="Whether this session is active in the strategy.",
    )
    source_material_id: Optional[str] = Field(
        default=None,
        description="Teaching material ID that defined this session.",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty of session definition.",
    )

    @property
    def is_fully_defined(self) -> bool:
        """True only when all session parameters are present and taught."""
        return (
            self.timezone is not None
            and self.start_time is not None
            and self.end_time is not None
            and len(self.applicable_days) > 0
            and self.certainty in (ConceptCertainty.EXPLICIT, ConceptCertainty.INFERRED)
        )


# ---------------------------------------------------------------------------
# Swing Point (structural primitive)
# ---------------------------------------------------------------------------


class SwingPoint(BaseModel):
    """Structural representation of a swing high or swing low.

    The exact definition of what constitutes a swing high or low
    (lookback_candles, wick vs body consideration, etc.) must be
    populated from human teaching. Do not assume generic definitions.
    """

    model_config = ConfigDict(frozen=True)

    swing_id: str = Field(..., min_length=1, description="Unique swing point identifier")
    swing_type: SwingPointType = Field(..., description="SWING_HIGH or SWING_LOW")
    price: float = Field(..., gt=0.0, description="Price level of the swing point")
    timestamp: datetime = Field(..., description="Timestamp of the swing candle (peak/trough bar)")
    confirmed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the bar when this swing point was confirmed (lookback_right bars after timestamp).",
    )
    lookback_candles: Optional[int] = Field(
        default=None,
        description=(
            "Number of candles checked left and right to confirm swing. "
            "None = definition not yet taught."
        ),
    )
    use_wick: Optional[bool] = Field(
        default=None,
        description=(
            "True = use High/Low (wick), False = use candle body. "
            "None = not yet taught."
        ),
    )
    source_concept_id: str = Field(
        default="",
        description="ID of ICTConcept that defined this swing type.",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty that definition is correct.",
    )

    @property
    def is_deterministic(self) -> bool:
        """True only when enough parameters exist to compute deterministically."""
        return self.lookback_candles is not None and self.use_wick is not None


# ---------------------------------------------------------------------------
# Liquidity Level
# ---------------------------------------------------------------------------


class LiquidityLevel(BaseModel):
    """Represents a specific identified liquidity level.

    What constitutes liquidity, how levels are identified, and
    which are relevant must be taught. Do not assume definitions.
    """

    model_config = ConfigDict(frozen=True)

    level_id: str = Field(..., min_length=1, description="Unique level identifier")
    level_type: LiquidityType = Field(..., description="Classification of this liquidity level")
    price: float = Field(..., gt=0.0, description="Price level")
    timestamp: datetime = Field(..., description="Timestamp when this level was formed")
    timeframe: str = Field(..., min_length=1, description="Timeframe on which this level exists")
    swept: bool = Field(default=False, description="True if this level has been swept/taken")
    swept_at: Optional[datetime] = Field(
        default=None, description="Timestamp when level was swept"
    )
    source_concept_id: str = Field(
        default="",
        description="ICTConcept ID that governs how this level is defined.",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty that this level matches the taught definition.",
    )


# ---------------------------------------------------------------------------
# Fair Value Gap (FVG)
# ---------------------------------------------------------------------------


class FVGRecord(BaseModel):
    """Structural representation of a Fair Value Gap.

    The exact formation condition (three-candle structure, body vs wick boundaries,
    minimum size requirement, validity period, mitigation definition, and
    multiple-FVG handling rules) must ALL come from human teaching.

    Until those are taught and verified, this remains VERIFIED_BUT_NOT_EXECUTABLE.
    """

    model_config = ConfigDict(frozen=True)

    fvg_id: str = Field(..., min_length=1, description="Unique FVG identifier")
    direction: FVGDirection = Field(..., description="BULLISH or BEARISH")
    upper_boundary: float = Field(..., gt=0.0, description="Upper price boundary of the gap")
    lower_boundary: float = Field(..., gt=0.0, description="Lower price boundary of the gap")
    formation_candle_1_ts: datetime = Field(
        ..., description="Timestamp of first candle in formation"
    )
    formation_candle_2_ts: datetime = Field(
        ..., description="Timestamp of gap candle (second candle)"
    )
    formation_candle_3_ts: datetime = Field(
        ..., description="Timestamp of third candle in formation"
    )
    timeframe: str = Field(..., min_length=1, description="Timeframe on which FVG was formed")
    mitigated: bool = Field(default=False, description="True if FVG has been mitigated/filled")
    mitigated_at: Optional[datetime] = Field(
        default=None, description="When mitigation occurred"
    )
    valid: bool = Field(default=True, description="False when FVG has been invalidated")
    invalid_reason: Optional[str] = Field(
        default=None, description="Reason for invalidation if applicable"
    )
    source_concept_id: str = Field(
        default="",
        description="ICTConcept ID governing how this FVG is identified.",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty that this FVG matches the taught definition.",
    )

    @property
    def size(self) -> float:
        """Gap size in price units."""
        return abs(self.upper_boundary - self.lower_boundary)


# ---------------------------------------------------------------------------
# Multi-Timeframe Configuration
# ---------------------------------------------------------------------------


class TimeframeConfig(BaseModel):
    """Assigns a timeframe to a structural role in a multi-timeframe strategy.

    The specific timeframe value (e.g., '4H', '15m') and its role
    must both be taught. Do not assume a default hierarchy.
    """

    model_config = ConfigDict(frozen=True)

    config_id: str = Field(..., description="Unique config identifier")
    role: TimeframeRole = Field(..., description="Structural role of this timeframe")
    timeframe: Optional[str] = Field(
        default=None,
        description="Specific timeframe string (e.g. '4H', '15m'). None = not yet taught.",
    )
    purpose: str = Field(
        default="",
        description="Human-readable purpose description for this timeframe role.",
    )
    source_material_id: Optional[str] = Field(
        default=None,
        description="Teaching material that established this timeframe assignment.",
    )
    certainty: ConceptCertainty = Field(
        default=ConceptCertainty.MISSING,
        description="Certainty of this timeframe assignment.",
    )

    @property
    def is_assigned(self) -> bool:
        return self.timeframe is not None and self.certainty != ConceptCertainty.MISSING


# ---------------------------------------------------------------------------
# ICT Strategy Specification
# ---------------------------------------------------------------------------


class ICTStrategySpec(BaseModel):
    """Compositional ICT strategy specification built from verified ICTConcepts.

    This extends the intent of the existing StrategySpec without replacing it.
    An ICTStrategySpec is only executable when ALL composed concepts are EXECUTABLE
    and ALL compositional rules are resolved.

    The strategy spec is initially empty — fields are populated ONLY through
    the teaching pipeline. Nothing is pre-filled with generic ICT assumptions.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_id: str = Field(..., min_length=1, description="Unique strategy identifier")
    name: str = Field(..., min_length=1, description="Strategy name")
    version: str = Field(default="0.1.0", description="Strategy version")
    description: str = Field(default="", description="Strategy description")
    market_scope: str = Field(default="", description="Market scope (e.g. CRYPTO, FX)")
    instruments: List[str] = Field(default_factory=list, description="Target instruments")

    # Multi-timeframe configuration
    timeframes: List[TimeframeConfig] = Field(
        default_factory=list,
        description="Timeframe role assignments. Must be taught.",
    )

    # Sessions
    sessions: List[SessionDefinition] = Field(
        default_factory=list,
        description="Applicable trading sessions. Must be taught.",
    )

    # Concept composition
    concept_ids: List[str] = Field(
        default_factory=list,
        description="Ordered list of ICTConcept IDs composing this strategy.",
    )

    # Sequencing (must be taught)
    sequence_steps: List[str] = Field(
        default_factory=list,
        description=(
            "Explicitly ordered sequence steps for strategy execution. "
            "Each step must reference a verified concept or condition. "
            "Empty = sequence not yet taught."
        ),
    )

    # Risk rules (must be taught)
    risk_per_trade: Optional[float] = Field(
        default=None,
        description="Fraction of equity risked per trade. None = not yet taught.",
    )
    max_concurrent_positions: Optional[int] = Field(
        default=None,
        description="Maximum simultaneous open positions. None = not yet taught.",
    )

    # Overall executability
    is_verified: bool = Field(default=False, description="Human verification flag")
    verified_by: Optional[str] = Field(default=None, description="Human operator who verified")
    verified_at: Optional[datetime] = Field(default=None, description="Verification timestamp")

    source_material_ids: List[str] = Field(
        default_factory=list,
        description="Teaching material IDs that contributed to this strategy spec.",
    )

    # Unresolved items requiring human teaching
    unresolved_items: List[str] = Field(
        default_factory=list,
        description="Explicit list of items blocking executability.",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
    metadata: FrozenMapping = Field(default_factory=dict, description="Additional metadata")

    @property
    def is_executable(self) -> bool:
        """True only when strategy is fully resolved and human-verified."""
        return (
            self.is_verified
            and is_valid_human_authority(self.verified_by)
            and len(self.source_material_ids) > 0
            and len(self.concept_ids) > 0
            and len(self.sequence_steps) > 0
            and len(self.timeframes) > 0
            and self.has_complete_timeframes
            and all(s.is_fully_defined for s in self.sessions if s.enabled)
            and self.risk_per_trade is not None
            and self.risk_per_trade > 0
            and len(self.unresolved_items) == 0
        )

    @property
    def has_complete_timeframes(self) -> bool:
        """True when all timeframe roles are assigned."""
        return len(self.timeframes) > 0 and all(tf.is_assigned for tf in self.timeframes)
