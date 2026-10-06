"""Comprehensive automated tests for Gemini Model Selection & Runtime Configuration (Phase 8.7)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from atsits.cli import ATSITSCLI, build_parser
from atsits.gemini.client import GeminiClient
from atsits.gemini.config import (
    DEFAULT_GEMINI_MODEL,
    SUPPORTED_GEMINI_MODELS,
    GeminiConfig,
    get_supported_models,
    load_gemini_config,
    persist_gemini_model,
    validate_model_id,
)
from atsits.gemini.exceptions import GeminiQuotaExceededError
from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.mcp.client import MCPClient
from atsits.web.app import create_app


# ----------------------------------------------------------------------
# 1. Model Registry & Validation Unit Tests
# ----------------------------------------------------------------------
def test_supported_models_registry_contents():
    """Verify all 5 required Gemini models are in the whitelist with display names."""
    expected_models = {
        "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
        "gemini-3.6-flash": "Gemini 3.6 Flash",
        "gemini-3.7-flash": "Gemini 3.7 Flash",
        "gemini-3.8-flash": "Gemini 3.8 Flash",
    }
    assert set(SUPPORTED_GEMINI_MODELS.keys()) == set(expected_models.keys())

    for model_id, display_name in expected_models.items():
        info = SUPPORTED_GEMINI_MODELS[model_id]
        assert info.model_id == model_id
        assert info.display_name == display_name
        assert len(info.description) > 5

    # Verify default model is gemini-2.5-flash-lite
    assert SUPPORTED_GEMINI_MODELS[DEFAULT_GEMINI_MODEL].is_default is True
    # Ensure no live models are in whitelist
    for model_id in SUPPORTED_GEMINI_MODELS:
        assert "live" not in model_id.lower()


def test_get_supported_models_list():
    """Verify get_supported_models returns properly structured list for UI/API."""
    models_list = get_supported_models()
    assert len(models_list) == 5
    ids = [m["model_id"] for m in models_list]
    assert "gemini-2.5-flash-lite" in ids
    assert "gemini-3.8-flash" in ids


def test_validate_model_id_success_and_normalization():
    """Verify validate_model_id accepts valid IDs and strips 'models/' prefix."""
    assert validate_model_id("gemini-3.7-flash") == "gemini-3.7-flash"
    assert validate_model_id("models/gemini-3.6-flash") == "gemini-3.6-flash"
    assert validate_model_id("  gemini-2.5-flash-lite  ") == "gemini-2.5-flash-lite"


def test_validate_model_id_rejection():
    """Verify invalid or forbidden models (e.g. Gemini Live) are rejected."""
    with pytest.raises(ValueError, match="Unsupported Gemini model"):
        validate_model_id("gemini-3.8-live")

    with pytest.raises(ValueError, match="Unsupported Gemini model"):
        validate_model_id("gemini-1.5-pro")

    with pytest.raises(ValueError, match="Unsupported Gemini model"):
        validate_model_id("gpt-4o")


# ----------------------------------------------------------------------
# 2. Config & .env Persistence Tests
# ----------------------------------------------------------------------
def test_gemini_config_display_name_and_with_model():
    """Verify GeminiConfig display name resolution and immutable model clone."""
    cfg = GeminiConfig(api_key="test_key", model_name="gemini-3.7-flash")
    assert cfg.display_name == "Gemini 3.7 Flash"

    new_cfg = cfg.with_model("gemini-3.8-flash")
    assert new_cfg.model_name == "gemini-3.8-flash"
    assert new_cfg.display_name == "Gemini 3.8 Flash"
    assert new_cfg.api_key == cfg.api_key


def test_persist_gemini_model(tmp_path):
    """Verify persist_gemini_model updates .env safely without touching API key."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=AQ.test_api_key_12345\nGEMINI_MODEL=gemini-2.5-flash-lite\nOTHER_VAR=xyz\n",
        encoding="utf-8",
    )

    persist_gemini_model("gemini-3.6-flash", env_file=env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "GEMINI_MODEL=gemini-3.6-flash" in content
    assert "GEMINI_API_KEY=AQ.test_api_key_12345" in content
    assert "OTHER_VAR=xyz" in content


# ----------------------------------------------------------------------
# 3. GeminiMCPRuntime Dynamic Model Switching Tests
# ----------------------------------------------------------------------
def test_runtime_dynamic_model_switch():
    """Verify GeminiMCPRuntime updates active model and recreates Gemini client."""
    cfg = GeminiConfig(api_key="mock_key", model_name="gemini-2.5-flash-lite")
    mcp_client = MagicMock(spec=MCPClient)
    runtime = GeminiMCPRuntime(config=cfg, mcp_client=mcp_client)

    assert runtime.current_model == "gemini-2.5-flash-lite"
    assert runtime.config.display_name == "Gemini 2.5 Flash Lite"

    # Switch model
    runtime.set_model("gemini-3.7-flash")
    assert runtime.current_model == "gemini-3.7-flash"
    assert runtime.config.display_name == "Gemini 3.7 Flash"
    assert runtime.client.config.model_name == "gemini-3.7-flash"


def test_runtime_rejects_invalid_model():
    """Verify GeminiMCPRuntime raises ValueError on unsupported model."""
    cfg = GeminiConfig(api_key="mock_key")
    runtime = GeminiMCPRuntime(config=cfg)
    with pytest.raises(ValueError, match="Unsupported Gemini model"):
        runtime.set_model("invalid-model-name")


# ----------------------------------------------------------------------
# 4. Web API Endpoints Tests (/api/models & /api/model)
# ----------------------------------------------------------------------
@pytest.fixture
def web_test_client():
    cfg = GeminiConfig(api_key="mock_secret_key_123", model_name="gemini-2.5-flash-lite")
    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, mcp_client=mcp)
    app = create_app(gemini_config=cfg, gemini_runtime=runtime, mcp_client=mcp)
    return TestClient(app), runtime


def test_get_api_models(web_test_client):
    """Verify GET /api/models returns model list and active model."""
    client, runtime = web_test_client
    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert len(data["models"]) == 5
    assert data["active_model_id"] == "gemini-2.5-flash-lite"
    assert data["active_display_name"] == "Gemini 2.5 Flash Lite"


def test_post_api_model_success(web_test_client, tmp_path):
    """Verify POST /api/model updates runtime model."""
    client, runtime = web_test_client

    with patch("atsits.web.app.persist_gemini_model") as mock_persist:
        res = client.post("/api/model", json={"model_id": "gemini-3.8-flash", "persist": True})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["model_id"] == "gemini-3.8-flash"
        assert data["display_name"] == "Gemini 3.8 Flash"
        assert runtime.current_model == "gemini-3.8-flash"
        mock_persist.assert_called_once_with("gemini-3.8-flash")


def test_post_api_model_invalid(web_test_client):
    """Verify POST /api/model returns 400 for invalid model."""
    client, runtime = web_test_client
    res = client.post("/api/model", json={"model_id": "unsupported-model"})
    assert res.status_code == 400
    data = res.json()
    assert "detail" in data or "error" in data


def test_api_status_includes_model_metadata(web_test_client):
    """Verify GET /api/status includes gemini_model_display."""
    client, runtime = web_test_client
    runtime.set_model("gemini-2.5-flash-lite")
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["gemini_model"] == "gemini-2.5-flash-lite"
    assert data["gemini_model_display"] == "Gemini 2.5 Flash Lite"


# ----------------------------------------------------------------------
# 5. Quota Error (429) Handling Tests
# ----------------------------------------------------------------------
def test_quota_error_handling_in_chat(web_test_client):
    """Verify 429 quota exhaustion produces clean error response advising model switch."""
    client, runtime = web_test_client

    quota_err = GeminiQuotaExceededError(
        "Gemini 2.5 Flash Lite quota exhausted. Switch to another available model or try again later.",
        model_name="gemini-2.5-flash-lite",
    )

    with patch.object(runtime, "send_message", side_effect=quota_err):
        res = client.post("/api/chat", json={"message": "Analyze market"})
        assert res.status_code == 200
        data = res.json()
        assert data["error_code"] == "QUOTA_EXHAUSTED"
        assert "Gemini 2.5 Flash Lite quota exhausted" in data["message"]
        # Verify no secret leaked
        assert "mock_secret_key" not in res.text


# ----------------------------------------------------------------------
# 6. CLI --model Flags and Status Display Tests
# ----------------------------------------------------------------------
def test_cli_parser_model_flags():
    """Verify CLI parser accepts --model / -m across subcommands."""
    parser = build_parser()

    args_chat = parser.parse_args(["chat", "--model", "gemini-3.7-flash", "Hello"])
    assert args_chat.model == "gemini-3.7-flash"
    assert args_chat.prompt == ["Hello"]

    args_teach = parser.parse_args(["teach", "-m", "gemini-3.6-flash", "--text", "Rules"])
    assert args_teach.model == "gemini-3.6-flash"

    args_status = parser.parse_args(["status", "--model", "gemini-3.8-flash"])
    assert args_status.model == "gemini-3.8-flash"


def test_cli_status_displays_supported_models(capsys):
    """Verify CLI status displays active model and model options."""
    cfg = GeminiConfig(api_key=None, model_name="gemini-2.5-flash-lite")
    cli = ATSITSCLI(gemini_config=cfg)
    cli.status()

    captured = capsys.readouterr().out
    assert "Gemini Model: Gemini 2.5 Flash Lite (gemini-2.5-flash-lite)" in captured
    assert "Supported Gemini Models:" in captured
    assert "[*] Gemini 2.5 Flash Lite" in captured
    assert "[ ] Gemini 3.8 Flash" in captured


def test_cli_set_model_dynamically(capsys):
    """Verify cli.set_model() switches model and output."""
    cfg = GeminiConfig(api_key=None, model_name="gemini-2.5-flash-lite")
    cli = ATSITSCLI(gemini_config=cfg)
    cli.set_model("gemini-3.8-flash", persist=False)

    assert cli.config.model_name == "gemini-3.8-flash"
    assert cli.config.display_name == "Gemini 3.8 Flash"
    captured = capsys.readouterr().out
    assert "Active Gemini model set to: Gemini 3.8 Flash (gemini-3.8-flash)" in captured
