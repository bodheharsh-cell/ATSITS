"""Read-only MCP resources providing contextual system facts and teaching records."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from atsits.learning.hypotheses import HypothesisRegistry
from atsits.learning.registry import ExperimentRegistry
from atsits.mcp.tools import MCPToolRegistry
from atsits.teaching.registry import TeachingRegistry


class MCPResourceManager:
    """Provides read-only MCP resources."""

    def __init__(self, tool_registry: Optional[MCPToolRegistry] = None):
        self.tools = tool_registry or MCPToolRegistry()
        self.hypothesis_registry = self.tools.hypothesis_registry
        self.experiment_registry = self.tools.experiment_registry
        self.teaching_registry = self.tools.teaching_registry

    def list_resources(self) -> List[Dict[str, str]]:
        """List all available read-only resources."""
        return [
            {
                "uri": "strategy://current",
                "name": "Current Strategy Specification",
                "mimeType": "application/json",
            },
            {
                "uri": "strategy://versions",
                "name": "Available Strategy Versions",
                "mimeType": "application/json",
            },
            {
                "uri": "research://experiments",
                "name": "Recorded Experiments",
                "mimeType": "application/json",
            },
            {
                "uri": "research://hypotheses",
                "name": "Registered Research Hypotheses",
                "mimeType": "application/json",
            },
            {
                "uri": "teaching://materials",
                "name": "Registered Teaching Materials",
                "mimeType": "application/json",
            },
            {
                "uri": "teaching://drafts",
                "name": "Draft Strategy Revisions",
                "mimeType": "application/json",
            },
            {
                "uri": "teaching://verified",
                "name": "Verified Strategy Specifications",
                "mimeType": "application/json",
            },
            {
                "uri": "system://status",
                "name": "ATSITS System Status",
                "mimeType": "application/json",
            },
        ]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read resource content by URI."""
        clean_uri = uri.strip().lower()

        if clean_uri == "strategy://current":
            return self.tools.handle_get_strategy({})

        elif clean_uri == "strategy://versions":
            return {
                "production_version": "1.0.0",
                "available_versions": ["1.0.0"],
                "strategy_name": "EMA_Pullback_v1.0",
            }

        elif clean_uri == "research://experiments":
            exps = self.experiment_registry.list_all()
            return {
                "total_experiments": len(exps),
                "experiments": [
                    {
                        "experiment_id": e.experiment_id,
                        "hypothesis_id": e.hypothesis_id,
                        "candidate_version": e.candidate_strategy_version,
                        "validation_passed": e.validation_passed,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in exps
                ],
            }

        elif clean_uri == "research://hypotheses":
            hyps = self.hypothesis_registry.list_all()
            return {
                "total_hypotheses": len(hyps),
                "hypotheses": [h.model_dump() for h in hyps],
            }

        elif clean_uri == "teaching://materials":
            materials = self.teaching_registry.list_materials()
            return {
                "total_materials": len(materials),
                "materials": [
                    {
                        "material_id": m.material_id,
                        "title": m.title,
                        "source_type": m.source_type.value,
                        "content_hash": m.content_hash,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in materials
                ],
            }

        elif clean_uri == "teaching://drafts":
            drafts = self.teaching_registry.list_drafts()
            return {
                "total_drafts": len(drafts),
                "drafts": [
                    {
                        "draft_id": d.draft_id,
                        "strategy_name": d.strategy_name,
                        "status": d.status.value,
                        "revision": d.revision,
                    }
                    for d in drafts
                ],
            }

        elif clean_uri == "teaching://verified":
            verified = self.teaching_registry.list_verified_strategies()
            return {
                "total_verified": len(verified),
                "verified_strategies": [
                    {
                        "strategy_id": v.strategy_spec.strategy_id,
                        "name": v.strategy_spec.name,
                        "version": v.version,
                        "status": v.status.value,
                        "verified_by": v.verified_by,
                    }
                    for v in verified
                ],
            }

        elif clean_uri == "system://status":
            dataset_file = Path("data/btcusdt_1h.csv")
            return {
                "system_name": "ATSITS",
                "system_status": "OPERATIONAL",
                "execution_mode": "RESEARCH_MCP",
                "production_strategy": "EMA_Pullback_v1.0",
                "dataset_available": dataset_file.is_file(),
            }

        raise KeyError(f"Resource URI '{uri}' not found.")
