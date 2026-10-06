"""Domain exceptions for ATSITS Gemini integration."""

from typing import List, Optional


class GeminiError(Exception):
    """Base exception for all Gemini runtime errors."""


class GeminiNotConfiguredError(GeminiError):
    """Raised when Gemini API is invoked without a valid GEMINI_API_KEY."""


class GeminiAuthError(GeminiError):
    """Raised when Gemini API rejects authentication (invalid or revoked key)."""


class GeminiAPIError(GeminiError):
    """Raised when Gemini API call fails due to network or generic API error."""


class GeminiQuotaExceededError(GeminiAPIError):
    """Raised when Gemini API returns 429 / RESOURCE_EXHAUSTED."""

    def __init__(self, message: str, model_name: str = ""):
        super().__init__(message)
        self.model_name = model_name


class GeminiMCPToolError(GeminiError):
    """Raised when an MCP tool execution fails during a Gemini tool call loop."""


class RouterError(GeminiError):
    """Base exception for model routing errors."""


class AllModelsUnavailableError(RouterError):
    """Raised when all candidate models for a task are exhausted or in cooldown."""

    def __init__(self, message: str, exhausted_models: Optional[list] = None):
        super().__init__(message)
        self.exhausted_models = exhausted_models or []


class CriticalTaskDowngradePreventedError(RouterError):
    """Raised when a CRITICAL task cannot find a suitable strong model and downgrade is prohibited."""

