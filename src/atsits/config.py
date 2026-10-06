"""Configuration loader and schema for ATSITS."""

import json
from enum import Enum
from pathlib import Path
from typing import Optional, Union
from pydantic import BaseModel, ConfigDict, Field
from atsits.models.risk import RiskConfig


class ExecutionMode(str, Enum):
    """Allowed system execution modes."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class AppEnvironment(str, Enum):
    """Application runtime environments."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LoggingConfig(BaseModel):
    """Logging settings."""

    model_config = ConfigDict(frozen=True)

    log_level: str = Field(default="INFO", description="Standard logging level (e.g. DEBUG, INFO, WARNING)")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Logging format template string",
    )


class AppConfig(BaseModel):
    """Top-level application configuration."""

    model_config = ConfigDict(frozen=True)

    environment: AppEnvironment = Field(
        default=AppEnvironment.DEV,
        description="Application environment (dev, test, prod)",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.BACKTEST,
        description="System execution mode",
    )
    risk: RiskConfig = Field(..., description="Default risk management settings")
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging configuration",
    )


def load_config(config_path: Optional[Union[str, Path]] = None) -> AppConfig:
    """Load application configuration from a JSON file.

    Args:
        config_path: Path to the JSON configuration file. If None, resolves to
                     'config/default_config.json' relative to project root.

    Returns:
        Validated AppConfig instance.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        ValueError: If configuration JSON is invalid or fails schema validation.
    """
    if config_path is None:
        # Default path relative to workspace root
        resolved_path = Path(__file__).resolve().parent.parent.parent / "config" / "default_config.json"
    else:
        resolved_path = Path(config_path).resolve()

    if not resolved_path.is_file():
        raise FileNotFoundError(f"Configuration file not found at: {resolved_path}")

    with open(resolved_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"Malformed JSON in configuration file '{resolved_path}': {err}") from err

    return AppConfig.model_validate(data)
