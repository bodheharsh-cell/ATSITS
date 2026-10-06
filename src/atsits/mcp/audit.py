"""Append-only audit logging for MCP interactions."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class MCPAuditEntry(BaseModel):
    """Immutable audit record representing a single MCP tool invocation."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC timestamp of invocation")
    request_id: str = Field(..., min_length=1, description="Unique request identifier")
    tool_name: str = Field(..., min_length=1, description="Invoked tool name")
    category: str = Field(..., description="Tool category: READ or ACTION")
    input_summary: Dict[str, Any] = Field(default_factory=dict, description="Sanitized summary of arguments")
    duration_ms: float = Field(..., ge=0.0, description="Execution duration in milliseconds")
    status: str = Field(..., description="Invocation outcome: SUCCESS or ERROR")
    error_code: Optional[str] = Field(None, description="Structured error code if failed")
    error_message: Optional[str] = Field(None, description="Error message if failed")


def sanitize_input(arguments: Dict[str, Any], max_str_len: int = 200) -> Dict[str, Any]:
    """Sanitize and truncate arguments for safe audit recording without secrets."""
    sanitized: Dict[str, Any] = {}
    sensitive_keys = {"api_key", "secret", "password", "token", "auth"}

    for k, v in arguments.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > max_str_len:
            sanitized[k] = v[:max_str_len] + "...[TRUNCATED]"
        elif isinstance(v, (int, float, bool, type(None))):
            sanitized[k] = v
        elif isinstance(v, dict):
            sanitized[k] = sanitize_input(v, max_str_len=max_str_len)
        else:
            sanitized[k] = str(v)[:max_str_len]

    return sanitized


class MCPAuditLogger:
    """Persistent append-only audit logger for MCP interactions."""

    def __init__(self, file_path: Optional[Union[str, Path]] = None):
        if file_path is None:
            self.file_path = Path("data/mcp/audit.jsonl").resolve()
        else:
            self.file_path = Path(file_path).resolve()

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._in_memory_log: List[MCPAuditEntry] = []

    def log_invocation(
        self,
        request_id: str,
        tool_name: str,
        category: str,
        arguments: Dict[str, Any],
        duration_ms: float,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> MCPAuditEntry:
        """Log a tool invocation to persistent audit log and memory."""
        entry = MCPAuditEntry(
            timestamp=datetime.now(timezone.utc),
            request_id=request_id,
            tool_name=tool_name,
            category=category,
            input_summary=sanitize_input(arguments),
            duration_ms=duration_ms,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )

        self._in_memory_log.append(entry)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        return entry

    def get_entries(self) -> List[MCPAuditEntry]:
        """Return all logged audit entries in memory."""
        return list(self._in_memory_log)
