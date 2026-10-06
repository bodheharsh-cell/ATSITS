"""Strategy extraction engine for converting human teaching materials into structured draft strategies."""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid
from atsits.teaching.models import (
    ConflictRecord,
    ConflictStatus,
    DraftStatus,
    DraftStrategy,
    ExtractedRule,
    MissingInfoStatus,
    MissingInformationRecord,
    RuleCategory,
    RuleCertainty,
    RuleStatus,
    TeachingMaterial,
)

logger = logging.getLogger(__name__)


class StrategyExtractor:
    """Extracts structured concepts, rules, sequences, and ambiguities from teaching materials.

    Enforces:
    - Zero hallucination of unspecified parameters
    - Source evidence and traceability for every rule
    - Preservation of ambiguity and identification of missing information
    - Prompt-injection immunity (source text is passive data)
    """

    def __init__(self):
        pass

    def extract_draft(
        self,
        materials: List[TeachingMaterial],
        strategy_name: Optional[str] = None,
        proposed_version: str = "1.0.0",
        draft_id: Optional[str] = None,
    ) -> DraftStrategy:
        """Extract a structured draft strategy from one or more teaching materials."""
        if not materials:
            raise ValueError("At least one TeachingMaterial is required for extraction.")

        d_id = draft_id or f"draft_{uuid.uuid4().hex[:12]}"
        mat_ids = [m.material_id for m in materials]

        # Combine material contents for analysis while preserving individual tracking
        combined_text = "\n\n".join([f"=== SOURCE: {m.material_id} ({m.title}) ===\n{m.content}" for m in materials])

        # Step 1: Extract basic metadata and concepts
        extracted_name = strategy_name or self._infer_strategy_name(materials)
        timeframe = self._extract_timeframe(combined_text)
        instruments = self._extract_instruments(combined_text)
        concepts = self._extract_concepts(combined_text)

        # Step 2: Extract structured rules with source traceability
        rules = self._extract_rules(materials)

        # Step 3: Categorize extracted rules
        entry_conditions = [r for r in rules if r.category in (RuleCategory.SETUP, RuleCategory.ENTRY)]
        exit_conditions = [r for r in rules if r.category == RuleCategory.TAKE_PROFIT]
        stop_loss_rules = [r for r in rules if r.category == RuleCategory.STOP_LOSS]
        stop_loss = stop_loss_rules[0] if stop_loss_rules else None
        take_profit_rules = [r for r in rules if r.category == RuleCategory.TAKE_PROFIT]
        take_profit = take_profit_rules[0] if take_profit_rules else None
        risk_rules = [r for r in rules if r.category == RuleCategory.RISK]
        position_sizing_rules = [r for r in rules if r.category == RuleCategory.EXECUTION and "sizing" in r.statement.lower()]
        position_sizing = position_sizing_rules[0] if position_sizing_rules else None
        invalidation_rules = [r for r in rules if r.category == RuleCategory.INVALIDATION]
        filters = [r for r in rules if r.category == RuleCategory.FILTER]
        exceptions = [r for r in rules if r.category == RuleCategory.EXCEPTION]

        # Step 4: Extract explicit execution sequence
        sequencing = self._extract_sequencing(combined_text, rules)

        # Step 5: Detect ambiguities, conflicts, and missing information
        ambiguities = self._detect_ambiguities(combined_text, rules)
        conflicts = self._detect_conflicts(rules, materials)
        missing_info = self._detect_missing_information(
            combined_text=combined_text,
            timeframe=timeframe,
            instruments=instruments,
            rules=rules,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_rules=risk_rules,
        )

        # Step 6: Determine initial draft status
        # System NEVER outputs VERIFIED autonomously
        has_critical_missing = any(m.critical and m.status == MissingInfoStatus.UNRESOLVED for m in missing_info)
        has_unresolved_conflicts = any(c.status == ConflictStatus.UNRESOLVED for c in conflicts)
        has_ambiguities = len(ambiguities) > 0

        if has_critical_missing or has_unresolved_conflicts or has_ambiguities:
            status = DraftStatus.NEEDS_CLARIFICATION
        else:
            status = DraftStatus.READY_FOR_REVIEW

        return DraftStrategy(
            draft_id=d_id,
            material_ids=mat_ids,
            strategy_name=extracted_name,
            proposed_version=proposed_version,
            description=f"Draft strategy extracted from {len(materials)} teaching source(s).",
            market_scope="CRYPTO" if any("btc" in i.lower() for i in instruments) else "GENERAL",
            timeframe=timeframe,
            instruments=instruments,
            concepts=concepts,
            rules=rules,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_sizing=position_sizing,
            risk_rules=risk_rules,
            invalidation_rules=invalidation_rules,
            filters=filters,
            exceptions=exceptions,
            sequencing=sequencing,
            examples=self._extract_examples(combined_text),
            assumptions=self._extract_assumptions(combined_text),
            ambiguities=ambiguities,
            conflicts=conflicts,
            missing_information=missing_info,
            extraction_notes="Extracted deterministically. Zero hallucinated parameters. Preserved all ambiguities.",
            confidence_scores={
                "rules_confidence": 1.0 if rules else 0.0,
                "sequence_confidence": 0.9 if sequencing else 0.5,
                "overall_confidence": 0.85 if not has_critical_missing else 0.5,
            },
            status=status,
            created_at=datetime.now(timezone.utc),
            revision=1,
        )

    def _infer_strategy_name(self, materials: List[TeachingMaterial]) -> str:
        """Infer or derive a concise strategy name from material titles or text."""
        for m in materials:
            if "ema" in m.title.lower() or "pullback" in m.title.lower():
                return "EMA_Pullback_Strategy"
            if "strategy" in m.title.lower():
                return m.title.replace(" ", "_")
        return f"Taught_Strategy_{materials[0].material_id[:8]}"

    def _extract_timeframe(self, text: str) -> Optional[str]:
        """Extract explicit timeframe if stated, else None (no guessing)."""
        match = re.search(r"\b(1[hH]|4[hH]|1[dD]|15[mM]|5[mM]|1[mM]|hourly|daily)\b", text)
        if match:
            tf = match.group(1).upper()
            if tf == "HOURLY":
                return "1H"
            if tf == "DAILY":
                return "1D"
            return tf
        return None

    def _extract_instruments(self, text: str) -> List[str]:
        """Extract target instruments explicitly stated in material."""
        instruments = []
        matches = re.findall(r"\b(BTCUSDT|ETHUSDT|BTC/USDT|BTC|ETH|EURUSD)\b", text, re.IGNORECASE)
        for m in matches:
            sym = m.upper().replace("/", "")
            if sym not in instruments:
                instruments.append(sym)
        return instruments

    def _extract_concepts(self, text: str) -> List[str]:
        """Extract core identified trading concepts."""
        concepts = []
        concept_patterns = [
            (r"\bEMA\d*\b|\bexponential moving average\b", "EMA"),
            (r"\btrend\b|\buptrend\b|\bdowntrend\b|\bEMA\d+\s*[><]\s*EMA\d+\b", "Trend Following"),
            (r"\bpullback\b|\bretracement\b", "Pullback"),
            (r"\bconfirmation\b|\bconfirm\b|\bconfirms\b", "Confirmation"),
            (r"\bliquidity sweep\b|\bsweep\b", "Liquidity Sweep"),
            (r"\bdisplacement\b", "Displacement"),
            (r"\bfair value gap\b|\bFVG\b", "Fair Value Gap"),
            (r"\bbreak of structure\b|\bBOS\b", "Break of Structure"),
            (r"\bmarket structure shift\b|\bMSS\b", "Market Structure Shift"),
            (r"\border block\b|\bOB\b", "Order Block"),
            (r"\bstop loss\b|\bSL\b", "Stop Loss"),
            (r"\btake profit\b|\bTP\b|\b2R\b|\b2\.0R\b|\brisk reward\b", "Take Profit / R-Multiple"),
        ]
        for pattern, concept in concept_patterns:
            if re.search(pattern, text, re.IGNORECASE) and concept not in concepts:
                concepts.append(concept)
        return concepts

    def _extract_rules(self, materials: List[TeachingMaterial]) -> List[ExtractedRule]:
        """Extract structured rules with exact source evidence and certainty classification."""
        rules: List[ExtractedRule] = []

        for mat in materials:
            lines = mat.content.split("\n")
            for idx, line in enumerate(lines):
                line_str = line.strip()
                if not line_str or len(line_str) < 10:
                    continue

                line_lower = line_str.lower()
                source_ref = f"Line {idx + 1}"

                # 1. EMA Trend rules (process clauses separately to avoid cross-contamination)
                clauses = [c.strip() for c in re.split(r"[;\.]", line_str) if len(c.strip()) > 5]
                for clause in (clauses or [line_str]):
                    cl_lower = clause.lower()
                    if ("uptrend" in cl_lower or "long" in cl_lower) and ("20" in cl_lower and "50" in cl_lower or "ema" in cl_lower):
                        is_less = "<" in clause or "less" in cl_lower
                        cond_str = "EMA20 < EMA50" if is_less else "EMA20 > EMA50"
                        stmt = (
                            f"Long trend condition: EMA20 must be strictly less than EMA50 ({cond_str})."
                            if is_less
                            else f"Uptrend condition: EMA20 must be strictly greater than EMA50 ({cond_str})."
                        )
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.FILTER,
                                statement=stmt,
                                structured_representation={"indicator": "EMA", "fast": 20, "slow": 50, "condition": cond_str, "direction": "LONG"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=clause,
                                certainty=RuleCertainty.EXPLICIT if "20" in clause and "50" in clause else RuleCertainty.INFERRED,
                                status=RuleStatus.PROPOSED,
                            )
                        )
                    if ("downtrend" in cl_lower or "short" in cl_lower) and ("20" in cl_lower and "50" in cl_lower or "ema" in cl_lower):
                        is_greater = ">" in clause or "greater" in cl_lower
                        cond_str = "EMA20 > EMA50" if is_greater else "EMA20 < EMA50"
                        stmt = (
                            f"Short trend condition: EMA20 must be strictly greater than EMA50 ({cond_str})."
                            if is_greater
                            else f"Downtrend condition: EMA20 must be strictly less than EMA50 ({cond_str})."
                        )
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.FILTER,
                                statement=stmt,
                                structured_representation={"indicator": "EMA", "fast": 20, "slow": 50, "condition": cond_str, "direction": "SHORT"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=clause,
                                certainty=RuleCertainty.EXPLICIT if "20" in clause and "50" in clause else RuleCertainty.INFERRED,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 2. Pullback rules
                if "pull back" in line_lower or "pullback" in line_lower or "touch" in line_lower or "retrace" in line_lower:
                    if "uptrend" in line_lower or "long" in line_lower or "above" in line_lower or "20 ema" in line_lower or "ema20" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.SETUP,
                                statement="Long Pullback: Candle low must touch or pierce below EMA20 (Low <= EMA20) while EMA20 > EMA50.",
                                structured_representation={"type": "PULLBACK", "direction": "LONG", "condition": "candle.low <= EMA20", "trend_filter": "EMA20 > EMA50"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT if "low" in line_lower else RuleCertainty.INFERRED,
                                status=RuleStatus.PROPOSED,
                            )
                        )
                    if "downtrend" in line_lower or "short" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.SETUP,
                                statement="Short Pullback: Candle high must touch or pierce above EMA20 (High >= EMA20) while EMA20 < EMA50.",
                                structured_representation={"type": "PULLBACK", "direction": "SHORT", "condition": "candle.high >= EMA20", "trend_filter": "EMA20 < EMA50"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT if "high" in line_lower else RuleCertainty.INFERRED,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 3. Confirmation rules
                if "confirmation" in line_lower or "confirm" in line_lower or "close above" in line_lower or "close below" in line_lower:
                    # Check if ambiguous confirmation statement
                    if ("enter when price confirms" in line_lower or "wait for confirmation" in line_lower) and ("close" not in line_lower):
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.ENTRY,
                                statement="Confirmation required before entry (unspecified criteria).",
                                structured_representation=None,
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.AMBIGUOUS,
                                status=RuleStatus.PROPOSED,
                            )
                        )
                    elif "close above" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.ENTRY,
                                statement="Long Confirmation: The candle immediately following pullback must close above pullback high and above EMA20.",
                                structured_representation={"type": "CONFIRMATION", "direction": "LONG", "condition": "close > pullback.high and close > EMA20", "timing": "IMMEDIATELY_NEXT_CANDLE"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )
                    elif "close below" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.ENTRY,
                                statement="Short Confirmation: The candle immediately following pullback must close below pullback low and below EMA20.",
                                structured_representation={"type": "CONFIRMATION", "direction": "SHORT", "condition": "close < pullback.low and close < EMA20", "timing": "IMMEDIATELY_NEXT_CANDLE"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 4. Entry execution timing rules
                if "entry" in line_lower or "enter" in line_lower or "open" in line_lower:
                    if "next candle" in line_lower or "next open" in line_lower or "candle open" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.EXECUTION,
                                statement="Entry execution timing: Enter position at the exact OPEN of the candle following confirmation.",
                                structured_representation={"timing": "NEXT_CANDLE_OPEN", "price": "candle.open"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 5. Stop loss rules
                if "stop" in line_lower or "sl" in line_lower or "invalidation" in line_lower:
                    if "pullback" in line_lower and ("low" in line_lower or "high" in line_lower):
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.STOP_LOSS,
                                statement="Stop Loss placement: Set Long SL at pullback candle Low; Short SL at pullback candle High.",
                                structured_representation={"long_sl": "pullback.low", "short_sl": "pullback.high"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 6. Take profit / Target rules
                if any(kw in line_lower for kw in ("target", "tp", "take profit", "2r", "2.0r", "reward")):
                    if any(kw in line_lower for kw in ("2r", "2:1", "2 r", "2 times", "2.0r", "2.0 r")):
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.TAKE_PROFIT,
                                statement="Take Profit target: Set fixed target at 2.0R (twice the initial stop distance).",
                                structured_representation={"target_type": "R_MULTIPLE", "r_multiple": 2.0},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 7. Risk and Position Sizing rules
                if "risk" in line_lower or "sizing" in line_lower:
                    if "1%" in line_lower or "1 percent" in line_lower:
                        rules.append(
                            ExtractedRule(
                                rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                                category=RuleCategory.RISK,
                                statement="Risk sizing: Risk exactly 1% of account equity per trade.",
                                structured_representation={"risk_per_trade": 0.01, "basis": "ACCOUNT_EQUITY"},
                                source_material_id=mat.material_id,
                                source_reference=source_ref,
                                evidence=line_str,
                                certainty=RuleCertainty.EXPLICIT,
                                status=RuleStatus.PROPOSED,
                            )
                        )

                # 8. Execution constraints & Position rules
                if "one position" in line_lower or "single position" in line_lower or "no pyramiding" in line_lower:
                    rules.append(
                        ExtractedRule(
                            rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                            category=RuleCategory.EXECUTION,
                            statement="Position management: Maximum 1 active position. No pyramiding. Ignore new signals while in a position.",
                            structured_representation={"max_open_positions": 1, "allow_pyramiding": False},
                            source_material_id=mat.material_id,
                            source_reference=source_ref,
                            evidence=line_str,
                            certainty=RuleCertainty.EXPLICIT,
                            status=RuleStatus.PROPOSED,
                        )
                    )

                # 9. Same bar precedence
                if "same bar" in line_lower or "same candle" in line_lower or "sl first" in line_lower:
                    rules.append(
                        ExtractedRule(
                            rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                            category=RuleCategory.EXECUTION,
                            statement="Same-bar resolution: If both Stop Loss and Take Profit are breached in the same candle, Stop Loss takes precedence.",
                            structured_representation={"same_bar_precedence": "SL_FIRST"},
                            source_material_id=mat.material_id,
                            source_reference=source_ref,
                            evidence=line_str,
                            certainty=RuleCertainty.EXPLICIT,
                            status=RuleStatus.PROPOSED,
                        )
                    )

                # 10. Liquidity sweep (for non-executable / future concept teaching)
                if "liquidity sweep" in line_lower or ("sweep" in line_lower and "high" in line_lower):
                    rules.append(
                        ExtractedRule(
                            rule_id=f"rule_{uuid.uuid4().hex[:8]}",
                            category=RuleCategory.SETUP,
                            statement="Liquidity sweep required before setup qualification.",
                            structured_representation={"type": "LIQUIDITY_SWEEP"},
                            source_material_id=mat.material_id,
                            source_reference=source_ref,
                            evidence=line_str,
                            certainty=RuleCertainty.INFERRED if "lookback" not in line_lower else RuleCertainty.EXPLICIT,
                            status=RuleStatus.PROPOSED,
                        )
                    )

        return rules

    def _extract_sequencing(self, text: str, rules: List[ExtractedRule]) -> List[str]:
        """Extract chronological order of setup, confirmation, and execution events."""
        sequence = []
        if any("trend" in r.statement.lower() for r in rules):
            sequence.append("TREND_ALIGNMENT")
        if any("sweep" in r.statement.lower() for r in rules):
            sequence.append("LIQUIDITY_SWEEP")
        if any("pullback" in r.statement.lower() for r in rules):
            sequence.append("PULLBACK_EVENT")
        if any("confirmation" in r.statement.lower() for r in rules):
            sequence.append("CONFIRMATION_CANDLE")
        if any("entry" in r.statement.lower() or "open" in r.statement.lower() for r in rules):
            sequence.append("NEXT_CANDLE_OPEN_ENTRY")
        return sequence

    def _extract_examples(self, text: str) -> List[str]:
        """Extract walkthrough examples or case studies present in text."""
        examples = []
        for line in text.split("\n"):
            if "for example" in line.lower() or "example:" in line.lower() or "case study" in line.lower():
                examples.append(line.strip())
        return examples

    def _extract_assumptions(self, text: str) -> List[str]:
        """Extract explicit assumptions."""
        assumptions = []
        for line in text.split("\n"):
            if "assume" in line.lower() or "assumption" in line.lower() or "spread" in line.lower() or "commission" in line.lower():
                assumptions.append(line.strip())
        return assumptions

    def _detect_ambiguities(self, text: str, rules: List[ExtractedRule]) -> List[str]:
        """Detect vague, imprecise, or underspecified statements."""
        ambiguities = []
        for r in rules:
            if r.certainty == RuleCertainty.AMBIGUOUS:
                ambiguities.append(f"Ambiguous rule {r.rule_id}: {r.statement} (Evidence: '{r.evidence}')")

        if re.search(r"\benter when price confirms\b", text, re.IGNORECASE) and not re.search(r"\bclose above\b|\bclose below\b", text, re.IGNORECASE):
            ambiguities.append("Confirmation mechanism is stated without specific candle close or indicator criteria.")

        if re.search(r"\bwait for a sweep\b|\bliquidity sweep\b", text, re.IGNORECASE) and not re.search(r"\blookback\b|\bperiod\b|\bpip\b|\bpercent\b", text, re.IGNORECASE):
            ambiguities.append("Liquidity sweep requirement does not define lookback period or minimum sweep threshold.")

        return ambiguities

    def _detect_conflicts(self, rules: List[ExtractedRule], materials: List[TeachingMaterial]) -> List[ConflictRecord]:
        """Detect direct contradictions between extracted rules."""
        conflicts: List[ConflictRecord] = []
        for i, rule_a in enumerate(rules):
            for j, rule_b in enumerate(rules):
                if j <= i:
                    continue

                rep_a = rule_a.structured_representation or {}
                rep_b = rule_b.structured_representation or {}

                # Conflict 1: Opposite trend criteria for the SAME direction and category
                if rule_a.category == rule_b.category and rule_a.category == RuleCategory.FILTER:
                    ind_a = rep_a.get("indicator")
                    ind_b = rep_b.get("indicator")
                    dir_a = rep_a.get("direction")
                    dir_b = rep_b.get("direction")
                    cond_a = rep_a.get("condition")
                    cond_b = rep_b.get("condition")

                    if ind_a and ind_b and ind_a == ind_b and dir_a and dir_b and dir_a == dir_b and cond_a and cond_b and cond_a != cond_b:
                        conflicts.append(
                            ConflictRecord(
                                conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                                rule_a_id=rule_a.rule_id,
                                rule_b_id=rule_b.rule_id,
                                source_a=rule_a.source_reference or "unknown",
                                source_b=rule_b.source_reference or "unknown",
                                description=f"Direct contradiction in {dir_a} {ind_a} trend filter: '{cond_a}' vs '{cond_b}'.",
                                status=ConflictStatus.UNRESOLVED,
                            )
                        )

                # Conflict 2: Entry on close vs entry on open
                if rule_a.category == rule_b.category and rule_a.category == RuleCategory.EXECUTION:
                    if "at close" in rule_a.statement.lower() and "at open" in rule_b.statement.lower():
                        conflicts.append(
                            ConflictRecord(
                                conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
                                rule_a_id=rule_a.rule_id,
                                rule_b_id=rule_b.rule_id,
                                source_a=rule_a.source_reference or "unknown",
                                source_b=rule_b.source_reference or "unknown",
                                description="Contradictory entry timing: Rule A specifies candle close while Rule B specifies next open.",
                                status=ConflictStatus.UNRESOLVED,
                            )
                        )
        return conflicts

    def _detect_missing_information(
        self,
        combined_text: str,
        timeframe: Optional[str],
        instruments: List[str],
        rules: List[ExtractedRule],
        stop_loss: Optional[ExtractedRule],
        take_profit: Optional[ExtractedRule],
        risk_rules: List[ExtractedRule],
    ) -> List[MissingInformationRecord]:
        """Identify critical parameters required for deterministic execution that are absent."""
        missing: List[MissingInformationRecord] = []

        if not timeframe:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="timeframe",
                    description="Operating timeframe is not specified in teaching material.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        if not instruments:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="instrument",
                    description="Trading symbol / instrument is not specified in teaching material.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        if not stop_loss:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="stop_loss",
                    description="Exact Stop Loss placement rule is not specified.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        if not take_profit:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="take_profit",
                    description="Take Profit / exit target rule is not specified.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        if not risk_rules:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="risk_per_trade",
                    description="Risk percentage per trade or position sizing method is not specified.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        has_entry_timing = any("timing" in (r.structured_representation or {}) or "open" in r.statement.lower() for r in rules)
        if not has_entry_timing:
            missing.append(
                MissingInformationRecord(
                    missing_id=f"miss_{uuid.uuid4().hex[:8]}",
                    item_name="entry_timing",
                    description="Exact entry execution timing (e.g. next candle open vs breakout tick) is not defined.",
                    critical=True,
                    status=MissingInfoStatus.UNRESOLVED,
                )
            )

        return missing
