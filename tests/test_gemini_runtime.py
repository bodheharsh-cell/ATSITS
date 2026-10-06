"""Unit and integration tests for Gemini configuration, client wrapper, and MCP runtime."""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import pytest
from pydantic import BaseModel

from atsits.gemini.client import GeminiClient, _sanitize_error_message
from atsits.gemini.config import GeminiConfig, _mask_secret, load_gemini_config
from atsits.gemini.exceptions import (
    GeminiAPIError,
    GeminiAuthError,
    GeminiError,
    GeminiNotConfiguredError,
)
from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.mcp.client import MCPClient
from atsits.mcp.server import MCPServer


# ---------------------------------------------------------------------
# 1. Config and Secret Masking Tests
# ---------------------------------------------------------------------
def test_mask_secret():
    assert _mask_secret(None) == "<not configured>"
    assert _mask_secret("") == "<not configured>"
    assert _mask_secret("12345") == "****"
    assert _mask_secret("AIzaSyD-123456789-abcdef") == "AIza...cdef"


def test_gemini_config_defaults_and_masking():
    cfg = GeminiConfig(api_key="AIzaSySecretApiKey123456789")
    assert cfg.is_configured is True
    assert "AIzaSySecretApiKey123456789" not in repr(cfg)
    assert "AIzaSySecretApiKey123456789" not in str(cfg)
    assert cfg.masked_key == "AIza...6789"
    assert cfg.model_name == "gemini-2.5-flash-lite"
    assert cfg.temperature == 0.2


def test_gemini_config_unconfigured():
    cfg = GeminiConfig(api_key=None)
    assert cfg.is_configured is False
    assert cfg.masked_key == "<not configured>"


def test_load_gemini_config_env_priority(monkeypatch, tmp_path):
    # Test loading from custom .env file
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=key_from_dotenv\nGEMINI_MODEL=gemini-3.7-flash\n", encoding="utf-8")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    cfg = load_gemini_config(env_file=env_file)
    assert cfg.api_key == "key_from_dotenv"
    assert cfg.model_name == "gemini-3.7-flash"

    # Direct override priority
    cfg_override = load_gemini_config(env_file=env_file, api_key_override="override_key")
    assert cfg_override.api_key == "override_key"


def test_sanitize_error_message():
    secret = "AIzaSyD_Secret_Key_9999"
    raw_error = f"API error with key {secret} at endpoint"
    clean = _sanitize_error_message(raw_error, secret)
    assert secret not in clean
    assert "[REDACTED_API_KEY]" in clean


# ---------------------------------------------------------------------
# 2. GeminiClient Tests
# ---------------------------------------------------------------------
def test_client_unconfigured_error():
    cfg = GeminiConfig(api_key=None)
    client = GeminiClient(config=cfg)
    assert client.is_configured is False

    success, msg = client.test_connection()
    assert success is False
    assert "not configured" in msg

    with pytest.raises(GeminiNotConfiguredError):
        client.generate_content("hello")


def test_client_test_connection_success():
    cfg = GeminiConfig(api_key="mock_valid_key")
    mock_raw = MagicMock()
    mock_resp = MagicMock()
    mock_raw.models.generate_content.return_value = mock_resp

    client = GeminiClient(config=cfg, raw_client=mock_raw)
    success, msg = client.test_connection()

    assert success is True
    assert "Successfully authenticated" in msg
    mock_raw.models.generate_content.assert_called_once()


def test_client_test_connection_auth_failure():
    cfg = GeminiConfig(api_key="mock_invalid_key")
    mock_raw = MagicMock()
    mock_raw.models.generate_content.side_effect = Exception("401 Unauthorized API key not valid")

    client = GeminiClient(config=cfg, raw_client=mock_raw)
    success, msg = client.test_connection()

    assert success is False
    assert "authentication failed" in msg


def test_client_generate_content_error_translation():
    cfg = GeminiConfig(api_key="secret_key_123")
    mock_raw = MagicMock()
    mock_raw.models.generate_content.side_effect = Exception("403 Forbidden secret_key_123")

    client = GeminiClient(config=cfg, raw_client=mock_raw)
    with pytest.raises(GeminiAuthError) as exc_info:
        client.generate_content("test")

    assert "secret_key_123" not in str(exc_info.value)
    assert "[REDACTED_API_KEY]" in str(exc_info.value)


# ---------------------------------------------------------------------
# 3. GeminiMCPRuntime Tests with Mock SDK
# ---------------------------------------------------------------------
def test_runtime_tools_extraction():
    mcp_server = MCPServer()
    mcp_client = MCPClient(server=mcp_server)
    cfg = GeminiConfig(api_key="test_key")
    runtime = GeminiMCPRuntime(config=cfg, mcp_client=mcp_client)

    tools = runtime._get_tools()
    assert len(tools) == 1
    fds = tools[0].function_declarations
    assert len(fds) >= 19
    names = [fd.name for fd in fds]
    assert "get_strategy" in names
    assert "get_market_state" in names
    assert "create_teaching_material" in names
    assert "extract_strategy_draft" in names


def test_runtime_multi_turn_tool_calling_loop():
    from google.genai import types

    cfg = GeminiConfig(api_key="test_key", max_turns=5)
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    mcp_server = MCPServer()
    mcp_client = MCPClient(server=mcp_server)

    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp_client)

    # Turn 1: Gemini decides to call get_strategy
    fc = types.FunctionCall(name="get_strategy", args={"strategy_version": None})
    cand1 = types.Candidate(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=fc)],
        )
    )
    resp1 = types.GenerateContentResponse(candidates=[cand1])

    # Turn 2: Gemini gives final answer after tool response
    cand2 = types.Candidate(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="The production strategy is EMA_Pullback_v1.0.")],
        )
    )
    resp2 = types.GenerateContentResponse(candidates=[cand2])

    mock_client.generate_content.side_effect = [resp1, resp2]

    tool_invocations = []

    def on_tool(name, args, res):
        tool_invocations.append((name, args, res))

    result_text = runtime.send_message("What is the current strategy?", on_tool_call=on_tool)

    assert result_text == "The production strategy is EMA_Pullback_v1.0."
    assert len(tool_invocations) == 1
    assert tool_invocations[0][0] == "get_strategy"
    assert tool_invocations[0][2]["is_error"] is False
    assert mock_client.generate_content.call_count == 2
    assert len(runtime.history) == 4  # user -> model (fc) -> user (tool response) -> model (final)


def test_runtime_teach_prompt_generation():
    cfg = GeminiConfig(api_key="test_key")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    cand = types = MagicMock()
    mock_client.generate_content.return_value = MagicMock(
        candidates=[
            MagicMock(
                content=MagicMock(
                    parts=[MagicMock(text="Structured teaching analysis with ambiguities highlighted.", function_call=None)]
                )
            )
        ],
        function_calls=[],
        text="Structured teaching analysis with ambiguities highlighted.",
    )

    runtime = GeminiMCPRuntime(config=cfg, client=mock_client)
    res = runtime.teach(teaching_text="Rule 1: Enter on 1h pullback.", source_name="Notes.txt")

    assert "Structured teaching analysis" in res
    assert mock_client.generate_content.called
    user_turn = runtime.history[0]
    prompt_text = user_turn.parts[0].text
    assert "Rule 1: Enter on 1h pullback." in prompt_text
    assert "Notes.txt" in prompt_text
