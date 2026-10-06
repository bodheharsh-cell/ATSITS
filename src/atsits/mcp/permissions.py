"""Permission layer enforcing strict boundaries for MCP interactions."""

from enum import Enum
from typing import Set
from atsits.mcp.schemas import ErrorCode, ToolCategory, ToolErrorResponse


class PermissionLevel(str, Enum):
    """Configurable permission levels for MCP clients.

    - READ_ONLY: Can only call READ-category tools. Cannot modify anything.
    - RESEARCH: Can call READ and ACTION tools, but CANNOT perform human
      verification or strategy promotion. Intended for Gemini/LLM callers.
    - HUMAN_OPERATOR: Can call all tools INCLUDING human review and
      verification actions. Intended for explicit human-initiated sessions
      (CLI, interactive scripts). This is the deterministic session-level
      authority boundary — not a caller-supplied string claim.
    """

    READ_ONLY = "READ_ONLY"
    RESEARCH = "RESEARCH"
    HUMAN_OPERATOR = "HUMAN_OPERATOR"


# Tools that may ONLY be invoked by a HUMAN_OPERATOR session.
# An autonomous Gemini/AI MCP caller (RESEARCH level) is barred from these
# regardless of what reviewer name it supplies in the payload.
HUMAN_OPERATOR_ONLY_TOOLS: Set[str] = {
    "submit_human_review",
}

PROHIBITED_OPERATIONS: Set[str] = {
    "modify_strategy_code",
    "promote_strategy",
    "promote_strategy_autonomously",
    "deploy_strategy",
    "execute_live_order",
    "execute_paper_order",
    "execute_arbitrary_python",
    "execute_shell_command",
    "write_arbitrary_file",
    "verify_strategy_autonomously",
    "approve_draft_autonomously",
    "execute_strategy",
    "generate_trading_code",
}


class PermissionPolicy:
    """Enforces execution boundaries and prevents prohibited actions through MCP."""

    def __init__(self, permission_level: PermissionLevel = PermissionLevel.RESEARCH):
        self.permission_level = permission_level

    @property
    def is_human_session(self) -> bool:
        """True only when this policy was explicitly constructed at HUMAN_OPERATOR level."""
        return self.permission_level == PermissionLevel.HUMAN_OPERATOR

    def validate_tool_access(self, tool_name: str, category: ToolCategory) -> None:
        """Validate whether the requested tool invocation is permitted.

        Raises:
            PermissionError: If the tool operation violates configured permission policy.
        """
        if tool_name in PROHIBITED_OPERATIONS:
            raise PermissionError(
                f"Operation '{tool_name}' is strictly prohibited by ATSITS safety boundaries."
            )

        if self.permission_level == PermissionLevel.READ_ONLY and category != ToolCategory.READ:
            raise PermissionError(
                f"Action tool '{tool_name}' is not permitted under READ_ONLY permission level."
            )

        # Gate: human-operator-only tools require a HUMAN_OPERATOR session.
        # A RESEARCH-level caller (Gemini/LLM/automation) is rejected here
        # regardless of any reviewer name they claim in the tool arguments.
        if tool_name in HUMAN_OPERATOR_ONLY_TOOLS and not self.is_human_session:
            raise PermissionError(
                f"Tool '{tool_name}' requires a HUMAN_OPERATOR session. "
                "Autonomous callers (RESEARCH/READ_ONLY) cannot perform human review or "
                "strategy verification regardless of the reviewer name supplied. "
                "This session is operating at permission level: "
                f"'{self.permission_level.value}'."
            )
