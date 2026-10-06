"""Command line interface for ATSITS Strategy Teaching & Review."""

import argparse
import logging
from pathlib import Path
import sys
from typing import List, Optional
from atsits.teaching.extractor import StrategyExtractor
from atsits.teaching.models import SourceType
from atsits.teaching.registry import TeachingRegistry
from atsits.teaching.reports import generate_draft_review_report, generate_verified_strategy_report
from atsits.teaching.review import HumanReviewEngine
from atsits.teaching.sources import create_teaching_material

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("teaching_cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atsits.teaching",
        description="ATSITS Strategy Teaching & Verified Extraction CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add-material
    p_add = subparsers.add_parser("add-material", help="Register source teaching material")
    p_add.add_argument("--title", required=True, help="Material title")
    p_add.add_argument("--file", help="Path to text or markdown file")
    p_add.add_argument("--text", help="Direct text content")
    p_add.add_argument("--type", default="TEXT", choices=[t.value for t in SourceType], help="Source type")
    p_add.add_argument("--source-ref", help="Source attribution / reference")

    # extract
    p_ext = subparsers.add_parser("extract", help="Extract draft strategy from registered material")
    p_ext.add_argument("--material-id", action="append", required=True, help="Material ID(s) to extract from")
    p_ext.add_argument("--name", help="Strategy name")
    p_ext.add_argument("--version", default="1.0.0", help="Proposed version string")

    # review
    p_rev = subparsers.add_parser("review", help="Display draft strategy review document")
    p_rev.add_argument("draft_id", help="Draft strategy ID")

    # correct-rule
    p_cor = subparsers.add_parser("correct-rule", help="Apply human correction to extracted rule")
    p_cor.add_argument("draft_id", help="Draft strategy ID")
    p_cor.add_argument("--rule-id", required=True, help="Rule ID to correct")
    p_cor.add_argument("--statement", required=True, help="New corrected statement")
    p_cor.add_argument("--reviewer", required=True, help="Human reviewer identifier")
    p_cor.add_argument("--reason", help="Correction rationale")

    # resolve-conflict
    p_conf = subparsers.add_parser("resolve-conflict", help="Resolve detected rule conflict")
    p_conf.add_argument("draft_id", help="Draft strategy ID")
    p_conf.add_argument("--conflict-id", required=True, help="Conflict ID to resolve")
    p_conf.add_argument("--resolution", required=True, help="Human resolution text")
    p_conf.add_argument("--reviewer", required=True, help="Human reviewer identifier")
    p_conf.add_argument("--reason", help="Resolution rationale")

    # clarify
    p_clar = subparsers.add_parser("clarify", help="Provide missing parameter clarification")
    p_clar.add_argument("draft_id", help="Draft strategy ID")
    p_clar.add_argument("--missing-id", required=True, help="Missing item ID")
    p_clar.add_argument("--value", required=True, help="Clarified value")
    p_clar.add_argument("--reviewer", required=True, help="Human reviewer identifier")
    p_clar.add_argument("--reason", help="Clarification rationale")

    # verify
    p_ver = subparsers.add_parser("verify", help="Execute human verification gate")
    p_ver.add_argument("draft_id", help="Draft strategy ID")
    p_ver.add_argument("--reviewer", required=True, help="Human reviewer identifier")
    p_ver.add_argument("--version", default="1.0.0", help="Verified version string")
    p_ver.add_argument("--notes", default="", help="Verification notes")

    # list-materials
    subparsers.add_parser("list-materials", help="List registered teaching materials")

    # list-drafts
    subparsers.add_parser("list-drafts", help="List registered strategy drafts")

    # list-verified
    subparsers.add_parser("list-verified", help="List verified strategy specifications")

    return parser


def main(args: Optional[List[str]] = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)

    registry = TeachingRegistry()
    extractor = StrategyExtractor()
    review_engine = HumanReviewEngine(registry=registry)

    try:
        if parsed.command == "add-material":
            content = parsed.text
            if parsed.file:
                content = Path(parsed.file).read_text(encoding="utf-8")
            if not content:
                print("Error: Either --file or --text must provide content.", file=sys.stderr)
                return 1

            material = create_teaching_material(
                title=parsed.title,
                content=content,
                source_type=SourceType(parsed.type),
                source_reference=parsed.source_ref,
            )
            saved = registry.save_material(material)
            print(f"Registered Material: {saved.material_id} (Hash: {saved.content_hash[:12]}...)")
            return 0

        elif parsed.command == "extract":
            materials = []
            for m_id in parsed.material_id:
                m = registry.get_material(m_id)
                if not m:
                    print(f"Error: Material '{m_id}' not found.", file=sys.stderr)
                    return 1
                materials.append(m)

            draft = extractor.extract_draft(
                materials=materials,
                strategy_name=parsed.name,
                proposed_version=parsed.version,
            )
            saved = registry.save_draft(draft)
            print(f"Extracted Draft Strategy: {saved.draft_id} (Status: {saved.status.value})")
            print(f"  Rules Extracted: {len(saved.rules)} | Ambiguities: {len(saved.ambiguities)} | Missing: {len(saved.missing_information)}")
            return 0

        elif parsed.command == "review":
            draft = registry.get_draft(parsed.draft_id)
            if not draft:
                print(f"Error: Draft '{parsed.draft_id}' not found.", file=sys.stderr)
                return 1
            reviews = registry.list_reviews_for_draft(parsed.draft_id)
            print(generate_draft_review_report(draft, reviews))
            return 0

        elif parsed.command == "correct-rule":
            draft = review_engine.correct_rule(
                draft_id=parsed.draft_id,
                rule_id=parsed.rule_id,
                new_statement=parsed.statement,
                reviewer=parsed.reviewer,
                reason=parsed.reason,
            )
            print(f"Corrected Rule {parsed.rule_id} in Draft {draft.draft_id} (Revision {draft.revision})")
            return 0

        elif parsed.command == "resolve-conflict":
            draft = review_engine.resolve_conflict(
                draft_id=parsed.draft_id,
                conflict_id=parsed.conflict_id,
                resolution_text=parsed.resolution,
                reviewer=parsed.reviewer,
                reason=parsed.reason,
            )
            print(f"Resolved Conflict {parsed.conflict_id} in Draft {draft.draft_id} (Revision {draft.revision})")
            return 0

        elif parsed.command == "clarify":
            draft = review_engine.provide_clarification(
                draft_id=parsed.draft_id,
                missing_id=parsed.missing_id,
                resolution_value=parsed.value,
                reviewer=parsed.reviewer,
                reason=parsed.reason,
            )
            print(f"Clarified Missing Item {parsed.missing_id} in Draft {draft.draft_id} (Revision {draft.revision})")
            return 0

        elif parsed.command == "verify":
            verified = review_engine.verify_draft(
                draft_id=parsed.draft_id,
                reviewer=parsed.reviewer,
                version=parsed.version,
                notes=parsed.notes,
            )
            print(f"Successfully Verified Strategy: {verified.strategy_spec.name} v{verified.version}")
            print(f"  Execution Status: {verified.status.value}")
            print(f"  Verified By: {verified.verified_by}")
            return 0

        elif parsed.command == "list-materials":
            materials = registry.list_materials()
            print(f"Total Registered Materials: {len(materials)}")
            for m in materials:
                print(f" - [{m.material_id}] {m.title} ({m.source_type.value}, Hash: {m.content_hash[:10]}...)")
            return 0

        elif parsed.command == "list-drafts":
            drafts = registry.list_drafts()
            print(f"Total Strategy Drafts: {len(drafts)}")
            for d in drafts:
                print(f" - [{d.draft_id}] {d.strategy_name} (Status: {d.status.value}, Rev: {d.revision})")
            return 0

        elif parsed.command == "list-verified":
            verified_list = registry.list_verified_strategies()
            print(f"Total Verified Strategies: {len(verified_list)}")
            for v in verified_list:
                print(f" - [{v.strategy_spec.strategy_id}] {v.strategy_spec.name} v{v.version} ({v.status.value}, Verified by {v.verified_by})")
            return 0

    except Exception as e:
        logger.error("Command failed: %s", str(e))
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
