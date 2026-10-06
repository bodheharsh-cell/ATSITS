"""Configuration loader, schema, and model registry for Gemini API runtime."""

import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------
# Supported Gemini Model Registry (Text & Function Calling Whitelist)
# ---------------------------------------------------------------------
class GeminiModelInfo(BaseModel):
    """Metadata for a supported Gemini model."""

    model_config = ConfigDict(frozen=True)

    model_id: str = Field(..., description="API model identifier")
    display_name: str = Field(..., description="Human-readable model name")
    description: str = Field(..., description="Brief model capability description")
    is_default: bool = Field(default=False, description="Whether this is the default model")


SUPPORTED_GEMINI_MODELS: Dict[str, GeminiModelInfo] = {
    "gemini-2.5-flash-lite": GeminiModelInfo(
        model_id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        description="High-speed, lightweight model for fast reasoning & MCP tools",
        is_default=True,
    ),
    "gemini-3.1-flash-lite": GeminiModelInfo(
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        description="Next-generation efficient flash model with function calling",
        is_default=False,
    ),
    "gemini-3.6-flash": GeminiModelInfo(
        model_id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        description="Balanced speed and reasoning for multi-turn tool interaction",
        is_default=False,
    ),
    "gemini-3.7-flash": GeminiModelInfo(
        model_id="gemini-3.7-flash",
        display_name="Gemini 3.7 Flash",
        description="Advanced reasoning model with deep analysis capabilities",
        is_default=False,
    ),
    "gemini-3.8-flash": GeminiModelInfo(
        model_id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        description="Latest high-capacity flagship flash model for quantitative research",
        is_default=False,
    ),
}

DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash-lite"


def get_supported_models() -> List[Dict[str, Any]]:
    """Return list of supported models for GUI and API consumers."""
    return [
        {
            "model_id": info.model_id,
            "display_name": info.display_name,
            "description": info.description,
            "is_default": info.is_default,
        }
        for info in SUPPORTED_GEMINI_MODELS.values()
    ]


def validate_model_id(model_id: str) -> str:
    """Validate requested model against supported whitelist.

    Raises:
        ValueError: If model_id is not in whitelist.
    """
    clean_id = (model_id or "").strip()
    # Normalize models/ prefix if passed
    if clean_id.startswith("models/"):
        clean_id = clean_id[len("models/") :]

    if clean_id not in SUPPORTED_GEMINI_MODELS:
        supported = ", ".join(SUPPORTED_GEMINI_MODELS.keys())
        raise ValueError(
            f"Unsupported Gemini model '{model_id}'. Supported models are: {supported}."
        )
    return clean_id


def _mask_secret(secret: Optional[str]) -> str:
    """Safely mask secret strings to prevent accidental exposure in logs/errors."""
    if not secret:
        return "<not configured>"
    stripped = secret.strip()
    if len(stripped) <= 8:
        return "****"
    return f"{stripped[:4]}...{stripped[-4:]}"


def _find_and_parse_dotenv(start_dir: Optional[Path] = None) -> tuple[dict, Optional[Path]]:
    """Parse key-value pairs and return path of .env file if present."""
    search_path = start_dir or Path.cwd()
    env_file: Optional[Path] = None

    # Search current and parent directories
    curr = search_path.resolve()
    for _ in range(5):
        candidate = curr / ".env"
        if candidate.is_file():
            env_file = candidate
            break
        if curr.parent == curr:
            break
        curr = curr.parent

    if not env_file or not env_file.is_file():
        return {}, None

    env_vars = {}
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k:
                    env_vars[k] = v
    except Exception:
        return {}, env_file

    return env_vars, env_file


def persist_gemini_model(model_id: str, env_file: Optional[Path] = None) -> None:
    """Persist selected Gemini model to .env file without exposing or altering API keys."""
    validated = validate_model_id(model_id)
    target_env = env_file
    if not target_env:
        _, found_env = _find_and_parse_dotenv()
        target_env = found_env or (Path.cwd() / ".env")

    lines = []
    model_set = False
    if target_env.is_file():
        with open(target_env, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GEMINI_MODEL="):
                    lines.append(f"GEMINI_MODEL={validated}\n")
                    model_set = True
                else:
                    lines.append(line)

    if not model_set:
        lines.append(f"GEMINI_MODEL={validated}\n")

    with open(target_env, "w", encoding="utf-8") as f:
        f.writelines(lines)


def persist_gemini_selection_mode(mode: str, env_file: Optional[Path] = None) -> None:
    """Persist selection mode (AUTO or MANUAL) to .env file."""
    clean_mode = "AUTO" if (mode or "").strip().upper() == "AUTO" else "MANUAL"
    target_env = env_file
    if not target_env:
        _, found_env = _find_and_parse_dotenv()
        target_env = found_env or (Path.cwd() / ".env")

    lines = []
    mode_set = False
    if target_env.is_file():
        with open(target_env, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GEMINI_SELECTION_MODE="):
                    lines.append(f"GEMINI_SELECTION_MODE={clean_mode}\n")
                    mode_set = True
                else:
                    lines.append(line)

    if not mode_set:
        lines.append(f"GEMINI_SELECTION_MODE={clean_mode}\n")

    with open(target_env, "w", encoding="utf-8") as f:
        f.writelines(lines)


def validate_selection_target(target: str) -> tuple[str, str]:
    """Validate a target which may be 'auto' or a specific model ID.

    Returns:
        Tuple of (mode: "AUTO" | "MANUAL", validated_model_id: str)
    """
    clean = (target or "").strip().lower()
    if clean in ("auto", "router", "default"):
        return ("AUTO", DEFAULT_GEMINI_MODEL)
    valid_id = validate_model_id(target)
    return ("MANUAL", valid_id)


class GeminiConfig(BaseModel):
    """Configuration for Google Gemini API."""

    model_config = ConfigDict(frozen=True)

    api_key: Optional[str] = Field(
        default=None,
        description="Gemini API Key from Google AI Studio. Must be kept private.",
    )
    model_name: str = Field(
        default=DEFAULT_GEMINI_MODEL,
        description="Gemini model identifier (e.g. gemini-2.5-flash-lite, gemini-3.7-flash).",
    )
    selection_mode: str = Field(
        default="AUTO",
        description="Model selection mode: AUTO (task-aware automatic router) or MANUAL.",
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for Gemini reasoning.",
    )
    max_turns: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum sequential tool-call turns allowed per user turn.",
    )
    debug_mcp_calls: bool = Field(
        default=True,
        description="Whether to print MCP tool calls in chat/debug mode.",
    )

    @property
    def is_configured(self) -> bool:
        """True if a non-empty API key is present."""
        return bool(self.api_key and self.api_key.strip())

    @property
    def is_auto(self) -> bool:
        """True if selection_mode is AUTO."""
        return self.selection_mode.upper() == "AUTO"

    @property
    def masked_key(self) -> str:
        """Return masked representation of API key."""
        return _mask_secret(self.api_key)

    @property
    def display_name(self) -> str:
        """Return human-readable model name."""
        info = SUPPORTED_GEMINI_MODELS.get(self.model_name)
        return info.display_name if info else self.model_name

    def with_model(self, new_model_id: str) -> "GeminiConfig":
        """Return a new GeminiConfig instance with validated new model ID."""
        valid_id = validate_model_id(new_model_id)
        return GeminiConfig(
            api_key=self.api_key,
            model_name=valid_id,
            selection_mode=self.selection_mode,
            temperature=self.temperature,
            max_turns=self.max_turns,
            debug_mcp_calls=self.debug_mcp_calls,
        )

    def with_selection_mode(self, mode: str) -> "GeminiConfig":
        """Return a new GeminiConfig instance with updated selection mode."""
        clean_mode = "AUTO" if (mode or "").strip().upper() == "AUTO" else "MANUAL"
        return GeminiConfig(
            api_key=self.api_key,
            model_name=self.model_name,
            selection_mode=clean_mode,
            temperature=self.temperature,
            max_turns=self.max_turns,
            debug_mcp_calls=self.debug_mcp_calls,
        )

    def __repr__(self) -> str:
        return (
            f"GeminiConfig(model_name='{self.model_name}', "
            f"selection_mode='{self.selection_mode}', "
            f"api_key='{self.masked_key}', "
            f"temperature={self.temperature}, "
            f"is_configured={self.is_configured})"
        )

    def __str__(self) -> str:
        return self.__repr__()



def load_gemini_config(
    env_file: Optional[Union[str, Path]] = None,
    api_key_override: Optional[str] = None,
    model_override: Optional[str] = None,
    selection_mode_override: Optional[str] = None,
) -> GeminiConfig:
    """Load Gemini configuration from environment variables and optional .env file.

    Priority:
    1. Direct arguments (if provided)
    2. OS environment variables (os.environ)
    3. .env file variables
    4. Safe defaults
    """
    dotenv_vars = {}
    if env_file:
        p = Path(env_file).resolve()
        if p.is_file():
            dotenv_vars, _ = _find_and_parse_dotenv(p.parent)
    else:
        dotenv_vars, _ = _find_and_parse_dotenv()

    # Resolve API Key
    api_key = (
        api_key_override
        or os.environ.get("GEMINI_API_KEY")
        or dotenv_vars.get("GEMINI_API_KEY")
    )

    # Resolve Selection Mode (Defaults to AUTO)
    raw_mode = (
        selection_mode_override
        or os.environ.get("GEMINI_SELECTION_MODE")
        or dotenv_vars.get("GEMINI_SELECTION_MODE")
        or "AUTO"
    )
    clean_mode = "AUTO" if (raw_mode or "").strip().upper() == "AUTO" else "MANUAL"

    # Resolve Model Name
    raw_model = (
        model_override
        or os.environ.get("GEMINI_MODEL")
        or dotenv_vars.get("GEMINI_MODEL")
        or DEFAULT_GEMINI_MODEL
    )

    # Validate against whitelist; fallback to DEFAULT_GEMINI_MODEL if invalid in legacy config
    try:
        model_name = validate_model_id(raw_model)
    except ValueError:
        model_name = DEFAULT_GEMINI_MODEL

    # Resolve Temperature
    temp_str = os.environ.get("GEMINI_TEMPERATURE") or dotenv_vars.get("GEMINI_TEMPERATURE")
    try:
        temperature = float(temp_str) if temp_str is not None else 0.2
    except ValueError:
        temperature = 0.2

    # Resolve Debug Flag
    debug_str = os.environ.get("GEMINI_DEBUG_MCP") or dotenv_vars.get("GEMINI_DEBUG_MCP")
    debug_mcp = debug_str.lower() in ("1", "true", "yes") if debug_str else True

    return GeminiConfig(
        api_key=api_key.strip() if api_key else None,
        model_name=model_name,
        selection_mode=clean_mode,
        temperature=temperature,
        debug_mcp_calls=debug_mcp,
    )

