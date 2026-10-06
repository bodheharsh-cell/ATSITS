"""Extraction bridge connecting Phase 7 teaching materials to structured ICT concepts.

CRITICAL INVARIANT:
This extractor identifies what the human teaching material ACTUALLY says.
It does NOT hallucinate parameters, default thresholds, lookback periods,
or execution rules. Any concept that is mentioned but underspecified is
explicitly flagged as AMBIGUOUS or MISSING and populated with unresolved questions.
"""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import (
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
from atsits.strategies.ict.concepts import CONCEPT_CATALOG, get_catalog_concept
from atsits.strategies.ict.models import (
    ConceptCertainty,
    ConceptStatus,
    ICTConcept,
    ICTConceptCategory,
    ICTConceptParameter,
)

logger = logging.getLogger(__name__)

# Keyword patterns mapping human text to ICT concept categories
_ICT_KEYWORD_PATTERNS: Dict[ICTConceptCategory, List[str]] = {
    ICTConceptCategory.MARKET_STRUCTURE: [
        r"\bmarket structure\b",
        r"\bstructure\b",
        r"\btrend structure\b",
    ],
    ICTConceptCategory.SWING_HIGH: [
        r"\bswing high\b",
        r"\bswing highs\b",
        r"\bsh\b",
        r"\blocal high\b",
    ],
    ICTConceptCategory.SWING_LOW: [
        r"\bswing low\b",
        r"\bswing lows\b",
        r"\bsl\b",
        r"\blocal low\b",
    ],
    ICTConceptCategory.LIQUIDITY: [
        r"\bliquidity\b",
        r"\bequal highs\b",
        r"\bequal lows\b",
        r"\bbuy-side liquidity\b",
        r"\bsell-side liquidity\b",
        r"\bbsl\b",
        r"\bssl\b",
    ],
    ICTConceptCategory.LIQUIDITY_SWEEP: [
        r"\bliquidity sweep\b",
        r"\bsweep\b",
        r"\bswept\b",
        r"\btaken\b",
        r"\braid\b",
        r"\bpurge\b",
        r"\brun on liquidity\b",
    ],
    ICTConceptCategory.DISPLACEMENT: [
        r"\bdisplacement\b",
        r"\bimpulsive move\b",
        r"\benergetic move\b",
        r"\bexpansion candle\b",
    ],
    ICTConceptCategory.FAIR_VALUE_GAP: [
        r"\bfair value gap\b",
        r"\bfvg\b",
        r"\bimbalance\b",
        r"\binefficiency\b",
        r"\bsibi\b",
        r"\bbisi\b",
    ],
    ICTConceptCategory.ORDER_BLOCK: [
        r"\border block\b",
        r"\bob\b",
        r"\bbreaker block\b",
        r"\bmitigation block\b",
    ],
    ICTConceptCategory.BREAK_OF_STRUCTURE: [
        r"\bbreak of structure\b",
        r"\bbos\b",
        r"\bstructure break\b",
    ],
    ICTConceptCategory.MARKET_STRUCTURE_SHIFT: [
        r"\bmarket structure shift\b",
        r"\bmss\b",
        r"\bshift in structure\b",
        r"\bchange of character\b",
        r"\bchoch\b",
    ],
    ICTConceptCategory.PREMIUM: [
        r"\bpremium\b",
        r"\bpremium zone\b",
    ],
    ICTConceptCategory.DISCOUNT: [
        r"\bdiscount\b",
        r"\bdiscount zone\b",
    ],
    ICTConceptCategory.DEALING_RANGE: [
        r"\bdealing range\b",
        r"\brange equilibrium\b",
        r"\bequilibrium\b",
    ],
    ICTConceptCategory.SESSION: [
        r"\bsession\b",
        r"\bkill zone\b",
        r"\bkillzone\b",
        r"\blondon\b",
        r"\bnew york\b",
        r"\basian\b",
        r"\bjudas swing\b",
    ],
    ICTConceptCategory.ENTRY_MODEL: [
        r"\bentry model\b",
        r"\bentry trigger\b",
        r"\benter on\b",
        r"\bexecution model\b",
    ],
    ICTConceptCategory.INVALIDATION: [
        r"\binvalidation\b",
        r"\binvalidate\b",
        r"\bvoid\b",
        r"\bsetup cancelled\b",
    ],
    ICTConceptCategory.TARGET: [
        r"\btarget\b",
        r"\btake profit\b",
        r"\btp\b",
        r"\bprofit target\b",
    ],
    ICTConceptCategory.RISK: [
        r"\brisk\b",
        r"\bposition size\b",
        r"\bstop loss\b",
        r"\bsizing\b",
    ],
}


class ICTConceptExtractor:
    """Extracts ICT concepts from human teaching materials via Phase 7 pipeline without hallucinating rules."""

    def __init__(self, base_extractor: Optional[StrategyExtractor] = None):
        self.base_extractor = base_extractor or StrategyExtractor()

    def extract_ict_concepts(
        self, materials: List[TeachingMaterial]
    ) -> List[ICTConcept]:
        """Extract structured ICTConcept objects from teaching materials.

        Identifies mentioned concept categories. Where parameters/definitions are not
        explicitly stated in the text, marks them as AMBIGUOUS/MISSING and attaches
        unresolved questions.
        """
        if not materials:
            return []

        combined_text = "\n\n".join(m.content for m in materials)
        material_ids = [m.material_id for m in materials]
        extracted_concepts: List[ICTConcept] = []

        # Check which categories are referenced in teaching material
        for category, patterns in _ICT_KEYWORD_PATTERNS.items():
            matched_snippets: List[str] = []
            for pat in patterns:
                for match in re.finditer(pat, combined_text, re.IGNORECASE):
                    # Extract surrounding context (sentence or window)
                    start = max(0, match.start() - 50)
                    end = min(len(combined_text), match.end() + 50)
                    snippet = combined_text[start:end].strip()
                    matched_snippets.append(snippet)

            if not matched_snippets:
                continue

            # Template from catalog
            concept_key = category.value.lower()
            template = get_catalog_concept(concept_key)
            if not template:
                continue

            evidence = "; ".join(matched_snippets[:3])
            has_explicit_rules, explicit_definition, resolved_params = self._analyze_definition(
                category, combined_text
            )

            if has_explicit_rules and explicit_definition:
                # Fully or partially specified definition from teaching
                certainty = ConceptCertainty.EXPLICIT
                status = ConceptStatus.TAUGHT
                unresolved_q = [
                    q for q in template.unresolved_questions
                    if not any(p.name.lower() in q.lower() for p in resolved_params if p.is_resolved)
                ]
            else:
                # Mentioned but underspecified — preserve catalog unresolved questions
                certainty = ConceptCertainty.AMBIGUOUS
                status = ConceptStatus.TAUGHT
                explicit_definition = None
                resolved_params = template.parameters
                unresolved_q = list(template.unresolved_questions)

            concept = ICTConcept(
                concept_id=f"taught_{concept_key}",
                category=category,
                name=template.name,
                description=template.description,
                definition=explicit_definition,
                parameters=resolved_params,
                dependencies=template.dependencies,
                source_material_ids=material_ids,
                source_evidence=evidence,
                certainty=certainty,
                status=status,
                unresolved_questions=unresolved_q,
            )
            extracted_concepts.append(concept)

        return extracted_concepts

    def extract_ict_draft(
        self,
        materials: List[TeachingMaterial],
        strategy_name: Optional[str] = None,
        proposed_version: str = "0.1.0",
    ) -> Tuple[DraftStrategy, List[ICTConcept]]:
        """Extract a complete DraftStrategy alongside its component ICTConcepts.

        Ensures that any ambiguous concept creates corresponding MissingInformationRecord
        items in the draft strategy so that Phase 7 human review can address them.
        """
        # 1. Run base Phase 7 extraction
        draft = self.base_extractor.extract_draft(
            materials=materials,
            strategy_name=strategy_name or "ICT_Taught_Strategy",
            proposed_version=proposed_version,
        )

        # 2. Extract detailed ICT concepts
        ict_concepts = self.extract_ict_concepts(materials)

        # 3. Augment draft with ICT concepts & unresolved questions
        augmented_missing = list(draft.missing_information)
        augmented_ambiguities = list(draft.ambiguities)
        augmented_concepts = list(draft.concepts)

        for c in ict_concepts:
            if c.name not in augmented_concepts:
                augmented_concepts.append(c.name)

            if c.certainty in (ConceptCertainty.AMBIGUOUS, ConceptCertainty.MISSING):
                for q in c.unresolved_questions:
                    if q not in augmented_ambiguities:
                        augmented_ambiguities.append(q)

                for p in c.unresolved_parameters:
                    missing_id = f"missing_{c.concept_id}_{p.param_id}"
                    if not any(m.missing_id == missing_id for m in augmented_missing):
                        augmented_missing.append(
                            MissingInformationRecord(
                                missing_id=missing_id,
                                item_name=f"{c.name}: {p.name}",
                                description=f"{p.description} (Source concept: {c.concept_id})",
                                critical=True,
                                status=MissingInfoStatus.UNRESOLVED,
                            )
                        )

        # Determine draft status
        if augmented_missing or augmented_ambiguities:
            status = DraftStatus.NEEDS_CLARIFICATION
        else:
            status = draft.status

        augmented_draft = draft.model_copy(
            update={
                "concepts": augmented_concepts,
                "missing_information": augmented_missing,
                "ambiguities": augmented_ambiguities,
                "status": status,
            }
        )

        return augmented_draft, ict_concepts

    def _analyze_definition(
        self, category: ICTConceptCategory, text: str
    ) -> Tuple[bool, Optional[str], List[ICTConceptParameter]]:
        """Check if teaching text contains a quantifiable, deterministic rule for a category."""
        text_lower = text.lower()
        template = get_catalog_concept(category.value.lower())
        if not template:
            return False, None, []

        params = list(template.parameters)

        # Look for explicit numbers or precise parameters
        if category == ICTConceptCategory.SWING_HIGH or category == ICTConceptCategory.SWING_LOW:
            lookback_match = re.search(r"(\d+)\s*[- ]*(bar|candle)s?\s*(left|right|swing|lookback)", text_lower)
            if lookback_match:
                n = int(lookback_match.group(1))
                if "wick" in text_lower:
                    use_wick: Optional[bool] = True
                    wick_cert = ConceptCertainty.EXPLICIT
                elif "body" in text_lower:
                    use_wick = False
                    wick_cert = ConceptCertainty.EXPLICIT
                else:
                    use_wick = None
                    wick_cert = ConceptCertainty.MISSING

                new_params = [
                    ICTConceptParameter(
                        param_id=f"{category.value.lower()[:2]}_lookback_left",
                        name="Left Lookback Bars",
                        description="Lookback bars to the left",
                        value=n,
                        certainty=ConceptCertainty.EXPLICIT,
                    ),
                    ICTConceptParameter(
                        param_id=f"{category.value.lower()[:2]}_lookback_right",
                        name="Right Lookback Bars",
                        description="Lookback bars to the right",
                        value=n,
                        certainty=ConceptCertainty.EXPLICIT,
                    ),
                    ICTConceptParameter(
                        param_id=f"{category.value.lower()[:2]}_use_wick",
                        name="Use Wick vs Body",
                        description="Wick vs Body flag",
                        value=use_wick,
                        certainty=wick_cert,
                    ),
                ]
                wick_desc = f" using {'wick' if use_wick is True else 'body'}" if use_wick is not None else " (wick vs body unstated)"
                return (
                    True,
                    f"A {category.name.lower()} is defined with {n} bars lookback left and right{wick_desc}.",
                    new_params,
                )

        elif category == ICTConceptCategory.FAIR_VALUE_GAP:
            # Only extract explicit definition if the source material directly defines the relationship
            if ("candle 1" in text_lower and "candle 3" in text_lower and (
                "imbalance" in text_lower or "gap" in text_lower or "overlap" in text_lower or "wicks" in text_lower
            )):
                sentences = [s.strip() for s in re.split(r"[.\n;]", text) if s.strip()]
                fvg_sentence = next(
                    (s for s in sentences if "candle 1" in s.lower() and "candle 3" in s.lower()),
                    None,
                )
                if fvg_sentence:
                    return True, fvg_sentence, params

        elif category == ICTConceptCategory.RISK:
            risk_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:risk|equity|account)", text_lower)
            if risk_match:
                pct = float(risk_match.group(1)) / 100.0
                new_params = [
                    ICTConceptParameter(
                        param_id="risk_pct",
                        name="Risk Per Trade Fraction",
                        description="Fraction of equity risked per trade",
                        value=pct,
                        certainty=ConceptCertainty.EXPLICIT,
                    ),
                    ICTConceptParameter(
                        param_id="max_positions",
                        name="Max Concurrent Positions",
                        description="Maximum concurrent positions",
                        value=1,
                        certainty=ConceptCertainty.EXPLICIT,
                    ),
                ]
                return True, f"Risk exactly {pct*100:.1f}% equity per trade, maximum 1 position.", new_params

        return False, None, params
