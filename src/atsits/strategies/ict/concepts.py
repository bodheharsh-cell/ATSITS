"""Catalog of ICT concept categories and structural templates for ATSITS Phase 8.

CRITICAL INVARIANT:
This catalog defines ONLY the structural placeholders and unresolved questions for
each ICT concept category. It does NOT contain trading rules, parameter values,
thresholds, lookback periods, session times, or execution logic.

All definitions MUST be populated from human teaching material via Phase 7.
"""

from typing import Dict, List, Optional
from atsits.strategies.ict.models import (
    ConceptCertainty,
    ConceptStatus,
    ICTConcept,
    ICTConceptCategory,
    ICTConceptParameter,
)


def _build_catalog() -> Dict[str, ICTConcept]:
    """Instantiate the canonical catalog of ICT concept categories."""
    catalog: Dict[str, ICTConcept] = {}

    # 1. MARKET_STRUCTURE
    catalog["market_structure"] = ICTConcept(
        concept_id="market_structure",
        category=ICTConceptCategory.MARKET_STRUCTURE,
        name="Market Structure",
        description="High-level structural trend and price regime classification.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="ms_timeframe",
                name="Structure Timeframe",
                description="Timeframe on which market structure is identified (e.g., 4H, 1D).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="ms_trend_rule",
                name="Trend Classification Rule",
                description="Rule determining bullish vs bearish structure (e.g., higher highs/lows vs lower highs/lows).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "Which timeframe defines the structural trend?",
            "What specific sequence of highs and lows establishes bullish vs bearish structure?",
            "How many swings are required to confirm a change in structural regime?",
            "How are complex multi-timeframe structural conflicts resolved?",
        ],
    )

    # 2. SWING_HIGH
    catalog["swing_high"] = ICTConcept(
        concept_id="swing_high",
        category=ICTConceptCategory.SWING_HIGH,
        name="Swing High",
        description="Local price maximum representing structural turning point or buy-side liquidity.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="sh_lookback_left",
                name="Left Lookback Bars",
                description="Number of neighboring bars to the left required to have lower highs.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="sh_lookback_right",
                name="Right Lookback Bars",
                description="Number of neighboring bars to the right required to confirm the swing high.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="sh_use_wick",
                name="Use Wick vs Body",
                description="True if high is measured from wick (High), False if measured from body (Open/Close).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "How many bars to the left and right are required to confirm a swing high?",
            "Is the swing high defined by the candle wick high or the candle body close?",
            "What is the required confirmation delay before the swing high is considered established?",
        ],
    )

    # 3. SWING_LOW
    catalog["swing_low"] = ICTConcept(
        concept_id="swing_low",
        category=ICTConceptCategory.SWING_LOW,
        name="Swing Low",
        description="Local price minimum representing structural turning point or sell-side liquidity.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="sl_lookback_left",
                name="Left Lookback Bars",
                description="Number of neighboring bars to the left required to have higher lows.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="sl_lookback_right",
                name="Right Lookback Bars",
                description="Number of neighboring bars to the right required to confirm the swing low.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="sl_use_wick",
                name="Use Wick vs Body",
                description="True if low is measured from wick (Low), False if measured from body (Open/Close).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "How many bars to the left and right are required to confirm a swing low?",
            "Is the swing low defined by the candle wick low or the candle body close?",
            "What is the required confirmation delay before the swing low is considered established?",
        ],
    )

    # 4. LIQUIDITY
    catalog["liquidity"] = ICTConcept(
        concept_id="liquidity",
        category=ICTConceptCategory.LIQUIDITY,
        name="Liquidity",
        description="Pools of resting orders at key reference prices.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="liq_types",
                name="Target Liquidity Types",
                description="Which liquidity types are monitored (e.g. swing highs/lows, equal highs/lows, session extremes).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="liq_tolerance_pct",
                name="Equal High/Low Tolerance",
                description="Price percentage tolerance for identifying equal highs or equal lows.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What constitutes valid liquidity for this strategy?",
            "Which reference levels are tracked (previous day, session, swing points, equal highs/lows)?",
            "What is the price tolerance for identifying equal highs or equal lows?",
            "Which timeframe's liquidity pools are prioritized?",
        ],
    )

    # 5. LIQUIDITY_SWEEP
    catalog["liquidity_sweep"] = ICTConcept(
        concept_id="liquidity_sweep",
        category=ICTConceptCategory.LIQUIDITY_SWEEP,
        name="Liquidity Sweep",
        description="Price breaching a liquidity level and failing to sustain continuation.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="sweep_breach_rule",
                name="Breach Rule",
                description="Condition for sweep (e.g., Wick pierces level but candle closes back inside).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="sweep_max_bars",
                name="Max Sweep Reversal Window",
                description="Maximum number of bars allowed for price to reverse back inside level.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What qualifies as a liquidity sweep vs a true breakout?",
            "Must the candle close back inside the liquidity level, or does a wick touch suffice?",
            "Within how many bars must the rejection occur following the breach?",
        ],
    )

    # 6. DISPLACEMENT
    catalog["displacement"] = ICTConcept(
        concept_id="displacement",
        category=ICTConceptCategory.DISPLACEMENT,
        name="Displacement",
        description="Energetic, directional candle movement indicating institutional participation.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="disp_min_body_ratio",
                name="Min Body-to-Range Ratio",
                description="Minimum ratio of candle body to total range to qualify as displacement.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="disp_min_size_atr_multiple",
                name="Min Size ATR Multiple",
                description="Minimum candle range relative to average range (e.g. 1.5x ATR).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What quantifiable metric defines displacement (body size, ATR multiple, tick velocity)?",
            "How many consecutive displacement candles are required?",
            "Must displacement create an immediate Fair Value Gap or break structure?",
        ],
    )

    # 7. FAIR_VALUE_GAP
    catalog["fair_value_gap"] = ICTConcept(
        concept_id="fair_value_gap",
        category=ICTConceptCategory.FAIR_VALUE_GAP,
        name="Fair Value Gap (FVG)",
        description="Three-candle price imbalance where candle 1 and candle 3 wicks do not overlap.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="fvg_min_gap_size",
                name="Minimum Gap Size",
                description="Minimum gap size in price or percentage required for validity.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="fvg_mitigation_rule",
                name="Mitigation Rule",
                description="Rule defining when an FVG is mitigated (e.g. touch upper bound, fill 50%, full fill).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="fvg_invalidation_rule",
                name="Invalidation Rule",
                description="Condition that invalidates the FVG (e.g. candle close through opposite boundary).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What exact three-candle formation rule defines an FVG for this strategy?",
            "What is the minimum gap size required for an FVG to be tradable?",
            "When is an FVG considered mitigated (first touch, 50% CE level, full fill)?",
            "When does an FVG become invalid?",
            "How are overlapping or multiple consecutive FVGs prioritized?",
        ],
    )

    # 8. ORDER_BLOCK
    catalog["order_block"] = ICTConcept(
        concept_id="order_block",
        category=ICTConceptCategory.ORDER_BLOCK,
        name="Order Block",
        description="The last opposing candle prior to a strong displacement move.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="ob_selection_rule",
                name="Candle Selection Rule",
                description="Whether OB is defined by last opposing candle, consecutive series, or wick/body bounds.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="ob_mitigation_threshold",
                name="Mitigation Threshold",
                description="Price level within OB required for mitigation (open, high/low, 50% mean threshold).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What exact candle sequence defines an Order Block?",
            "Is the Order Block boundary defined by candle high/low wicks or open/close body?",
            "What level within the Order Block constitutes mitigation (open, 50% mean threshold)?",
            "Must the move following the Order Block create an FVG or break structure?",
        ],
    )

    # 9. BREAK_OF_STRUCTURE
    catalog["break_of_structure"] = ICTConcept(
        concept_id="break_of_structure",
        category=ICTConceptCategory.BREAK_OF_STRUCTURE,
        name="Break of Structure (BOS)",
        description="Price moving beyond a prior swing high/low in the direction of the prevailing trend.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="bos_confirmation_rule",
                name="Break Confirmation Rule",
                description="Whether BOS requires a candle close beyond swing level or wick breach is sufficient.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "Does a Break of Structure require a candle close beyond the prior swing or only a wick breach?",
            "Which timeframe swing point must be broken?",
            "How does BOS differ from MSS in this strategy?",
        ],
    )

    # 10. MARKET_STRUCTURE_SHIFT
    catalog["market_structure_shift"] = ICTConcept(
        concept_id="market_structure_shift",
        category=ICTConceptCategory.MARKET_STRUCTURE_SHIFT,
        name="Market Structure Shift (MSS)",
        description="First break of opposing swing high/low accompanied by displacement signaling trend reversal.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="mss_displacement_required",
                name="Displacement Required",
                description="Whether MSS strictly requires displacement into an FVG.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="mss_close_required",
                name="Close Required",
                description="Whether MSS requires a candle body close beyond key swing level.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What distinguishes an MSS from a normal BOS?",
            "Must an MSS be accompanied by displacement and FVG creation?",
            "Does MSS require a body close past the swing point or a wick breach?",
        ],
    )

    # 11. PREMIUM
    catalog["premium"] = ICTConcept(
        concept_id="premium",
        category=ICTConceptCategory.PREMIUM,
        name="Premium Zone",
        description="Upper 50% of the active dealing range, favoring sell setups.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="prem_range_calc",
                name="Dealing Range Calculation",
                description="How dealing range high and low are identified for premium calculation.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "How is the dealing range high and low determined to calculate the 50% equilibrium?",
            "Is premium defined strictly as > 50% Fibonacci retracement or another threshold?",
        ],
    )

    # 12. DISCOUNT
    catalog["discount"] = ICTConcept(
        concept_id="discount",
        category=ICTConceptCategory.DISCOUNT,
        name="Discount Zone",
        description="Lower 50% of the active dealing range, favoring buy setups.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="disc_range_calc",
                name="Dealing Range Calculation",
                description="How dealing range high and low are identified for discount calculation.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "How is the dealing range high and low determined to calculate the 50% equilibrium?",
            "Is discount defined strictly as < 50% Fibonacci retracement or another threshold?",
        ],
    )

    # 13. DEALING_RANGE
    catalog["dealing_range"] = ICTConcept(
        concept_id="dealing_range",
        category=ICTConceptCategory.DEALING_RANGE,
        name="Dealing Range",
        description="The active trading range bounded by key swing high and swing low.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="dr_high_swing_id",
                name="Range High Swing",
                description="Method of selecting anchor high for the range.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="dr_low_swing_id",
                name="Range Low Swing",
                description="Method of selecting anchor low for the range.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What defines the anchor high and low of the active dealing range?",
            "When is the dealing range reset or expanded?",
        ],
    )

    # 14. SESSION
    catalog["session"] = ICTConcept(
        concept_id="session",
        category=ICTConceptCategory.SESSION,
        name="Trading Session & Kill Zone",
        description="Specific time-of-day windows where trading setups are evaluated.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="session_timezone",
                name="Session Timezone",
                description="Timezone for session window evaluation (e.g. UTC, America/New_York).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="session_start_time",
                name="Session Start Time",
                description="Start time of allowed trading window in HH:MM.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="session_end_time",
                name="Session End Time",
                description="End time of allowed trading window in HH:MM.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What specific session hours or kill zones apply to this strategy?",
            "What timezone is used for session start and end times?",
            "Are trades outside the session window prohibited or only new setup evaluations prohibited?",
        ],
    )

    # 15. ENTRY_MODEL
    catalog["entry_model"] = ICTConcept(
        concept_id="entry_model",
        category=ICTConceptCategory.ENTRY_MODEL,
        name="Entry Model",
        description="Deterministic trigger condition converting verified setup into trade entry.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="entry_timing",
                name="Entry Execution Timing",
                description="When order is executed (e.g. Next candle Open, Limit at FVG boundary, Market on close).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="entry_price_level",
                name="Entry Price Level",
                description="Reference price for entry execution.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What exact event triggers the entry (limit order at FVG boundary, market on close, next bar open)?",
            "Which timeframe governs the entry execution trigger?",
            "How long may a pending entry wait before being cancelled?",
        ],
    )

    # 16. INVALIDATION
    catalog["invalidation"] = ICTConcept(
        concept_id="invalidation",
        category=ICTConceptCategory.INVALIDATION,
        name="Setup Invalidation",
        description="Conditions that void a forming setup before trade entry.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="invalidation_price_level",
                name="Invalidation Price Level",
                description="Price breach that immediately voids the setup.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="invalidation_max_bars",
                name="Max Setup Lifetime Bars",
                description="Maximum bars setup may remain active before expiring.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What price action voids a setup prior to entry execution?",
            "What is the maximum time or bar count a setup remains valid?",
        ],
    )

    # 17. TARGET
    catalog["target"] = ICTConcept(
        concept_id="target",
        category=ICTConceptCategory.TARGET,
        name="Take Profit Target",
        description="Objective price target or R-multiple for closing a winning trade.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="target_type",
                name="Target Type",
                description="Method of target placement (fixed R-multiple, opposing liquidity pool, key swing level).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="target_value",
                name="Target Value",
                description="Specific R-multiple or reference level.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "How is the profit target determined (fixed R-multiple, next major liquidity pool, previous high/low)?",
            "Are partial take-profit levels used, or single full exit?",
        ],
    )

    # 18. RISK
    catalog["risk"] = ICTConcept(
        concept_id="risk",
        category=ICTConceptCategory.RISK,
        name="Risk Management",
        description="Position sizing and capital risk constraints.",
        definition=None,
        status=ConceptStatus.UNDEFINED,
        certainty=ConceptCertainty.MISSING,
        parameters=[
            ICTConceptParameter(
                param_id="risk_pct",
                name="Risk Per Trade Fraction",
                description="Percentage of equity risked per trade (e.g. 0.01 for 1%).",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
            ICTConceptParameter(
                param_id="max_positions",
                name="Max Concurrent Positions",
                description="Maximum simultaneous open positions allowed.",
                value=None,
                certainty=ConceptCertainty.MISSING,
            ),
        ],
        unresolved_questions=[
            "What fraction of account equity is risked per trade?",
            "What is the maximum number of simultaneous active positions allowed?",
            "Is pyramiding or adding to winning positions allowed?",
        ],
    )

    return catalog


CONCEPT_CATALOG: Dict[str, ICTConcept] = _build_catalog()


def get_catalog_concept(concept_id: str) -> Optional[ICTConcept]:
    """Retrieve a template concept from the catalog by ID."""
    return CONCEPT_CATALOG.get(concept_id.lower())


def list_catalog_concepts() -> List[ICTConcept]:
    """Return all catalog template concepts."""
    return list(CONCEPT_CATALOG.values())
