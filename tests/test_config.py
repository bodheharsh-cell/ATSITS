"""Tests for configuration loading and validation."""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from atsits.config import AppConfig, AppEnvironment, ExecutionMode, load_config
from atsits.models.risk import RiskConfig


def test_load_default_config():
    """Verify that the default configuration file loads and validates cleanly."""
    config = load_config()
    assert isinstance(config, AppConfig)
    assert config.environment == AppEnvironment.DEV
    assert config.execution_mode == ExecutionMode.BACKTEST
    assert isinstance(config.risk, RiskConfig)
    assert config.risk.max_risk_per_trade_pct == 0.01
    assert config.risk.account_balance == 10000.0
    assert config.logging.log_level == "INFO"


def test_load_custom_config(tmp_path: Path):
    """Verify that a custom JSON configuration file loads correctly."""
    custom_data = {
        "environment": "test",
        "execution_mode": "PAPER",
        "risk": {
            "max_risk_per_trade_pct": 0.02,
            "max_open_positions": 3,
            "account_balance": 50000.0,
            "max_leverage": 2.0,
        },
        "logging": {
            "log_level": "DEBUG",
            "log_format": "%(message)s",
        },
    }
    custom_file = tmp_path / "custom_config.json"
    custom_file.write_text(json.dumps(custom_data), encoding="utf-8")

    config = load_config(custom_file)
    assert config.environment == AppEnvironment.TEST
    assert config.execution_mode == ExecutionMode.PAPER
    assert config.risk.max_risk_per_trade_pct == 0.02
    assert config.risk.max_open_positions == 3
    assert config.risk.account_balance == 50000.0
    assert config.risk.max_leverage == 2.0
    assert config.logging.log_level == "DEBUG"


def test_load_config_file_not_found():
    """Verify FileNotFoundError when config path does not exist."""
    with pytest.raises(FileNotFoundError):
        load_config("non_existent_config_file_123.json")


def test_load_config_malformed_json(tmp_path: Path):
    """Verify ValueError when configuration file contains malformed JSON."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ invalid json: ", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed JSON"):
        load_config(bad_file)


def test_load_config_invalid_schema(tmp_path: Path):
    """Verify ValidationError when configuration violates schema rules."""
    invalid_data = {
        "environment": "unsupported_env",
        "execution_mode": "INVALID_MODE",
        "risk": {
            "max_risk_per_trade_pct": -0.5,  # Invalid: must be > 0
            "max_open_positions": 0,          # Invalid: must be >= 1
            "account_balance": -100.0,        # Invalid: must be > 0
        },
    }
    invalid_file = tmp_path / "invalid_config.json"
    invalid_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(invalid_file)


def test_config_immutability():
    """Verify that AppConfig instances are frozen/immutable."""
    config = load_config()
    with pytest.raises(ValidationError):
        config.environment = AppEnvironment.PROD  # type: ignore
