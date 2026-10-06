"""Interactive runtime coordinating Gemini LLM reasoning, ATSITS MCP tools, and automatic routing."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional, Set
from atsits.gemini.client import GeminiClient, _get_model_display_name, categorize_error
from atsits.gemini.config import GeminiConfig, load_gemini_config, validate_model_id
from atsits.gemini.exceptions import (
    AllModelsUnavailableError,
    CriticalTaskDowngradePreventedError,
    GeminiAPIError,
    GeminiAuthError,
    GeminiError,
    GeminiNotConfiguredError,
    GeminiQuotaExceededError,
)
from atsits.gemini.prompts import ATSITS_SYSTEM_INSTRUCTION
from atsits.gemini.router import (
    FailureCategory,
    ModelHealthTracker,
    ModelRouter,
    RoutingMetadata,
    RoutingMode,
    TaskClass,
    TaskClassification,
    TaskClassifier,
)
from atsits.mcp.client import MCPClient

logger = logging.getLogger(__name__)

# State-changing MCP tools that must NEVER be executed more than once per user request
STATE_CHANGING_TOOLS: Set[str] = {
    "place_paper_order",
    "close_paper_position",
    "submit_human_review",
    "create_teaching_material",
    "extract_strategy_draft",
    "run_backtest",
    "run_experiment",
    "propose_strategy_change",
}


def _clean_schema_dict(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure JSON Schema dictionary is strictly JSON-serializable."""
    clean = {}
    for k, v in schema.items():
        if isinstance(v, dict):
            clean[k] = _clean_schema_dict(v)
        elif isinstance(v, list):
            clean[k] = [
                _clean_schema_dict(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            clean[k] = v
    return clean


class GeminiMCPRuntime:
    """Orchestrates multi-turn conversation, automatic task-aware routing, and MCP tools."""

    config: GeminiConfig
    client: GeminiClient
    mcp_client: MCPClient
    router: ModelRouter

    def __init__(
        self,
        config: Optional[GeminiConfig] = None,
        client: Optional[GeminiClient] = None,
        mcp_client: Optional[MCPClient] = None,
        router: Optional[ModelRouter] = None,
        system_instruction: Optional[str] = None,
    ):
        self.config = config or load_gemini_config()
        self.client = client or GeminiClient(config=self.config)
        self.mcp_client = mcp_client or MCPClient()
        self.system_instruction = system_instruction or ATSITS_SYSTEM_INSTRUCTION
        self.history: List[Any] = []
        self._tools_cache: Optional[List[Any]] = None

        default_mode = RoutingMode.AUTO if self.config.is_auto else RoutingMode.MANUAL
        self.router = router or ModelRouter(default_mode=default_mode)
        self.last_routing_metadata: Optional[RoutingMetadata] = None
        self._last_test_result: Optional[Tuple[bool, str, Dict[str, Any]]] = None
        self._last_test_timestamp: Optional[datetime] = None
        self._test_cache_ttl_seconds: float = 30.0

    @property
    def is_configured(self) -> bool:
        """Return True if Gemini is configured with an API key."""
        return self.client.is_configured

    @property
    def selection_mode(self) -> str:
        """Return active selection mode: AUTO or MANUAL."""
        return self.router.mode.value

    @property
    def current_model(self) -> str:
        """Return the active model identifier."""
        if self.router.mode == RoutingMode.AUTO and self.last_routing_metadata:
            return self.last_routing_metadata.selected_model
        return self.config.model_name

    def set_mode(self, mode: str) -> str:
        """Switch selection mode between AUTO and MANUAL."""
        clean_mode = "AUTO" if (mode or "").strip().upper() == "AUTO" else "MANUAL"
        self.router.mode = RoutingMode.AUTO if clean_mode == "AUTO" else RoutingMode.MANUAL
        new_config = self.config.with_selection_mode(clean_mode)
        self.config = new_config
        self.client.config = new_config
        self._last_test_result = None
        logger.info("Gemini selection mode set to: %s", clean_mode)
        return clean_mode

    def set_model(self, model_id: str) -> str:
        """Switch model. If 'auto', enables AUTO mode; otherwise sets specific model in MANUAL mode."""
        clean_id = (model_id or "").strip()
        if clean_id.lower() in ("auto", "router", "default"):
            self.set_mode("AUTO")
            logger.info("Active Gemini model mode set to AUTO (automatic task routing).")
            return "auto"

        validated = validate_model_id(clean_id)
        self.set_mode("MANUAL")
        new_config = self.config.with_model(validated)
        self.config = new_config
        self.client.config = new_config
        self._last_test_result = None
        logger.info("Active Gemini model manually set to: %s (%s)", validated, self.config.display_name)
        return validated

    def test_connection(self, force: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
        """Test Gemini API connectivity taking router mode and candidate health into account.

        Args:
            force: If True, bypass in-memory TTL cache and perform a fresh network probe.

        Returns:
            Tuple of (success: bool, message: str, meta: Dict[str, Any])
        """
        if not self.is_configured:
            return (
                False,
                "Gemini API key is not configured. ATSITS will run in deterministic offline mode. "
                "Set GEMINI_API_KEY in your environment or .env file to enable Gemini.",
                {
                    "status": "NOT_CONFIGURED",
                    "model": self.config.model_name,
                    "display_name": self.config.display_name,
                    "mode": self.selection_mode,
                },
            )

        now = datetime.now(timezone.utc)
        if not force and self._last_test_result is not None and self._last_test_timestamp is not None:
            if (now - self._last_test_timestamp).total_seconds() < self._test_cache_ttl_seconds:
                return self._last_test_result

        def _cache_and_return(res: Tuple[bool, str, Dict[str, Any]]) -> Tuple[bool, str, Dict[str, Any]]:
            self._last_test_result = res
            self._last_test_timestamp = datetime.now(timezone.utc)
            return res

        # 1. MANUAL Mode
        if self.router.mode != RoutingMode.AUTO:
            target_model = self.config.model_name
            success, msg = self.client.test_connection(model=target_model)
            if success:
                status = "ONLINE"
            elif any(k in msg.lower() for k in ("quota", "429", "resource_exhausted")):
                status = "QUOTA_EXHAUSTED"
            elif any(k in msg.lower() for k in ("auth", "401", "403", "key")):
                status = "AUTH_ERROR"
            else:
                status = "OFFLINE"

            return _cache_and_return((
                success,
                msg,
                {
                    "status": status,
                    "model": target_model,
                    "display_name": self.config.display_name,
                    "mode": "MANUAL",
                },
            ))

        # 2. AUTO Mode: probe candidate chain (prioritizing lightweight/healthy models)
        candidates = self.router.resolve_candidate_chain(TaskClass.SIMPLE)
        last_msg = ""
        quota_failures = 0

        for model_id in candidates:
            # Skip if explicitly in cooldown unless all are in cooldown
            if not self.router.health_tracker.is_available(model_id):
                quota_failures += 1
                continue

            success, msg = self.client.test_connection(model=model_id)
            last_msg = msg
            if success:
                disp = _get_model_display_name(model_id)
                return _cache_and_return((
                    True,
                    msg,
                    {
                        "status": "ONLINE",
                        "model": model_id,
                        "display_name": f"⚡ Auto Router ({disp})",
                        "mode": "AUTO",
                    },
                ))

            # Record failure in health tracker
            if any(k in msg.lower() for k in ("quota", "429", "resource_exhausted")):
                self.router.health_tracker.record_failure(
                    model_id,
                    GeminiQuotaExceededError(msg, model_name=model_id),
                )
                quota_failures += 1
            elif any(k in msg.lower() for k in ("auth", "401", "403", "key")):
                return _cache_and_return((
                    False,
                    msg,
                    {
                        "status": "AUTH_ERROR",
                        "model": model_id,
                        "display_name": "⚡ Auto Router",
                        "mode": "AUTO",
                    },
                ))

        if quota_failures >= len(candidates):
            return _cache_and_return((
                False,
                "All Gemini candidate models quota exhausted. Try again later or switch models.",
                {
                    "status": "QUOTA_EXHAUSTED",
                    "model": "auto",
                    "display_name": "⚡ Auto Router (Quota Exhausted)",
                    "mode": "AUTO",
                },
            ))

        return _cache_and_return((
            False,
            last_msg or "Gemini connection failed",
            {
                "status": "OFFLINE",
                "model": "auto",
                "display_name": "⚡ Auto Router (Offline)",
                "mode": "AUTO",
            },
        ))

    def reset(self) -> None:
        """Clear in-memory conversation history."""
        self.history = []

    def _get_tools(self) -> List[Any]:
        """Construct Gemini Tools list from MCP server tool declarations."""
        if self._tools_cache is not None:
            return self._tools_cache

        from google.genai import types

        mcp_tools = self.mcp_client.list_tools()
        function_declarations = []

        for tool in mcp_tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            schema = tool.get("inputSchema") or tool.get("input_schema") or {}
            cleaned_schema = _clean_schema_dict(schema)

            fd = types.FunctionDeclaration(
                name=name,
                description=description,
                parameters_json_schema=cleaned_schema if cleaned_schema else None,
            )
            function_declarations.append(fd)

        self._tools_cache = [types.Tool(function_declarations=function_declarations)]
        return self._tools_cache

    def send_message(
        self,
        message: str,
        on_tool_call: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a user message to Gemini, execute any MCP tool calls, and return final text response.

        Includes automatic task classification, model routing, and quota fallback with
        strict protection against re-executing state-changing MCP actions on retry.
        """
        if not self.is_configured:
            raise GeminiNotConfiguredError(
                "Gemini API is not configured. Set GEMINI_API_KEY environment variable or in .env file."
            )

        from google.genai import types

        # 1. Deterministic Task Classification
        task_classification = self.router.classify_task(message, context=context)

        # 2. Model Selection (AUTO or MANUAL)
        active_model, routing_meta = self.router.select_initial_model(
            task_classification=task_classification,
            manual_override_model=self.config.model_name,
        )
        self.last_routing_metadata = routing_meta
        logger.info(
            "Routed task [%s] to model: %s (mode=%s, reason=%s)",
            task_classification.task_class.value,
            active_model,
            self.router.mode.value,
            routing_meta.selection_reason,
        )

        # Append user turn
        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        )
        self.history.append(user_content)

        tools = self._get_tools()

        # Track state-changing actions executed during this user request by canonical signature
        # Prevents re-executing identical state-changing actions on fallback while allowing distinct sequential actions
        executed_action_signatures: Set[str] = set()
        is_critical = (task_classification.task_class == TaskClass.CRITICAL)

        turn_count = 0
        while turn_count < self.config.max_turns:
            turn_count += 1

            # Build config with thinking support where available
            thinking_cfg = self.router.build_thinking_config(active_model, task_classification)
            gen_config = types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=self.config.temperature,
                tools=tools,
                thinking_config=thinking_cfg,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

            # Execution attempt with quota fallback loop
            response = None
            max_fallback_attempts = 3
            current_attempt = 0

            while current_attempt <= max_fallback_attempts:
                try:
                    response = self.client.generate_content(
                        contents=self.history,
                        config=gen_config,
                        model=active_model,
                        allow_thinking_fallback=(not is_critical),
                    )
                    # Successful call -> record health
                    self.router.health_tracker.record_success(active_model)
                    break

                except Exception as exc:
                    cat = categorize_error(exc)
                    self.router.health_tracker.record_failure(active_model, cat, str(exc))

                    # Authentication failure: DO NOT retry other models
                    if cat == FailureCategory.AUTHENTICATION_ERROR or isinstance(exc, GeminiAuthError):
                        logger.error("Authentication error on %s; stopping fallback.", active_model)
                        raise

                    # In MANUAL mode: do not automatically switch models
                    if self.router.mode == RoutingMode.MANUAL:
                        raise

                    current_attempt += 1
                    if current_attempt > max_fallback_attempts:
                        logger.error("Max fallback attempts (%d) reached.", max_fallback_attempts)
                        raise AllModelsUnavailableError(
                            f"Max fallback attempts reached; all suitable models exhausted: {exc}"
                        ) from exc

                    # Attempt to resolve fallback model
                    try:
                        fallback_model, new_routing_meta = self.router.get_fallback_model(
                            current_model=active_model,
                            task_classification=task_classification,
                            failure_category=cat,
                            attempt=routing_meta.fallback_attempt,
                        )
                        logger.warning(
                            "Gemini model fallback [%d]: %s -> %s (Reason: %s)",
                            current_attempt,
                            active_model,
                            fallback_model,
                            cat.value,
                        )
                        active_model = fallback_model
                        routing_meta = new_routing_meta
                        self.last_routing_metadata = routing_meta

                        # Rebuild config for fallback model
                        thinking_cfg = self.router.build_thinking_config(active_model, task_classification)
                        gen_config = types.GenerateContentConfig(
                            system_instruction=self.system_instruction,
                            temperature=self.config.temperature,
                            tools=tools,
                            thinking_config=thinking_cfg,
                        )
                        # NOTE: MCP Action Safety:
                        # self.history already contains all tool responses up to this turn.
                        # The fallback model continues with existing history without re-executing tools.

                    except (AllModelsUnavailableError, CriticalTaskDowngradePreventedError):
                        raise
                    except Exception as fallback_exc:
                        logger.error("Failed to resolve fallback model: %s", fallback_exc)
                        raise

            if response is None:
                raise GeminiAPIError("Failed to generate response after all fallback attempts.")

            # Check for candidate content
            candidate = response.candidates[0] if (response.candidates and len(response.candidates) > 0) else None
            if not candidate or not candidate.content:
                return response.text or ""

            # Check for function calls
            function_calls = response.function_calls or []

            if not function_calls:
                # Pure text response from Gemini
                self.history.append(candidate.content)
                text_parts = []
                for part in candidate.content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                return "\n".join(text_parts) if text_parts else (response.text or "")

            # If function calls were produced:
            self.history.append(candidate.content)
            response_parts = []

            for fc in function_calls:
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}

                import json
                try:
                    args_repr = json.dumps(tool_args, sort_keys=True, default=str)
                except Exception:
                    args_repr = str(sorted(tool_args.items()))
                action_sig = f"{tool_name}:{args_repr}"

                # MCP Action Duplicate Protection:
                # Prevent duplicate execution of identical state-changing actions on fallback or within the same turn,
                # while allowing legitimate distinct sequential actions (e.g. multi-step teaching).
                if tool_name in STATE_CHANGING_TOOLS and action_sig in executed_action_signatures:
                    logger.warning(
                        "MCP Action Safety: duplicate state-changing tool call prevented: %s (%s)",
                        tool_name,
                        tool_args,
                    )
                    mcp_result = {
                        "is_error": True,
                        "error": f"Action '{tool_name}' with identical parameters was already executed in this workflow and cannot be duplicated.",
                    }
                else:
                    if tool_name in STATE_CHANGING_TOOLS:
                        executed_action_signatures.add(action_sig)

                    try:
                        mcp_result = self.mcp_client.call_tool(tool_name, tool_args)
                    except Exception as exc:
                        mcp_result = {
                            "is_error": True,
                            "error": str(exc),
                        }

                if on_tool_call is not None:
                    on_tool_call(tool_name, tool_args, mcp_result)
                elif self.config.debug_mcp_calls:
                    logger.info("MCP Tool [%s] -> %s", tool_name, "OK" if not mcp_result.get("is_error") else "ERR")

                # Return result as function response part
                response_payload = mcp_result.get("data", mcp_result)
                resp_part = types.Part.from_function_response(
                    name=tool_name,
                    response={"result": response_payload},
                )
                response_parts.append(resp_part)


            self.history.append(types.Content(role="user", parts=response_parts))

        return "Response generation reached maximum tool-call turns limit."

    def teach(
        self,
        teaching_text: str,
        source_name: Optional[str] = None,
        on_tool_call: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
    ) -> str:
        """Run structured teaching extraction and analysis turn with COMPLEX task routing context."""
        prompt = (
            "Analyze the following strategy teaching material.\n"
            "1. Identify the core components: Indicators, Market Structure / ICT concepts, Filters, Entry Triggers, Exit Rules, Risk Parameters.\n"
            "2. Identify any AMBIGUITIES, MISSING PARAMETERS, or CONFLICTS.\n"
            "3. Use appropriate MCP tools if needed to check existing concepts or strategies.\n"
            "4. Present the structured draft clearly and explain the review options available to the human operator ([A] Approve, [C] Correct, [R] Reject, [V] Verify).\n\n"
            f"Teaching Material ({source_name or 'Manual Input'}):\n"
            f"```text\n{teaching_text}\n```"
        )
        return self.send_message(
            prompt,
            on_tool_call=on_tool_call,
            context={"task_type": "teaching_extraction", "source_name": source_name},
        )
