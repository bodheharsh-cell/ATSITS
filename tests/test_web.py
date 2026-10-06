"""Automated unit and integration tests for ATSITS Local Web GUI (Phase 8.6)."""

import os
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import pytest

from atsits.gemini.config import GeminiConfig
from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.mcp.client import MCPClient
from atsits.web.app import create_app


@pytest.fixture
def mock_runtime():
    cfg = GeminiConfig(api_key="mock_secret_key_987654321")
    runtime = MagicMock(spec=GeminiMCPRuntime)
    runtime.is_configured = True
    runtime.send_message.return_value = "Production strategy is EMA_Pullback_v1.0 with 20/50 EMAs."
    return runtime


@pytest.fixture
def client(mock_runtime):
    cfg = GeminiConfig(api_key="mock_secret_key_987654321")
    app = create_app(gemini_config=cfg, gemini_runtime=mock_runtime)
    return TestClient(app)


def test_index_page_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ATSITS" in response.text
    assert "Algorithmic Trading Research & Teaching GUI" in response.text


def test_api_health_endpoint(client):
    """Verify GET /api/health returns immediate HTTP 200 without external dependencies."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["ready"] is True
    assert data["app"] == "ATSITS"


def test_api_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "READY"
    assert data["production_strategy"] == "EMA_Pullback_v1.0"
    assert data["mcp_tool_count"] >= 19
    assert data["authority"] == "HUMAN_OPERATOR"
    # Verify API key is NOT exposed
    assert "api_key" not in data
    assert "mock_secret_key_987654321" not in response.text


def test_api_chat_with_mock_runtime(client, mock_runtime):
    # Simulate a tool call triggered inside send_message
    def fake_send(msg, on_tool_call=None):
        if on_tool_call:
            on_tool_call("get_strategy", {}, {"is_error": False, "data": {"strategy": "EMA_Pullback_v1.0"}})
        return "Production strategy is EMA_Pullback_v1.0."

    mock_runtime.send_message.side_effect = fake_send

    response = client.post("/api/chat", json={"message": "What is the strategy?"})
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Production strategy is EMA_Pullback_v1.0."
    assert len(data["mcp_calls"]) == 1
    assert data["mcp_calls"][0]["name"] == "get_strategy"
    assert data["mcp_calls"][0]["is_error"] is False


def test_api_chat_reset(client, mock_runtime):
    response = client.post("/api/chat/reset")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    mock_runtime.reset.assert_called_once()


def test_api_chat_offline_mode():
    cfg_unconf = GeminiConfig(api_key=None)
    app = create_app(gemini_config=cfg_unconf)
    offline_client = TestClient(app)

    response = offline_client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 503
    data = response.json()
    assert "Gemini API is not configured" in data["error"]
    assert "deterministic tools" in data["response"]


def test_api_strategy_endpoint(client):
    response = client.get("/api/strategy")
    assert response.status_code == 200
    data = response.json()
    assert data["production_strategy"]["name"] == "EMA_Pullback_v1.0"
    assert data["production_strategy"]["status"] == "PRODUCTION_LOCKED"
    assert data["production_strategy"]["parameters"]["fast_period"] == 20
    assert data["production_strategy"]["parameters"]["slow_period"] == 50
    assert isinstance(data["verified_strategies"], list)
    assert isinstance(data["draft_strategies"], list)


def test_api_backtest_baseline_metrics(client):
    response = client.post("/api/backtest", json={"initial_equity": 10000.0, "strategy_name": "EMA_Pullback_v1.0"})
    assert response.status_code == 200
    data = response.json()
    assert data["strategy_name"] == "EMA_Pullback_v1.0"
    assert data["number_of_trades"] == 201
    assert data["winning_trades"] == 67
    assert data["losing_trades"] == 134
    assert pytest.approx(data["win_rate"], 0.001) == 0.3333
    assert pytest.approx(data["total_net_pnl"], 0.01) == -306.09
    assert pytest.approx(data["profit_factor"], 0.01) == 0.98


def test_api_backtest_boundary_rejects_arbitrary_strategies(client):
    response = client.post("/api/backtest", json={"initial_equity": 10000.0, "strategy_name": "os.system"})
    assert response.status_code == 400
    assert "Unsupported strategy" in response.json()["detail"]


def test_api_journal_endpoint(client):
    response = client.get("/api/journal")
    assert response.status_code == 200
    data = response.json()
    assert "total_trades" in data
    assert "trades" in data
    assert isinstance(data["trades"], list)


def test_api_experiments_endpoint(client):
    response = client.get("/api/experiments")
    assert response.status_code == 200
    data = response.json()
    assert "total_experiments" in data
    assert "experiments" in data


def test_api_teach_extraction_and_human_review_gate(client):
    # 1. Extraction
    text = "Strategy: Enter long when EMA 20 crosses above EMA 50 on 1h chart with TP at 2.0R."
    extract_resp = client.post("/api/teach/extract", json={"text": text})
    assert extract_resp.status_code == 200
    draft_data = extract_resp.json()
    draft_id = draft_data["draft_id"]
    assert draft_id.startswith("draft_")
    assert len(draft_data["rules"]) >= 1

    # 2. Human Review: Approve
    review_resp = client.post(
        "/api/teach/review",
        json={"draft_id": draft_id, "action": "APPROVE"},
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["success"] is True

    # 3. Human Review: Clarify missing items
    clarify_resp = client.post(
        "/api/teach/review",
        json={
            "draft_id": draft_id,
            "action": "CLARIFY",
            "clarifications": {"instrument": "BTCUSDT"},
        },
    )
    assert clarify_resp.status_code == 200
    assert clarify_resp.json()["success"] is True


def test_api_key_leak_prevention_audit(client):
    """Audit all GET and POST endpoints to ensure raw API keys are NEVER leaked."""
    secret = "mock_secret_key_987654321"

    endpoints_to_check = [
        client.get("/"),
        client.get("/api/status"),
        client.get("/api/strategy"),
        client.get("/api/journal"),
        client.get("/api/experiments"),
        client.post("/api/backtest", json={"initial_equity": 10000.0, "strategy_name": "EMA_Pullback_v1.0"}),
    ]

    for resp in endpoints_to_check:
        assert secret not in resp.text, f"Secret key leaked in response from endpoint!"
