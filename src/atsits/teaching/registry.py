"""Append-only persistent registry for teaching materials, drafts, reviews, and verified strategies."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from atsits.teaching.models import (
    ConflictRecord,
    DraftStrategy,
    ReviewRecord,
    TeachingMaterial,
    VerifiedStrategy,
)

logger = logging.getLogger(__name__)


class TeachingRegistry:
    """Manages append-only JSONL persistence for the teaching and extraction pipeline."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("data/teaching")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.materials_file = self.base_dir / "materials.jsonl"
        self.drafts_file = self.base_dir / "drafts.jsonl"
        self.reviews_file = self.base_dir / "reviews.jsonl"
        self.verified_file = self.base_dir / "verified_strategies.jsonl"
        self.conflicts_file = self.base_dir / "conflicts.jsonl"

    def save_material(self, material: TeachingMaterial) -> TeachingMaterial:
        """Persist a teaching material record to append-only log.

        If a material with identical content hash already exists, returns existing record.
        """
        existing = self.get_material_by_hash(material.content_hash)
        if existing:
            logger.info("Material with content hash %s already exists as %s", material.content_hash, existing.material_id)
            return existing

        data = material.model_dump(mode="json")
        with open(self.materials_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        return material

    def get_material(self, material_id: str) -> Optional[TeachingMaterial]:
        """Retrieve teaching material by ID."""
        if not self.materials_file.exists():
            return None
        with open(self.materials_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("material_id") == material_id:
                    return TeachingMaterial.model_validate(record)
        return None

    def get_material_by_hash(self, content_hash: str) -> Optional[TeachingMaterial]:
        """Retrieve teaching material by canonical content hash."""
        if not self.materials_file.exists():
            return None
        with open(self.materials_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("content_hash") == content_hash:
                    return TeachingMaterial.model_validate(record)
        return None

    def list_materials(self) -> List[TeachingMaterial]:
        """List all registered teaching materials."""
        if not self.materials_file.exists():
            return []
        materials = []
        with open(self.materials_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                materials.append(TeachingMaterial.model_validate(json.loads(line)))
        return materials

    def save_draft(self, draft: DraftStrategy) -> DraftStrategy:
        """Persist a draft strategy revision to append-only log.

        Never overwrites previous revisions; appends new revision snapshot.
        """
        data = draft.model_dump(mode="json")
        with open(self.drafts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

        # Also persist conflicts if any
        if draft.conflicts:
            self.save_conflicts(draft.conflicts)

        return draft

    def get_draft(self, draft_id: str, revision: Optional[int] = None) -> Optional[DraftStrategy]:
        """Retrieve draft strategy. If revision is None, returns the latest revision."""
        if not self.drafts_file.exists():
            return None
        matching = []
        with open(self.drafts_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("draft_id") == draft_id:
                    matching.append(DraftStrategy.model_validate(record))

        if not matching:
            return None

        if revision is not None:
            for d in matching:
                if d.revision == revision:
                    return d
            return None

        # Return latest revision
        matching.sort(key=lambda d: d.revision)
        return matching[-1]

    def list_drafts(self) -> List[DraftStrategy]:
        """List the latest revision of all draft strategies."""
        if not self.drafts_file.exists():
            return []
        drafts_by_id: Dict[str, DraftStrategy] = {}
        with open(self.drafts_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                draft = DraftStrategy.model_validate(json.loads(line))
                current = drafts_by_id.get(draft.draft_id)
                if current is None or draft.revision >= current.revision:
                    drafts_by_id[draft.draft_id] = draft
        return list(drafts_by_id.values())

    def save_review_record(self, record: ReviewRecord) -> ReviewRecord:
        """Append a review record to the immutable review audit log."""
        data = record.model_dump(mode="json")
        with open(self.reviews_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        return record

    def list_reviews_for_draft(self, draft_id: str) -> List[ReviewRecord]:
        """Retrieve all review records for a specific draft in chronological order."""
        if not self.reviews_file.exists():
            return []
        reviews = []
        with open(self.reviews_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("draft_id") == draft_id:
                    reviews.append(ReviewRecord.model_validate(record))
        return reviews

    def save_conflicts(self, conflicts: List[ConflictRecord]) -> None:
        """Append detected conflicts to the conflicts log."""
        with open(self.conflicts_file, "a", encoding="utf-8") as f:
            for c in conflicts:
                f.write(json.dumps(c.model_dump(mode="json")) + "\n")

    def save_verified_strategy(self, verified: VerifiedStrategy) -> VerifiedStrategy:
        """Append a human-verified strategy specification to immutable verified storage."""
        data = verified.model_dump(mode="json")
        with open(self.verified_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        return verified

    def get_verified_strategy(self, strategy_id: str, version: Optional[str] = None) -> Optional[VerifiedStrategy]:
        """Retrieve verified strategy by strategy_id and optional version."""
        if not self.verified_file.exists():
            return None
        matching = []
        with open(self.verified_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("strategy_spec", {}).get("strategy_id") == strategy_id:
                    matching.append(VerifiedStrategy.model_validate(record))

        if not matching:
            return None

        if version is not None:
            for v in matching:
                if v.version == version:
                    return v
            return None

        # Return latest
        return matching[-1]

    def list_verified_strategies(self) -> List[VerifiedStrategy]:
        """List all verified strategies."""
        if not self.verified_file.exists():
            return []
        verified = []
        with open(self.verified_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                verified.append(VerifiedStrategy.model_validate(json.loads(line)))
        return verified
