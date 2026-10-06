"""Gemini API client wrapper using official google-genai SDK."""

import logging
from typing import Any, Optional, Tuple, Union
from atsits.gemini.config import GeminiConfig, SUPPORTED_GEMINI_MODELS, load_gemini_config
from atsits.gemini.exceptions import (
    GeminiAPIError,
    GeminiAuthError,
    GeminiError,
    GeminiNotConfiguredError,
    GeminiQuotaExceededError,
)

logger = logging.getLogger(__name__)


def _sanitize_error_message(err_msg: str, api_key: Optional[str]) -> str:
    """Strip any accidental key occurrences from error strings."""
    if not err_msg:
        return "Unknown error"
    if api_key and api_key.strip() and api_key.strip() in err_msg:
        err_msg = err_msg.replace(api_key.strip(), "[REDACTED_API_KEY]")
    return err_msg


def _get_model_display_name(model_id: str) -> str:
    """Get clean display name for a model id."""
    info = SUPPORTED_GEMINI_MODELS.get(model_id)
    return info.display_name if info else model_id


def categorize_error(exc: Exception) -> "FailureCategory":
    """Categorize an exception into a FailureCategory enum."""
    from atsits.gemini.router import FailureCategory

    if isinstance(exc, GeminiAuthError):
        return FailureCategory.AUTHENTICATION_ERROR
    if isinstance(exc, GeminiQuotaExceededError):
        return FailureCategory.QUOTA_EXHAUSTED

    err_str = str(exc).lower()
    if any(k in err_str for k in ("401", "403", "unauthorized", "api_key_invalid", "permission_denied", "api key not valid")):
        return FailureCategory.AUTHENTICATION_ERROR
    if any(k in err_str for k in ("429", "resource_exhausted", "quota")):
        return FailureCategory.QUOTA_EXHAUSTED
    if any(k in err_str for k in ("rate_limit", "rate limit", "too many requests")):
        return FailureCategory.RATE_LIMITED
    if any(k in err_str for k in ("500", "502", "503", "504", "server error", "internal error")):
        return FailureCategory.SERVER_ERROR
    if any(k in err_str for k in ("timeout", "timed out", "connection", "network", "socket")):
        return FailureCategory.NETWORK_ERROR
    if "400" in err_str or "bad request" in err_str:
        return FailureCategory.INVALID_REQUEST
    return FailureCategory.UNKNOWN


class GeminiClient:
    """Safe wrapper around the official Google GenAI SDK client."""

    def __init__(
        self,
        config: Optional[GeminiConfig] = None,
        raw_client: Optional[Any] = None,
    ):
        self.config = config or load_gemini_config()
        self._raw_client = raw_client

    @property
    def is_configured(self) -> bool:
        """Check whether the client has an API key configured."""
        return self.config.is_configured

    def _get_raw_client(self) -> Any:
        """Lazily initialize the underlying google.genai.Client."""
        if self._raw_client is not None:
            return self._raw_client

        if not self.is_configured or not self.config.api_key:
            raise GeminiNotConfiguredError(
                "GEMINI_API_KEY is not configured. "
                "Set GEMINI_API_KEY in your environment or .env file to enable Gemini features."
            )

        try:
            from google import genai

            self._raw_client = genai.Client(api_key=self.config.api_key)
            return self._raw_client
        except Exception as exc:
            sanitized = _sanitize_error_message(str(exc), self.config.api_key)
            raise GeminiAPIError(f"Failed to initialize google-genai client: {sanitized}") from exc

    def test_connection(self, model: Optional[str] = None) -> Tuple[bool, str]:
        """Test the Gemini API connection with a minimal request.

        Args:
            model: Optional model identifier to test. Defaults to self.config.model_name.

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.is_configured:
            return (
                False,
                "Gemini API key is not configured. ATSITS will run in deterministic offline mode. "
                "Set GEMINI_API_KEY in your environment or .env file to enable Gemini.",
            )

        target_model = model or self.config.model_name
        try:
            client = self._get_raw_client()
            from google.genai import types

            response = client.models.generate_content(
                model=target_model,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=5,
                    temperature=0.0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            if response:
                display_name = _get_model_display_name(target_model)
                return (
                    True,
                    f"Successfully authenticated with Gemini API (model: {display_name})",
                )
            return (False, "Received empty response from Gemini API")
        except Exception as exc:
            err_str = _sanitize_error_message(str(exc), self.config.api_key)
            # Identify auth errors vs quota vs generic network errors
            if any(k in err_str.lower() for k in ("401", "403", "unauthorized", "api_key_invalid", "permission_denied", "api key not valid")):
                return (False, f"Gemini API authentication failed: {err_str}")
            if any(k in err_str.lower() for k in ("429", "resource_exhausted", "quota")):
                display_name = _get_model_display_name(target_model)
                prefix = "" if display_name.lower().startswith("gemini") else "Gemini "
                return (
                    False,
                    f"{prefix}{display_name} quota exhausted. Switch to another available model or try again later.",
                )
            return (False, f"Gemini API connection failed: {err_str}")

    def generate_content(
        self,
        contents: Any,
        config: Optional[Any] = None,
        model: Optional[str] = None,
        allow_thinking_fallback: bool = True,
    ) -> Any:
        """Call generate_content with error translation, secret sanitization, and thinking control."""
        client = self._get_raw_client()
        target_model = model or self.config.model_name

        try:
            return client.models.generate_content(
                model=target_model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            # If thinking_config was rejected by model AND thinking fallback is permitted (non-critical tasks)
            if allow_thinking_fallback and config and hasattr(config, "thinking_config") and config.thinking_config is not None:
                err_lower = str(exc).lower()
                if any(k in err_lower for k in ("thinking", "thinking_config", "not supported", "invalid")):
                    logger.debug("Model %s rejected thinking_config, retrying without thinking (non-critical)", target_model)
                    try:
                        fallback_cfg = config.model_copy(update={"thinking_config": None})
                        return client.models.generate_content(
                            model=target_model,
                            contents=contents,
                            config=fallback_cfg,
                        )
                    except Exception:
                        pass  # Continue to standard error handling

            err_str = _sanitize_error_message(str(exc), self.config.api_key)
            if any(k in err_str.lower() for k in ("401", "403", "unauthorized", "api_key_invalid", "permission_denied", "api key not valid")):
                raise GeminiAuthError(f"Gemini authentication failed: {err_str}") from exc
            if any(k in err_str.lower() for k in ("429", "resource_exhausted", "quota")):
                display_name = _get_model_display_name(target_model)
                prefix = "" if display_name.lower().startswith("gemini") else "Gemini "
                raise GeminiQuotaExceededError(
                    f"{prefix}{display_name} quota exhausted. Switch to another available model or try again later.",
                    model_name=target_model,
                ) from exc
            raise GeminiAPIError(f"Gemini API request failed: {err_str}") from exc


