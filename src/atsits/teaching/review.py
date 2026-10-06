"""Human review engine enforcing human authority, audit trail, and verification gates."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
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
    RuleCertainty,
    RuleStatus,
    StrategyExecutionStatus,
    VerifiedStrategy,
)
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.validator import StrategyValidator

logger = logging.getLogger(__name__)


class HumanReviewEngine:
    """Manages the human review lifecycle, enforces verification gates, and maintains audit lineage."""

    def __init__(self, registry: Optional[TeachingRegistry] = None, validator: Optional[StrategyValidator] = None):
        self.registry = registry or TeachingRegistry()
        self.validator = validator or StrategyValidator()

    def approve_rule(
        self,
        draft_id: str,
        rule_id: str,
        reviewer: str,
        reason: Optional[str] = None,
    ) -> DraftStrategy:
        """Record human approval for an individual extracted rule."""
        self._validate_reviewer(reviewer)
        draft = self._get_latest_draft(draft_id)

        target_rule: Optional[ExtractedRule] = None
        updated_rules = []
        for r in draft.rules:
            if r.rule_id == rule_id:
                target_rule = r
                updated_rules.append(
                    ExtractedRule(
                        rule_id=r.rule_id,
                        category=r.category,
                        statement=r.statement,
                        structured_representation=r.structured_representation,
                        source_material_id=r.source_material_id,
                        source_reference=r.source_reference,
                        evidence=r.evidence,
                        certainty=r.certainty,
                        status=RuleStatus.ACCEPTED,
                    )
                )
            else:
                updated_rules.append(r)

        if not target_rule:
            raise ValueError(f"Rule with ID '{rule_id}' not found in draft '{draft_id}'.")

        # Record audit log
        self.registry.save_review_record(
            ReviewRecord(
                review_id=f"rev_{uuid.uuid4().hex[:10]}",
                draft_id=draft_id,
                reviewer=reviewer,
                timestamp=datetime.now(timezone.utc),
                action=ReviewAction.APPROVE_RULE,
                target=rule_id,
                original_value=target_rule.statement,
                new_value=target_rule.statement,
                reason=reason or "Human operator confirmed rule accuracy",
                status="COMPLETED",
            )
        )

        # Create new revision snapshot
        new_draft = draft.model_copy(
            update={
                "rules": updated_rules,
                "revision": draft.revision + 1,
            }
        )
        return self.registry.save_draft(new_draft)

    def correct_rule(
        self,
        draft_id: str,
        rule_id: str,
        new_statement: str,
        reviewer: str,
        new_structured_rep: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> DraftStrategy:
        """Apply human correction to an extracted rule, preserving original extraction lineage."""
        self._validate_reviewer(reviewer)
        draft = self._get_latest_draft(draft_id)

        target_rule: Optional[ExtractedRule] = None
        updated_rules = []
        for r in draft.rules:
            if r.rule_id == rule_id:
                target_rule = r
                updated_rules.append(
                    ExtractedRule(
                        rule_id=r.rule_id,
                        category=r.category,
                        statement=new_statement,
                        structured_representation=new_structured_rep or r.structured_representation,
                        source_material_id=r.source_material_id,
                        source_reference=r.source_reference,
                        evidence=r.evidence,
                        certainty=RuleCertainty.EXPLICIT,  # Clarified by human
                        status=RuleStatus.MODIFIED,
                    )
                )
            else:
                updated_rules.append(r)

        if not target_rule:
            raise ValueError(f"Rule with ID '{rule_id}' not found in draft '{draft_id}'.")

        # Audit record
        self.registry.save_review_record(
            ReviewRecord(
                review_id=f"rev_{uuid.uuid4().hex[:10]}",
                draft_id=draft_id,
                reviewer=reviewer,
                timestamp=datetime.now(timezone.utc),
                action=ReviewAction.CORRECT_RULE,
                target=rule_id,
                original_value=target_rule.statement,
                new_value=new_statement,
                reason=reason or "Human operator corrected rule formulation",
                status="COMPLETED",
            )
        )

        new_draft = draft.model_copy(
            update={
                "rules": updated_rules,
                "revision": draft.revision + 1,
            }
        )
        return self.registry.save_draft(new_draft)

    def resolve_conflict(
        self,
        draft_id: str,
        conflict_id: str,
        resolution_text: str,
        reviewer: str,
        reason: Optional[str] = None,
    ) -> DraftStrategy:
        """Resolve a detected rule conflict via explicit human operator decision."""
        self._validate_reviewer(reviewer)
        draft = self._get_latest_draft(draft_id)

        target_conflict: Optional[ConflictRecord] = None
        updated_conflicts = []
        for c in draft.conflicts:
            if c.conflict_id == conflict_id:
                target_conflict = c
                updated_conflicts.append(
                    ConflictRecord(
                        conflict_id=c.conflict_id,
                        rule_a_id=c.rule_a_id,
                        rule_b_id=c.rule_b_id,
                        source_a=c.source_a,
                        source_b=c.source_b,
                        description=c.description,
                        status=ConflictStatus.RESOLVED_BY_HUMAN,
                        resolution=resolution_text,
                    )
                )
            else:
                updated_conflicts.append(c)

        if not target_conflict:
            raise ValueError(f"Conflict with ID '{conflict_id}' not found in draft '{draft_id}'.")

        self.registry.save_review_record(
            ReviewRecord(
                review_id=f"rev_{uuid.uuid4().hex[:10]}",
                draft_id=draft_id,
                reviewer=reviewer,
                timestamp=datetime.now(timezone.utc),
                action=ReviewAction.RESOLVE_CONFLICT,
                target=conflict_id,
                original_value=target_conflict.description,
                new_value=resolution_text,
                reason=reason or "Human operator resolved contradiction",
                status="COMPLETED",
            )
        )

        new_draft = draft.model_copy(
            update={
                "conflicts": updated_conflicts,
                "revision": draft.revision + 1,
            }
        )
        return self.registry.save_draft(new_draft)

    def provide_clarification(
        self,
        draft_id: str,
        missing_id: str,
        resolution_value: str,
        reviewer: str,
        reason: Optional[str] = None,
    ) -> DraftStrategy:
        """Provide a missing parameter or clarification required for deterministic execution."""
        self._validate_reviewer(reviewer)
        draft = self._get_latest_draft(draft_id)

        target_missing: Optional[MissingInformationRecord] = None
        updated_missing = []
        for m in draft.missing_information:
            if m.missing_id == missing_id:
                target_missing = m
                updated_missing.append(
                    MissingInformationRecord(
                        missing_id=m.missing_id,
                        item_name=m.item_name,
                        description=m.description,
                        critical=m.critical,
                        status=MissingInfoStatus.RESOLVED_BY_HUMAN,
                        resolution=resolution_value,
                    )
                )
            else:
                updated_missing.append(m)

        if not target_missing:
            raise ValueError(f"Missing information record '{missing_id}' not found in draft '{draft_id}'.")

        self.registry.save_review_record(
            ReviewRecord(
                review_id=f"rev_{uuid.uuid4().hex[:10]}",
                draft_id=draft_id,
                reviewer=reviewer,
                timestamp=datetime.now(timezone.utc),
                action=ReviewAction.PROVIDE_CLARIFICATION,
                target=missing_id,
                original_value=None,
                new_value=resolution_value,
                reason=reason or f"Human specified value for '{target_missing.item_name}'",
                status="COMPLETED",
            )
        )

        new_draft = draft.model_copy(
            update={
                "missing_information": updated_missing,
                "revision": draft.revision + 1,
            }
        )
        return self.registry.save_draft(new_draft)

    def verify_draft(
        self,
        draft_id: str,
        reviewer: str,
        version: str = "1.0.0",
        notes: str = "",
    ) -> VerifiedStrategy:
        """Perform human verification gate and produce an immutable VerifiedStrategy specification.

        Enforces:
        - Human authority requirement (automated or empty reviewer rejected)
        - Verification gate prerequisites (zero unresolved critical items)
        - Deterministic executability check
        - Conversion to standard StrategySpec
        """
        self._validate_reviewer(reviewer)
        draft = self._get_latest_draft(draft_id)

        # Gate Check
        is_ready, blocking_reasons = self.validator.check_verification_readiness(draft)
        if not is_ready:
            raise PermissionError(
                f"Verification gate rejected draft '{draft_id}'. Blocking reasons:\n- "
                + "\n- ".join(blocking_reasons)
            )

        # Evaluate execution compatibility
        exec_status = self.validator.evaluate_executability(draft)

        # Construct deterministic StrategySpec
        spec = self.validator.build_strategy_spec(draft, version=version)

        # Create VerifiedStrategy
        verified = VerifiedStrategy(
            strategy_spec=spec,
            draft_id=draft.draft_id,
            verified_at=datetime.now(timezone.utc),
            verified_by=reviewer,
            status=exec_status,
            version=version,
            notes=notes or "Verified by human operator after structured review.",
            source_materials=draft.material_ids,
        )

        # Persist verified specification
        self.registry.save_verified_strategy(verified)

        # Transition draft status to VERIFIED and save revision
        verified_draft = draft.model_copy(
            update={
                "status": DraftStatus.VERIFIED,
                "revision": draft.revision + 1,
            }
        )
        self.registry.save_draft(verified_draft)

        # Append final review audit record
        self.registry.save_review_record(
            ReviewRecord(
                review_id=f"rev_{uuid.uuid4().hex[:10]}",
                draft_id=draft_id,
                reviewer=reviewer,
                timestamp=datetime.now(timezone.utc),
                action=ReviewAction.APPROVE_DRAFT,
                target="DRAFT",
                original_value=draft.status.value,
                new_value=DraftStatus.VERIFIED.value,
                reason=f"Draft successfully passed verification gate. Status: {exec_status.value}",
                status="COMPLETED",
            )
        )

        return verified

    def _get_latest_draft(self, draft_id: str) -> DraftStrategy:
        draft = self.registry.get_draft(draft_id)
        if not draft:
            raise ValueError(f"Draft with ID '{draft_id}' not found.")
        return draft

    def _validate_reviewer(self, reviewer: str) -> None:
        """Validate that the reviewer identifier represents a specific, named human operator.

        Two-layer check:
        1. Content quality: rejects AI-keyword names AND generic role labels.
        2. Specificity: requires a reviewer identifier that is not a bare generic word.

        Note: Session-level authority (PermissionPolicy.HUMAN_OPERATOR) is the outer
        structural gate enforced by the MCP server BEFORE this method is reached.
        This method is the inner quality check on the identity string itself.
        """
        if not reviewer or not reviewer.strip():
            raise PermissionError("Human reviewer identifier is required. Automated self-approval is forbidden.")

        rev_stripped = reviewer.strip()
        rev_lower = rev_stripped.lower()

        # Layer 1: Reject known AI/automation keywords in reviewer name
        non_human_keywords = ("gemini", "ai", "llm", "system", "auto", "extractor", "bot", "agent")
        if any(kw in rev_lower for kw in non_human_keywords):
            raise PermissionError(
                f"Reviewer '{reviewer}' is not recognized as a human authority. "
                "Only explicit human operators may review or verify strategies."
            )

        # Layer 2: Reject generic role labels that do not identify a specific person.
        # Reviewer must be a named individual (e.g. 'HumanOperator_Alice', 'Harsh_Operator'),
        # NOT a bare generic role word ('human', 'operator', 'user', 'person', 'reviewer').
        generic_role_labels = {"human", "operator", "user", "person", "reviewer", "admin", "anonymous"}
        if rev_lower in generic_role_labels:
            raise PermissionError(
                f"Reviewer identifier '{reviewer}' is too generic. "
                "A specific named human identity is required (e.g. 'HumanOperator_Alice', 'AnalystBob'). "
                "Generic role labels do not establish human authority."
            )
