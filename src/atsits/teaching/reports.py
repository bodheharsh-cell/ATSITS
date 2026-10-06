"""Markdown and text reporting generators for strategy teaching and review."""

from typing import List, Optional
from atsits.teaching.models import (
    ConflictStatus,
    DraftStrategy,
    MissingInfoStatus,
    ReviewRecord,
    TeachingMaterial,
    VerifiedStrategy,
)


def generate_draft_review_report(draft: DraftStrategy, reviews: Optional[List[ReviewRecord]] = None) -> str:
    """Generate a clean, structured Markdown review document for a draft strategy."""
    lines = [
        f"# Draft Strategy Review: {draft.strategy_name} (Revision {draft.revision})",
        "",
        f"**Draft ID:** `{draft.draft_id}`  ",
        f"**Status:** `{draft.status.value}`  ",
        f"**Proposed Version:** `{draft.proposed_version}`  ",
        f"**Timeframe:** `{draft.timeframe or 'UNSPECIFIED'}`  ",
        f"**Instruments:** `{', '.join(draft.instruments) if draft.instruments else 'UNSPECIFIED'}`  ",
        f"**Concepts:** `{', '.join(draft.concepts)}`  ",
        "",
        "---",
        "",
        "## 1. Extracted Execution Sequence",
        "",
    ]

    if draft.sequencing:
        for idx, step in enumerate(draft.sequencing, 1):
            lines.append(f"{idx}. **{step}**")
    else:
        lines.append("*No explicit execution sequence identified.*")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Extracted Rules & Source Traceability",
        "",
        "| Rule ID | Category | Statement | Certainty | Status | Source Location |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for r in draft.rules:
        src = f"`{r.source_material_id}` ({r.source_reference or 'N/A'})"
        lines.append(f"| `{r.rule_id}` | `{r.category.value}` | {r.statement} | `{r.certainty.value}` | `{r.status.value}` | {src} |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Ambiguities & Uncertainties",
        "",
    ])

    if draft.ambiguities:
        for a in draft.ambiguities:
            lines.append(f"- ⚠️ {a}")
    else:
        lines.append("*No unresolved ambiguities detected.*")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Rule Conflicts",
        "",
    ])

    if draft.conflicts:
        for c in draft.conflicts:
            status_icon = "✅" if c.status == ConflictStatus.RESOLVED_BY_HUMAN else "❌"
            lines.append(f"- {status_icon} **[{c.status.value}]** {c.description}")
            lines.append(f"  - Rules: `{c.rule_a_id}` (Source: {c.source_a}) vs `{c.rule_b_id}` (Source: {c.source_b})")
            if c.resolution:
                lines.append(f"  - **Resolution:** {c.resolution}")
    else:
        lines.append("*No rule conflicts detected.*")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Missing Information (Required for Deterministic Execution)",
        "",
    ])

    if draft.missing_information:
        for m in draft.missing_information:
            status_icon = "✅" if m.status == MissingInfoStatus.RESOLVED_BY_HUMAN else "❌"
            crit = "CRITICAL" if m.critical else "OPTIONAL"
            lines.append(f"- {status_icon} **[{m.status.value}] [{crit}] {m.item_name}**: {m.description}")
            if m.resolution:
                lines.append(f"  - **Human Value:** `{m.resolution}`")
    else:
        lines.append("*No missing parameters identified.*")

    if reviews:
        lines.extend([
            "",
            "---",
            "",
            "## 6. Review Audit Trail",
            "",
            "| Timestamp | Reviewer | Action | Target | Details |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for rev in reviews:
            ts = rev.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"| {ts} | `{rev.reviewer}` | `{rev.action.value}` | `{rev.target}` | {rev.reason or rev.new_value or ''} |")

    return "\n".join(lines)


def generate_verified_strategy_report(verified: VerifiedStrategy) -> str:
    """Generate a summary report for a verified strategy specification."""
    spec = verified.strategy_spec
    lines = [
        f"# Verified Strategy Specification: {spec.name} ({verified.version})",
        "",
        f"**Strategy ID:** `{spec.strategy_id}`  ",
        f"**Version:** `{verified.version}`  ",
        f"**Execution Status:** `{verified.status.value}`  ",
        f"**Verified By:** `{verified.verified_by}`  ",
        f"**Verified At:** `{verified.verified_at.strftime('%Y-%m-%d %H:%M:%S UTC')}`  ",
        f"**Original Draft ID:** `{verified.draft_id}`  ",
        f"**Source Materials:** `{', '.join(verified.source_materials)}`  ",
        "",
        "---",
        "",
        "## Verified Parameters",
        "",
        "```json",
        "{\n" + ",\n".join([f'  "{k}": {v}' for k, v in spec.parameters.items()]) + "\n}",
        "```",
        "",
        "## Verification Notes",
        "",
        verified.notes or "*No additional constraints.*",
    ]
    return "\n".join(lines)
