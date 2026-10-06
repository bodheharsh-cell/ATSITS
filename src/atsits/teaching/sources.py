"""Teaching material creation, normalization, and canonical content hashing."""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Optional
import uuid
from atsits.teaching.models import SourceType, TeachingMaterial


def compute_canonical_content_hash(content: str) -> str:
    """Compute a deterministic SHA-256 hash from canonicalized content string.

    Normalization rules:
    - Normalizes Windows CRLF to standard LF (\\n).
    - Strips leading and trailing whitespace from each line.
    - Strips leading and trailing blank lines.
    - Uses UTF-8 encoding.
    """
    lines = [line.strip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # Strip leading empty lines
    while lines and not lines[0]:
        lines.pop(0)
    # Strip trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    canonical_text = "\n".join(lines)
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def create_teaching_material(
    title: str,
    content: str,
    source_type: SourceType = SourceType.TEXT,
    source_reference: Optional[str] = None,
    material_id: Optional[str] = None,
    version: str = "1.0.0",
    metadata: Optional[Dict[str, Any]] = None,
) -> TeachingMaterial:
    """Create a validated, immutable TeachingMaterial record.

    Calculates deterministic canonical content hash and preserves original text.
    """
    if not title.strip():
        raise ValueError("Teaching material title cannot be empty.")
    if not content.strip():
        raise ValueError("Teaching material content cannot be empty.")

    m_id = material_id or f"mat_{uuid.uuid4().hex[:12]}"
    content_hash = compute_canonical_content_hash(content)

    return TeachingMaterial(
        material_id=m_id,
        source_type=source_type,
        title=title.strip(),
        content=content,
        source_reference=source_reference,
        created_at=datetime.now(timezone.utc),
        content_hash=content_hash,
        version=version,
        metadata=dict(metadata or {}),
    )
