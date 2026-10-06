"""ATSITS Gemini Integration Package."""

from atsits.gemini.client import GeminiClient
from atsits.gemini.config import (
    DEFAULT_GEMINI_MODEL,
    SUPPORTED_GEMINI_MODELS,
    GeminiConfig,
    GeminiModelInfo,
    get_supported_models,
    load_gemini_config,
    persist_gemini_model,
    validate_model_id,
)
from atsits.gemini.exceptions import (
    GeminiAPIError,
    GeminiAuthError,
    GeminiError,
    GeminiMCPToolError,
    GeminiNotConfiguredError,
    GeminiQuotaExceededError,
)
from atsits.gemini.prompts import ATSITS_SYSTEM_INSTRUCTION
from atsits.gemini.runtime import GeminiMCPRuntime

__all__ = [
    "GeminiConfig",
    "GeminiModelInfo",
    "SUPPORTED_GEMINI_MODELS",
    "DEFAULT_GEMINI_MODEL",
    "get_supported_models",
    "validate_model_id",
    "persist_gemini_model",
    "load_gemini_config",
    "GeminiClient",
    "GeminiMCPRuntime",
    "ATSITS_SYSTEM_INSTRUCTION",
    "GeminiError",
    "GeminiNotConfiguredError",
    "GeminiAuthError",
    "GeminiAPIError",
    "GeminiQuotaExceededError",
    "GeminiMCPToolError",
]
