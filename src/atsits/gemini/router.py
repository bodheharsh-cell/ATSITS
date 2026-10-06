"""Task-Aware Automatic Model Router and Quota Resilience Engine (Phase 8.8).

Core Principles:
1. Task-Driven Capability: Classifies tasks into SIMPLE, STANDARD, COMPLEX, CRITICAL.
2. Quota & Health Awareness: Tracks consecutive failures, 429 quota exhaustion, and cooldown states.
3. Least Powerful Suitable Model: Optimizes for quota efficiency by selecting the most efficient
   model that fulfills minimum capability, reserving high-capacity models for critical tasks.
4. Strict Downgrade Protection: Prohibits silent downgrade of CRITICAL tasks below acceptable capability.
5. Action Non-Duplication: Fallback preserves state-changing MCP tool outputs without re-executing actions.
6. Local Determinism: Router is pure Python with zero LLM-in-the-loop classification and zero impact on trading code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from atsits.gemini.config import SUPPORTED_GEMINI_MODELS
from atsits.gemini.exceptions import (
    AllModelsUnavailableError,
    CriticalTaskDowngradePreventedError,
    GeminiAuthError,
    RouterError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Task Classes and Capability Tiers
# ---------------------------------------------------------------------
class TaskClass(str, Enum):
    """Categorization of operator or agent tasks by cognitive complexity."""

    SIMPLE = "SIMPLE"          # Status queries, simple formatting, short extraction, pings
    STANDARD = "STANDARD"      # Normal coding, document analysis, moderate reasoning, standard MCP
    COMPLEX = "COMPLEX"        # Multi-document extraction, conflict resolution, backtest analysis
    CRITICAL = "CRITICAL"      # Strategy verification, safety boundary audit, rule invariant review


class CapabilityTier(str, Enum):
    """Minimum capability tiers for Gemini models."""

    LIGHTWEIGHT = "LIGHTWEIGHT"  # High-volume, fast reasoning (e.g. 3.1-flash-lite, 2.5-flash-lite)
    STANDARD = "STANDARD"        # Balanced speed & reasoning (e.g. 3.6-flash)
    STRONG = "STRONG"            # Advanced analytical reasoning (e.g. 3.7-flash)
    CRITICAL = "CRITICAL"        # Maximum cognitive depth & safety verification (e.g. 3.8-flash)


class ModelHealthState(str, Enum):
    """Real-time availability status of an individual model."""

    AVAILABLE = "AVAILABLE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class FailureCategory(str, Enum):
    """Classified failure modes for Gemini API interactions."""

    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"          # HTTP 429 / RESOURCE_EXHAUSTED (daily or global quota)
    RATE_LIMITED = "RATE_LIMITED"                # Short burst limit (RPM / TPM)
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"# 401/403/invalid key (DO NOT fallback across models)
    NETWORK_ERROR = "NETWORK_ERROR"              # Connection reset, socket timeout
    SERVER_ERROR = "SERVER_ERROR"                # 500, 503 internal Google API error
    INVALID_REQUEST = "INVALID_REQUEST"          # 400 Bad Request
    UNKNOWN = "UNKNOWN"


class RoutingMode(str, Enum):
    """Operational mode of the Gemini model selection system."""

    AUTO = "AUTO"      # Automatic task-aware routing with health & fallback
    MANUAL = "MANUAL"  # Explicit operator-selected model


# ---------------------------------------------------------------------
# Model Capability Specifications
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class ModelCapability:
    """Metadata defining model capability, thinking support, and tier."""

    model_id: str
    display_name: str
    capability_tier: CapabilityTier
    supported_tasks: List[TaskClass]
    primary_for: Optional[TaskClass]
    supports_thinking: bool
    fallback_priority: int
    relative_cost_weight: str  # "lowest", "low", "medium", "high", "highest"
    historical_quota_profile: Dict[str, Any] = field(default_factory=dict)


MODEL_CAPABILITIES: Dict[str, ModelCapability] = {
    "gemini-3.1-flash-lite": ModelCapability(
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        capability_tier=CapabilityTier.LIGHTWEIGHT,
        supported_tasks=[TaskClass.SIMPLE, TaskClass.STANDARD],
        primary_for=TaskClass.SIMPLE,
        supports_thinking=True,
        fallback_priority=1,
        relative_cost_weight="lowest",
        historical_quota_profile={
            "observed_rpm": 15,
            "observed_rpd": 500,
            "nature": "HISTORICAL_OBSERVATION_NOT_GUARANTEED",
        },
    ),
    "gemini-2.5-flash-lite": ModelCapability(
        model_id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        capability_tier=CapabilityTier.LIGHTWEIGHT,
        supported_tasks=[TaskClass.SIMPLE],
        primary_for=None,  # Secondary lightweight backup
        supports_thinking=False,
        fallback_priority=2,
        relative_cost_weight="low",
        historical_quota_profile={
            "observed_rpm": 10,
            "observed_rpd": 20,
            "nature": "HISTORICAL_OBSERVATION_NOT_GUARANTEED",
        },
    ),
    "gemini-3.6-flash": ModelCapability(
        model_id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        capability_tier=CapabilityTier.STANDARD,
        supported_tasks=[TaskClass.SIMPLE, TaskClass.STANDARD, TaskClass.COMPLEX],
        primary_for=TaskClass.STANDARD,
        supports_thinking=True,
        fallback_priority=3,
        relative_cost_weight="medium",
        historical_quota_profile={
            "observed_rpm": 5,
            "observed_rpd": 20,
            "nature": "HISTORICAL_OBSERVATION_NOT_GUARANTEED",
        },
    ),
    "gemini-3.7-flash": ModelCapability(
        model_id="gemini-3.7-flash",
        display_name="Gemini 3.7 Flash",
        capability_tier=CapabilityTier.STRONG,
        supported_tasks=[TaskClass.SIMPLE, TaskClass.STANDARD, TaskClass.COMPLEX, TaskClass.CRITICAL],
        primary_for=TaskClass.COMPLEX,
        supports_thinking=True,
        fallback_priority=4,
        relative_cost_weight="high",
        historical_quota_profile={
            "observed_rpm": 5,
            "observed_rpd": 20,
            "nature": "HISTORICAL_OBSERVATION_NOT_GUARANTEED",
        },
    ),
    "gemini-3.8-flash": ModelCapability(
        model_id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        capability_tier=CapabilityTier.CRITICAL,
        supported_tasks=[TaskClass.SIMPLE, TaskClass.STANDARD, TaskClass.COMPLEX, TaskClass.CRITICAL],
        primary_for=TaskClass.CRITICAL,
        supports_thinking=True,
        fallback_priority=5,
        relative_cost_weight="highest",
        historical_quota_profile={
            "observed_rpm": 5,
            "observed_rpd": 20,
            "nature": "HISTORICAL_OBSERVATION_NOT_GUARANTEED",
        },
    ),
}


# ---------------------------------------------------------------------
# Task Classification Result and Routing Metadata
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class TaskClassification:
    """Result of deterministic task analysis."""

    task_class: TaskClass
    minimum_capability: CapabilityTier
    confidence: float
    reason: str
    suggested_thinking: Optional[str] = None


@dataclass
class RoutingMetadata:
    """Diagnostic and observability metadata for a routed request."""

    router_version: str = "1.0"
    mode: str = "AUTO"  # AUTO or MANUAL
    task_class: str = "STANDARD"
    minimum_capability: str = "STANDARD"
    selected_model: str = "gemini-3.6-flash"
    selection_reason: str = "Standard document and reasoning task"
    fallback_attempt: int = 0
    previous_model: Optional[str] = None
    failure_reason: Optional[str] = None
    model_health: str = "AVAILABLE"
    thinking_level: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return safe, non-sensitive dictionary representation."""
        data = asdict(self)
        return data


# ---------------------------------------------------------------------
# Deterministic Task Classifier
# ---------------------------------------------------------------------
class TaskClassifier:
    """Deterministic classifier evaluating prompts without calling an LLM."""

    CRITICAL_PATTERNS = [
        re.compile(r"\b(verify|verification|approve|promot|audit)\b", re.IGNORECASE),
        re.compile(r"\b(safety boundary|materially alter|security review)\b", re.IGNORECASE),
        re.compile(r"\b(invariants?|reconcile conflicts?|spec consistency)\b", re.IGNORECASE),
        re.compile(r"\b(verified strategy|lock baseline|governance)\b", re.IGNORECASE),
    ]

    COMPLEX_PATTERNS = [
        re.compile(r"\b(multi-document|conflicting rules|conflicts?)\b", re.IGNORECASE),
        re.compile(r"\b(backtest analysis|drawdown analysis|distribution)\b", re.IGNORECASE),
        re.compile(r"\b(hypothesis|experiment runner|reconstruction)\b", re.IGNORECASE),
        re.compile(r"\b(architecture change|refactor|deep reasoning)\b", re.IGNORECASE),
        re.compile(r"\b(multi-step|step-by-step workflow|extract strategy)\b", re.IGNORECASE),
    ]

    SIMPLE_PATTERNS = [
        re.compile(r"^(ping|pong|hi|hello|hey|status|version|help)$", re.IGNORECASE),
        re.compile(r"^(what is the (time|price|symbol|strategy|version))\b", re.IGNORECASE),
        re.compile(r"^(summarize this in \d+ (words|bullets)|format as json)\b", re.IGNORECASE),
        re.compile(r"^(list (models|tools|strategies|trades))\b", re.IGNORECASE),
    ]

    def classify(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> TaskClassification:
        """Classify a user or workflow prompt deterministically."""
        ctx = context or {}
        text = (prompt or "").strip()
        length = len(text)

        # Context overrides (e.g. from explicit human review or verification API)
        if ctx.get("is_critical") or ctx.get("task_type") == "verification":
            return TaskClassification(
                task_class=TaskClass.CRITICAL,
                minimum_capability=CapabilityTier.STRONG,
                confidence=1.0,
                reason="Explicit verification or security-critical context",
                suggested_thinking="HIGH",
            )

        if ctx.get("task_type") in ("teaching_extraction", "conflict_resolution", "experiment_analysis"):
            return TaskClassification(
                task_class=TaskClass.COMPLEX,
                minimum_capability=CapabilityTier.STRONG,
                confidence=0.95,
                reason=f"Structured workflow context: {ctx.get('task_type')}",
                suggested_thinking="MEDIUM",
            )

        # 1. CRITICAL Evaluation
        for pat in self.CRITICAL_PATTERNS:
            if pat.search(text):
                return TaskClassification(
                    task_class=TaskClass.CRITICAL,
                    minimum_capability=CapabilityTier.STRONG,
                    confidence=0.9,
                    reason=f"Matched critical safety/verification pattern: {pat.pattern}",
                    suggested_thinking="HIGH",
                )

        # 2. COMPLEX Evaluation (High token length or complex pattern)
        if length > 1200:
            return TaskClassification(
                task_class=TaskClass.COMPLEX,
                minimum_capability=CapabilityTier.STRONG,
                confidence=0.85,
                reason=f"Long/multi-section prompt ({length} chars)",
                suggested_thinking="MEDIUM",
            )

        for pat in self.COMPLEX_PATTERNS:
            if pat.search(text):
                return TaskClassification(
                    task_class=TaskClass.COMPLEX,
                    minimum_capability=CapabilityTier.STRONG,
                    confidence=0.8,
                    reason=f"Matched complex analytical pattern: {pat.pattern}",
                    suggested_thinking="MEDIUM",
                )

        # 3. SIMPLE Evaluation (Strict lookup/status patterns and short non-reasoning queries)
        for pat in self.SIMPLE_PATTERNS:
            if pat.search(text):
                return TaskClassification(
                    task_class=TaskClass.SIMPLE,
                    minimum_capability=CapabilityTier.LIGHTWEIGHT,
                    confidence=0.9,
                    reason=f"Matched simple lookup/status pattern: {pat.pattern}",
                    suggested_thinking="LOW",
                )

        if length < 40:
            # Short generic non-reasoning query
            reasoning_words = ("why", "how", "explain", "analyze", "strategy", "trade", "code", "bug", "indicator", "diff", "calculat")
            if not any(k in text.lower() for k in reasoning_words):
                return TaskClassification(
                    task_class=TaskClass.SIMPLE,
                    minimum_capability=CapabilityTier.LIGHTWEIGHT,
                    confidence=0.75,
                    reason="Short greeting or lookup without analysis triggers",
                    suggested_thinking="LOW",
                )


        # 4. STANDARD Default
        return TaskClassification(
            task_class=TaskClass.STANDARD,
            minimum_capability=CapabilityTier.STANDARD,
            confidence=0.8,
            reason="Standard document reasoning, debugging, or MCP task",
            suggested_thinking="MEDIUM",
        )


# ---------------------------------------------------------------------
# Quota & Model Health Tracker
# ---------------------------------------------------------------------
class ModelHealthRecord:
    """Tracks state and cooldown for a single Gemini model."""

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.health_state = ModelHealthState.AVAILABLE
        self.last_success: Optional[datetime] = None
        self.last_failure: Optional[datetime] = None
        self.last_failure_category: Optional[FailureCategory] = None
        self.last_failure_error: str = ""
        self.consecutive_failures: int = 0
        self.cooldown_until: Optional[datetime] = None
        self.last_selected_at: Optional[datetime] = None
        self.total_requests: int = 0
        self.total_successes: int = 0
        self.total_quota_errors: int = 0


class ModelHealthTracker:
    """Tracks real-time health, 429 exhaustion, and bounded cooldowns."""

    def __init__(
        self,
        base_cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 900.0,  # 15 minutes
    ):
        self.base_cooldown_seconds = base_cooldown_seconds
        self.max_cooldown_seconds = max_cooldown_seconds
        self._records: Dict[str, ModelHealthRecord] = {
            m_id: ModelHealthRecord(m_id) for m_id in SUPPORTED_GEMINI_MODELS
        }

    def record_success(self, model_id: str) -> None:
        """Record a successful response; clears failure count and cooldown."""
        rec = self._get_or_create(model_id)
        now = datetime.now(timezone.utc)
        rec.last_success = now
        rec.consecutive_failures = 0
        rec.cooldown_until = None
        rec.health_state = ModelHealthState.AVAILABLE
        rec.total_requests += 1
        rec.total_successes += 1
        logger.debug("ModelHealth [%s] marked AVAILABLE (success).", model_id)

    def record_failure(
        self,
        model_id: str,
        category: FailureCategory,
        error_msg: str = "",
    ) -> float:
        """Record a model failure, update state, and set bounded cooldown.

        Returns:
            Calculated cooldown in seconds.
        """
        rec = self._get_or_create(model_id)
        now = datetime.now(timezone.utc)
        rec.last_failure = now
        rec.last_failure_category = category
        rec.last_failure_error = error_msg
        rec.consecutive_failures += 1
        rec.total_requests += 1

        if category == FailureCategory.QUOTA_EXHAUSTED:
            rec.total_quota_errors += 1
            # Bounded exponential backoff: base * 2^(fails - 1), capped at max
            factor = 2 ** max(0, rec.consecutive_failures - 1)
            cooldown_sec = min(self.base_cooldown_seconds * factor, self.max_cooldown_seconds)
            rec.cooldown_until = now + timedelta(seconds=cooldown_sec)
            rec.health_state = ModelHealthState.TEMPORARILY_UNAVAILABLE
            logger.warning(
                "ModelHealth [%s] QUOTA_EXHAUSTED (fails=%d). Cooldown for %.1fs until %s.",
                model_id,
                rec.consecutive_failures,
                cooldown_sec,
                rec.cooldown_until.isoformat(),
            )
            return cooldown_sec

        elif category == FailureCategory.RATE_LIMITED:
            # Short burst rate limit (30s)
            cooldown_sec = 30.0
            rec.cooldown_until = now + timedelta(seconds=cooldown_sec)
            rec.health_state = ModelHealthState.TEMPORARILY_UNAVAILABLE
            return cooldown_sec

        elif category in (FailureCategory.NETWORK_ERROR, FailureCategory.SERVER_ERROR):
            # Short retry cooldown (15s)
            cooldown_sec = 15.0
            rec.cooldown_until = now + timedelta(seconds=cooldown_sec)
            rec.health_state = ModelHealthState.TEMPORARILY_UNAVAILABLE
            return cooldown_sec

        elif category == FailureCategory.AUTHENTICATION_ERROR:
            # Authentication failure is configuration-level, not transient per-model
            rec.health_state = ModelHealthState.TEMPORARILY_UNAVAILABLE
            return 0.0

        return 0.0

    def is_available(self, model_id: str) -> bool:
        """Check if model is currently available (honoring cooldown expiry)."""
        rec = self._records.get(model_id)
        if not rec:
            return True

        if rec.health_state == ModelHealthState.AVAILABLE:
            return True

        # Check if cooldown has expired
        if rec.cooldown_until is not None:
            now = datetime.now(timezone.utc)
            if now >= rec.cooldown_until:
                # Cooldown expired -> automatically restore to AVAILABLE
                rec.health_state = ModelHealthState.AVAILABLE
                rec.cooldown_until = None
                logger.info("ModelHealth [%s] cooldown expired. Restored to AVAILABLE.", model_id)
                return True
            return False

        return rec.health_state != ModelHealthState.TEMPORARILY_UNAVAILABLE

    def get_model_status(self, model_id: str) -> Dict[str, Any]:
        """Return diagnostic status snapshot for UI and API consumers."""
        rec = self._records.get(model_id)
        if not rec:
            return {"model_id": model_id, "state": "UNKNOWN"}

        now = datetime.now(timezone.utc)
        cooldown_remaining = 0.0
        if rec.cooldown_until and rec.cooldown_until > now:
            cooldown_remaining = round((rec.cooldown_until - now).total_seconds(), 1)

        return {
            "model_id": model_id,
            "state": rec.health_state.value,
            "is_available": self.is_available(model_id),
            "consecutive_failures": rec.consecutive_failures,
            "last_failure_category": rec.last_failure_category.value if rec.last_failure_category else None,
            "cooldown_remaining_sec": cooldown_remaining,
            "total_requests": rec.total_requests,
            "total_successes": rec.total_successes,
            "total_quota_errors": rec.total_quota_errors,
        }

    def get_health_summary(self) -> Dict[str, Dict[str, Any]]:
        """Return status for all whitelisted models."""
        return {m_id: self.get_model_status(m_id) for m_id in SUPPORTED_GEMINI_MODELS}

    def _get_or_create(self, model_id: str) -> ModelHealthRecord:
        if model_id not in self._records:
            self._records[model_id] = ModelHealthRecord(model_id)
        return self._records[model_id]

    def reset(self) -> None:
        """Clear all health records."""
        for rec in self._records.values():
            rec.health_state = ModelHealthState.AVAILABLE
            rec.consecutive_failures = 0
            rec.cooldown_until = None


# ---------------------------------------------------------------------
# Central Model Router
# ---------------------------------------------------------------------
class ModelRouter:
    """Task-aware router with capability matching, health tracking, and quota fallback."""

    # Candidate chains ordered by efficiency and suitability
    CANDIDATE_CHAINS: Dict[TaskClass, List[str]] = {
        TaskClass.SIMPLE: [
            "gemini-3.1-flash-lite",  # Preferred high-volume lightweight
            "gemini-2.5-flash-lite",  # Secondary lightweight backup
            "gemini-3.6-flash",       # Standard step-up
        ],
        TaskClass.STANDARD: [
            "gemini-3.6-flash",       # Preferred standard reasoning
            "gemini-3.7-flash",       # Step-up strong model
            "gemini-3.1-flash-lite",  # Fallback efficient model
        ],
        TaskClass.COMPLEX: [
            "gemini-3.7-flash",       # Preferred complex reasoning
            "gemini-3.8-flash",       # Flagship step-up
            "gemini-3.6-flash",       # Fallback standard model
        ],
        TaskClass.CRITICAL: [
            "gemini-3.8-flash",       # Preferred maximum-depth model
            "gemini-3.7-flash",       # Strong secondary model
        ],
    }

    def __init__(
        self,
        classifier: Optional[TaskClassifier] = None,
        health_tracker: Optional[ModelHealthTracker] = None,
        default_mode: RoutingMode = RoutingMode.AUTO,
    ):
        self.classifier = classifier or TaskClassifier()
        self.health_tracker = health_tracker or ModelHealthTracker()
        self.mode = default_mode

    def classify_task(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> TaskClassification:
        """Classify a prompt deterministically."""
        return self.classifier.classify(prompt, context=context)

    def resolve_candidate_chain(self, task_class: TaskClass) -> List[str]:
        """Return the prioritized candidate models for a task class."""
        return list(self.CANDIDATE_CHAINS.get(task_class, self.CANDIDATE_CHAINS[TaskClass.STANDARD]))

    def select_initial_model(
        self,
        task_classification: TaskClassification,
        manual_override_model: Optional[str] = None,
    ) -> Tuple[str, RoutingMetadata]:
        """Select the best initial model based on mode, task class, and health state."""
        # 1. Manual Mode
        if self.mode == RoutingMode.MANUAL and manual_override_model:
            model_id = manual_override_model
            is_avail = self.health_tracker.is_available(model_id)
            meta = RoutingMetadata(
                router_version="1.0",
                mode="MANUAL",
                task_class=task_classification.task_class.value,
                minimum_capability=task_classification.minimum_capability.value,
                selected_model=model_id,
                selection_reason=f"Manual operator selection override ({model_id})",
                fallback_attempt=0,
                model_health="AVAILABLE" if is_avail else "TEMPORARILY_UNAVAILABLE",
                thinking_level=task_classification.suggested_thinking,
            )
            return model_id, meta

        # 2. AUTO Mode
        chain = self.resolve_candidate_chain(task_classification.task_class)

        # Find first available model in candidate chain
        selected_model: Optional[str] = None
        for candidate in chain:
            if self.health_tracker.is_available(candidate):
                selected_model = candidate
                break

        # If all candidates in chain are temporarily unavailable:
        if not selected_model:
            # Check critical downgrade boundary
            if task_classification.task_class == TaskClass.CRITICAL:
                raise CriticalTaskDowngradePreventedError(
                    "Critical task requires a stronger available model (gemini-3.8-flash or gemini-3.7-flash); "
                    "automatic downgrade prevented to preserve trading safety."
                )

            # Try any whitelisted model that is available
            for candidate in MODEL_CAPABILITIES:
                if self.health_tracker.is_available(candidate):
                    selected_model = candidate
                    break

        if not selected_model:
            status_map = self.health_tracker.get_health_summary()
            exhausted = [
                f"{m}: in cooldown ({status_map[m]['cooldown_remaining_sec']}s left)"
                for m in chain
            ]
            raise AllModelsUnavailableError(
                f"All candidate models for task [{task_classification.task_class.value}] are exhausted: "
                + ", ".join(exhausted),
                exhausted_models=chain,
            )

        meta = RoutingMetadata(
            router_version="1.0",
            mode="AUTO",
            task_class=task_classification.task_class.value,
            minimum_capability=task_classification.minimum_capability.value,
            selected_model=selected_model,
            selection_reason=task_classification.reason,
            fallback_attempt=0,
            model_health="AVAILABLE",
            thinking_level=task_classification.suggested_thinking,
        )
        return selected_model, meta

    def get_fallback_model(
        self,
        current_model: str,
        task_classification: TaskClassification,
        failure_category: FailureCategory,
        attempt: int,
    ) -> Tuple[str, RoutingMetadata]:
        """Select next suitable model upon failure, respecting capability boundaries."""
        # 1. Authentication failure MUST NOT fall back across models
        if failure_category == FailureCategory.AUTHENTICATION_ERROR:
            raise GeminiAuthError(
                "Gemini authentication failed. Do not retry other models; verify GEMINI_API_KEY configuration."
            )

        # 2. In MANUAL mode, do not automatically switch models
        if self.mode == RoutingMode.MANUAL:
            raise AllModelsUnavailableError(
                f"Manual model [{current_model}] failed with {failure_category.value}. Automatic fallback disabled in MANUAL mode."
            )

        # 3. Resolve next candidate in chain
        chain = self.resolve_candidate_chain(task_classification.task_class)
        try:
            curr_idx = chain.index(current_model)
            remaining_candidates = chain[curr_idx + 1 :]
        except ValueError:
            remaining_candidates = [m for m in chain if m != current_model]

        fallback_model: Optional[str] = None
        for candidate in remaining_candidates:
            if self.health_tracker.is_available(candidate):
                fallback_model = candidate
                break

        # Critical task protection: do not downgrade below chain
        if not fallback_model:
            if task_classification.task_class == TaskClass.CRITICAL:
                raise CriticalTaskDowngradePreventedError(
                    "Critical task requires a stronger available model (gemini-3.8-flash or gemini-3.7-flash); "
                    "automatic downgrade prevented."
                )

            # If standard/simple task, check if any other model is available
            for candidate in MODEL_CAPABILITIES:
                if candidate != current_model and self.health_tracker.is_available(candidate):
                    fallback_model = candidate
                    break

        if not fallback_model:
            raise AllModelsUnavailableError(
                f"All candidate models exhausted after fallback from [{current_model}] ({failure_category.value}).",
                exhausted_models=chain,
            )

        meta = RoutingMetadata(
            router_version="1.0",
            mode="AUTO",
            task_class=task_classification.task_class.value,
            minimum_capability=task_classification.minimum_capability.value,
            selected_model=fallback_model,
            selection_reason=f"Fallback from {current_model} due to {failure_category.value}",
            fallback_attempt=attempt + 1,
            previous_model=current_model,
            failure_reason=failure_category.value,
            model_health="AVAILABLE",
            thinking_level=task_classification.suggested_thinking,
        )
        return fallback_model, meta

    def build_thinking_config(
        self,
        model_id: str,
        task_classification: TaskClassification,
    ) -> Optional[Any]:
        """Construct official google-genai ThinkingConfig if supported by model."""
        cap = MODEL_CAPABILITIES.get(model_id)
        if not cap or not cap.supports_thinking:
            return None

        try:
            from google.genai import types

            if not hasattr(types, "ThinkingConfig"):
                return None

            # Map task classification to ThinkingLevel
            level_str = task_classification.suggested_thinking or "MEDIUM"
            if hasattr(types, "ThinkingLevel"):
                thinking_level = getattr(types.ThinkingLevel, level_str, types.ThinkingLevel.MEDIUM)
                return types.ThinkingConfig(thinking_level=thinking_level)

            # Fallback to thinking_budget if level not present
            budget_map = {
                TaskClass.SIMPLE: 512,
                TaskClass.STANDARD: 1024,
                TaskClass.COMPLEX: 2048,
                TaskClass.CRITICAL: 4096,
            }
            budget = budget_map.get(task_classification.task_class, 1024)
            return types.ThinkingConfig(thinking_budget=budget)
        except Exception as exc:
            logger.debug("ThinkingConfig creation skipped for %s: %s", model_id, exc)
            return None
