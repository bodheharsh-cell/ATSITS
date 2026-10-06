"""Comprehensive deterministic tests for Phase 8.8 Automatic Model Router & Quota Resilience."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from atsits.gemini.client import GeminiClient, categorize_error
from atsits.gemini.config import GeminiConfig, load_gemini_config, persist_gemini_selection_mode
from atsits.gemini.exceptions import (
    AllModelsUnavailableError,
    CriticalTaskDowngradePreventedError,
    GeminiAPIError,
    GeminiAuthError,
    GeminiQuotaExceededError,
)
from atsits.gemini.router import (
    CapabilityTier,
    FailureCategory,
    MODEL_CAPABILITIES,
    ModelHealthState,
    ModelHealthTracker,
    ModelRouter,
    RoutingMode,
    TaskClass,
    TaskClassification,
    TaskClassifier,
)
from atsits.gemini.runtime import GeminiMCPRuntime
from atsits.mcp.client import MCPClient
from atsits.mcp.server import MCPServer
from atsits.web.app import create_app


# ---------------------------------------------------------------------
# 1. Deterministic Task Classification Tests (1-4)
# ---------------------------------------------------------------------
def test_1_simple_classification():
    classifier = TaskClassifier()
    assert classifier.classify("ping").task_class == TaskClass.SIMPLE
    assert classifier.classify("status").task_class == TaskClass.SIMPLE
    assert classifier.classify("what is the price of BTC").task_class == TaskClass.SIMPLE
    assert classifier.classify("list tools").task_class == TaskClass.SIMPLE
    assert classifier.classify("hello").task_class == TaskClass.SIMPLE


def test_2_standard_classification():
    classifier = TaskClassifier()
    # Normal coding, debugging, or document queries
    res = classifier.classify("Can you explain how the EMA pullback indicator updates incrementally?")
    assert res.task_class == TaskClass.STANDARD
    assert res.minimum_capability == CapabilityTier.STANDARD


def test_3_complex_classification():
    classifier = TaskClassifier()
    # Multi-document or conflicting rules
    text = "Extract strategy from multi-document notes with conflicting rules and backtest analysis."
    res = classifier.classify(text)
    assert res.task_class == TaskClass.COMPLEX
    assert res.minimum_capability == CapabilityTier.STRONG

    # Long text (>1200 chars)
    long_text = "Rule analysis: " + "a" * 1300
    assert classifier.classify(long_text).task_class == TaskClass.COMPLEX


def test_4_critical_classification():
    classifier = TaskClassifier()
    assert classifier.classify("Verify strategy consistency before promotion").task_class == TaskClass.CRITICAL
    assert classifier.classify("Audit safety boundary and confirm rule invariants").task_class == TaskClass.CRITICAL
    assert classifier.classify("Reconcile conflicts in verified strategy spec").task_class == TaskClass.CRITICAL

    # Explicit context override
    res = classifier.classify("Check something", context={"is_critical": True})
    assert res.task_class == TaskClass.CRITICAL


# ---------------------------------------------------------------------
# 2. Model Selection by Task Class (5-8)
# ---------------------------------------------------------------------
def test_5_simple_selects_lightweight_model():
    router = ModelRouter()
    tc = TaskClassification(
        task_class=TaskClass.SIMPLE,
        minimum_capability=CapabilityTier.LIGHTWEIGHT,
        confidence=1.0,
        reason="simple query",
    )
    model, meta = router.select_initial_model(tc)
    assert model == "gemini-3.1-flash-lite"
    assert meta.selected_model == "gemini-3.1-flash-lite"
    assert meta.task_class == "SIMPLE"


def test_6_standard_selects_standard_model():
    router = ModelRouter()
    tc = TaskClassification(
        task_class=TaskClass.STANDARD,
        minimum_capability=CapabilityTier.STANDARD,
        confidence=1.0,
        reason="standard task",
    )
    model, meta = router.select_initial_model(tc)
    assert model == "gemini-3.6-flash"
    assert meta.selected_model == "gemini-3.6-flash"


def test_7_complex_selects_stronger_model():
    router = ModelRouter()
    tc = TaskClassification(
        task_class=TaskClass.COMPLEX,
        minimum_capability=CapabilityTier.STRONG,
        confidence=1.0,
        reason="complex task",
    )
    model, meta = router.select_initial_model(tc)
    assert model == "gemini-3.7-flash"
    assert meta.selected_model == "gemini-3.7-flash"


def test_8_critical_selects_strongest_suitable_model():
    router = ModelRouter()
    tc = TaskClassification(
        task_class=TaskClass.CRITICAL,
        minimum_capability=CapabilityTier.STRONG,
        confidence=1.0,
        reason="critical task",
    )
    model, meta = router.select_initial_model(tc)
    assert model == "gemini-3.8-flash"
    assert meta.selected_model == "gemini-3.8-flash"


# ---------------------------------------------------------------------
# 3. AUTO vs MANUAL Mode Tests (9-10)
# ---------------------------------------------------------------------
def test_9_auto_mode_respects_task():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.SIMPLE,
        minimum_capability=CapabilityTier.LIGHTWEIGHT,
        confidence=1.0,
        reason="simple",
    )
    model, meta = router.select_initial_model(tc, manual_override_model="gemini-3.8-flash")
    assert model == "gemini-3.1-flash-lite"
    assert meta.mode == "AUTO"


def test_10_manual_mode_honors_user_override():
    router = ModelRouter(default_mode=RoutingMode.MANUAL)
    tc = TaskClassification(
        task_class=TaskClass.SIMPLE,
        minimum_capability=CapabilityTier.LIGHTWEIGHT,
        confidence=1.0,
        reason="simple",
    )
    model, meta = router.select_initial_model(tc, manual_override_model="gemini-3.8-flash")
    assert model == "gemini-3.8-flash"
    assert meta.mode == "MANUAL"
    assert "Manual operator selection" in meta.selection_reason


# ---------------------------------------------------------------------
# 4. Quota Exhaustion, Health Tracking, and Cooldown Tests (11-15)
# ---------------------------------------------------------------------
def test_11_429_causes_cooldown():
    tracker = ModelHealthTracker(base_cooldown_seconds=60.0)
    assert tracker.is_available("gemini-3.6-flash") is True

    cooldown = tracker.record_failure("gemini-3.6-flash", FailureCategory.QUOTA_EXHAUSTED, "429 Quota")
    assert cooldown == 60.0
    assert tracker.is_available("gemini-3.6-flash") is False
    status = tracker.get_model_status("gemini-3.6-flash")
    assert status["state"] == "TEMPORARILY_UNAVAILABLE"
    assert status["consecutive_failures"] == 1


def test_12_429_causes_fallback():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.STANDARD,
        minimum_capability=CapabilityTier.STANDARD,
        confidence=1.0,
        reason="standard",
    )

    # Initial model: gemini-3.6-flash
    model, _ = router.select_initial_model(tc)
    assert model == "gemini-3.6-flash"

    # Simulate 429 failure
    router.health_tracker.record_failure(model, FailureCategory.QUOTA_EXHAUSTED)

    # Fallback model should be gemini-3.7-flash (next in STANDARD chain)
    fallback_model, meta = router.get_fallback_model(
        current_model=model,
        task_classification=tc,
        failure_category=FailureCategory.QUOTA_EXHAUSTED,
        attempt=0,
    )
    assert fallback_model == "gemini-3.7-flash"
    assert meta.fallback_attempt == 1
    assert meta.previous_model == "gemini-3.6-flash"
    assert meta.failure_reason == "QUOTA_EXHAUSTED"


def test_13_same_exhausted_model_not_immediately_retried():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    router.health_tracker.record_failure("gemini-3.1-flash-lite", FailureCategory.QUOTA_EXHAUSTED)

    tc = TaskClassification(
        task_class=TaskClass.SIMPLE,
        minimum_capability=CapabilityTier.LIGHTWEIGHT,
        confidence=1.0,
        reason="simple",
    )
    # Next initial selection for SIMPLE must skip 3.1-flash-lite and select 2.5-flash-lite
    selected, _ = router.select_initial_model(tc)
    assert selected != "gemini-3.1-flash-lite"
    assert selected == "gemini-2.5-flash-lite"


def test_14_cooldown_expires_correctly():
    tracker = ModelHealthTracker()
    now = datetime.now(timezone.utc)

    # Force a failure with past cooldown
    rec = tracker._get_or_create("gemini-3.6-flash")
    rec.health_state = ModelHealthState.TEMPORARILY_UNAVAILABLE
    rec.cooldown_until = now - timedelta(seconds=10)

    # Upon checking availability, cooldown should have expired
    assert tracker.is_available("gemini-3.6-flash") is True
    assert rec.health_state == ModelHealthState.AVAILABLE


def test_15_multiple_fallbacks_are_bounded():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.CRITICAL,
        minimum_capability=CapabilityTier.STRONG,
        confidence=1.0,
        reason="critical",
    )
    # Critical candidates are 3.8 and 3.7
    router.health_tracker.record_failure("gemini-3.8-flash", FailureCategory.QUOTA_EXHAUSTED)
    fallback1, _ = router.get_fallback_model("gemini-3.8-flash", tc, FailureCategory.QUOTA_EXHAUSTED, 0)
    assert fallback1 == "gemini-3.7-flash"

    router.health_tracker.record_failure("gemini-3.7-flash", FailureCategory.QUOTA_EXHAUSTED)
    with pytest.raises(CriticalTaskDowngradePreventedError):
        router.get_fallback_model("gemini-3.7-flash", tc, FailureCategory.QUOTA_EXHAUSTED, 1)


# ---------------------------------------------------------------------
# 5. Error Boundaries and Downgrade Protection Tests (16-22)
# ---------------------------------------------------------------------
def test_16_all_models_unavailable_produces_clear_error():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.STANDARD,
        minimum_capability=CapabilityTier.STANDARD,
        confidence=1.0,
        reason="standard",
    )
    # Exhaust all models
    for m in MODEL_CAPABILITIES:
        router.health_tracker.record_failure(m, FailureCategory.QUOTA_EXHAUSTED)

    with pytest.raises(AllModelsUnavailableError) as exc_info:
        router.select_initial_model(tc)
    assert "All candidate models for task [STANDARD] are exhausted" in str(exc_info.value)


def test_17_critical_task_cannot_downgrade_below_minimum_capability():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.CRITICAL,
        minimum_capability=CapabilityTier.STRONG,
        confidence=1.0,
        reason="critical",
    )
    # Mark strong models unavailable
    router.health_tracker.record_failure("gemini-3.8-flash", FailureCategory.QUOTA_EXHAUSTED)
    router.health_tracker.record_failure("gemini-3.7-flash", FailureCategory.QUOTA_EXHAUSTED)

    # Must NOT downgrade to gemini-3.1-flash-lite or 2.5-flash-lite
    with pytest.raises(CriticalTaskDowngradePreventedError) as exc_info:
        router.select_initial_model(tc)
    assert "automatic downgrade prevented" in str(exc_info.value).lower()


def test_18_routing_metadata_structure():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.STANDARD,
        minimum_capability=CapabilityTier.STANDARD,
        confidence=0.9,
        reason="test task",
        suggested_thinking="MEDIUM",
    )
    _, meta = router.select_initial_model(tc)
    data = meta.to_dict()
    assert data["router_version"] == "1.0"
    assert data["mode"] == "AUTO"
    assert data["task_class"] == "STANDARD"
    assert data["selected_model"] == "gemini-3.6-flash"
    assert data["fallback_attempt"] == 0
    assert data["model_health"] == "AVAILABLE"


def test_19_no_secrets_in_metadata_or_logs():
    meta = router_meta = TaskClassification(
        task_class=TaskClass.SIMPLE,
        minimum_capability=CapabilityTier.LIGHTWEIGHT,
        confidence=1.0,
        reason="test",
    )
    router = ModelRouter()
    _, m = router.select_initial_model(meta)
    d = m.to_dict()
    for k, v in d.items():
        assert "key" not in k.lower()
        assert "secret" not in k.lower()


def test_20_authentication_errors_do_not_fallback():
    router = ModelRouter(default_mode=RoutingMode.AUTO)
    tc = TaskClassification(
        task_class=TaskClass.STANDARD,
        minimum_capability=CapabilityTier.STANDARD,
        confidence=1.0,
        reason="auth test",
    )
    with pytest.raises(GeminiAuthError) as exc_info:
        router.get_fallback_model("gemini-3.6-flash", tc, FailureCategory.AUTHENTICATION_ERROR, 0)
    assert "authentication failed. Do not retry other models" in str(exc_info.value)


def test_21_network_errors_are_bounded():
    tracker = ModelHealthTracker()
    cooldown = tracker.record_failure("gemini-3.6-flash", FailureCategory.NETWORK_ERROR, "connection reset")
    assert cooldown == 15.0
    assert tracker.is_available("gemini-3.6-flash") is False


def test_22_server_errors_are_bounded():
    tracker = ModelHealthTracker()
    cooldown = tracker.record_failure("gemini-3.7-flash", FailureCategory.SERVER_ERROR, "503 Service Unavailable")
    assert cooldown == 15.0
    assert tracker.is_available("gemini-3.7-flash") is False


# ---------------------------------------------------------------------
# 6. MCP Safety & Duplicate Protection Tests (23-25)
# ---------------------------------------------------------------------
def test_23_mcp_read_only_conversation_survives_fallback():
    from google.genai import types

    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    # First model (3.1-flash-lite) fails with 429
    # Second model (2.5-flash-lite) succeeds
    quota_err = GeminiQuotaExceededError("429 Quota", model_name="gemini-3.1-flash-lite")
    cand = types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Pong")]))
    success_resp = types.GenerateContentResponse(candidates=[cand])

    mock_client.generate_content.side_effect = [quota_err, success_resp]

    res = runtime.send_message("ping")
    assert res == "Pong"
    assert runtime.last_routing_metadata.fallback_attempt == 1
    assert runtime.last_routing_metadata.previous_model == "gemini-3.1-flash-lite"
    assert runtime.last_routing_metadata.selected_model == "gemini-2.5-flash-lite"


def test_24_mcp_action_cannot_be_duplicated_by_fallback():
    from google.genai import types

    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    # Tool mock returns success
    mcp.call_tool.return_value = {"status": "FILLED", "order_id": "ORD-123"}

    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    # Turn 1: Model calls place_paper_order
    fc = types.FunctionCall(name="place_paper_order", args={"side": "BUY", "quantity": 0.1})
    cand1 = types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=fc)]))
    resp1 = types.GenerateContentResponse(candidates=[cand1])

    # Turn 2: Attempt 1 fails with 429; Attempt 2 (fallback model) succeeds with summary text
    quota_err = GeminiQuotaExceededError("429 Quota", model_name="gemini-3.6-flash")
    cand2 = types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Paper order placed.")]))
    resp2 = types.GenerateContentResponse(candidates=[cand2])

    mock_client.generate_content.side_effect = [resp1, quota_err, resp2]

    res = runtime.send_message("Buy 0.1 BTC on paper")
    assert "Paper order placed" in res

    # place_paper_order must be called EXACTLY ONCE
    assert mcp.call_tool.call_count == 1
    mcp.call_tool.assert_called_once_with("place_paper_order", {"side": "BUY", "quantity": 0.1})


def test_25_mcp_permissions_remain_enforced():
    from atsits.mcp.permissions import PermissionLevel, PermissionPolicy, ToolCategory

    policy = PermissionPolicy(permission_level=PermissionLevel.READ_ONLY)
    # READ tools are permitted
    policy.validate_tool_access("get_strategy", ToolCategory.READ)
    # ACTION tools are strictly blocked under READ_ONLY
    with pytest.raises(PermissionError):
        policy.validate_tool_access("run_backtest", ToolCategory.ACTION)



# ---------------------------------------------------------------------
# 7. Web GUI & CLI Integration Tests (26-30)
# ---------------------------------------------------------------------
def test_26_web_api_models_includes_auto_and_health():
    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, mcp_client=mcp)
    app = create_app(gemini_config=cfg, gemini_runtime=runtime, mcp_client=mcp)
    client = TestClient(app)

    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "AUTO"
    assert "health" in data
    assert len(data["models"]) == 5


def test_27_web_api_model_switch_to_auto():
    cfg = GeminiConfig(api_key="mock_key", selection_mode="MANUAL")
    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, mcp_client=mcp)
    app = create_app(gemini_config=cfg, gemini_runtime=runtime, mcp_client=mcp)
    client = TestClient(app)

    with patch("atsits.web.app.persist_gemini_selection_mode") as mock_persist_mode:
        res = client.post("/api/model", json={"model_id": "auto", "persist": True})
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "AUTO"
        assert runtime.selection_mode == "AUTO"
        mock_persist_mode.assert_called_once_with("AUTO")


def test_28_web_api_chat_returns_routing_metadata():
    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    from google.genai import types

    cand = types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Healthy status")]))
    mock_client.generate_content.return_value = types.GenerateContentResponse(candidates=[cand])

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)
    app = create_app(gemini_config=cfg, gemini_runtime=runtime, mcp_client=mcp)
    client = TestClient(app)

    res = client.post("/api/chat", json={"message": "status"})
    assert res.status_code == 200
    data = res.json()
    assert data["response"] == "Healthy status"
    assert "routing" in data
    assert data["routing"]["mode"] == "AUTO"
    assert data["routing"]["task_class"] == "SIMPLE"
    assert data["routing"]["selected_model"] == "gemini-3.1-flash-lite"


def test_29_cli_set_model_auto(capsys):
    from atsits.cli import ATSITSCLI

    cfg = GeminiConfig(api_key=None, selection_mode="MANUAL", model_name="gemini-2.5-flash-lite")
    cli = ATSITSCLI(gemini_config=cfg)
    cli.set_model("auto", persist=False)
    assert cli.gemini_runtime.selection_mode == "AUTO"
    captured = capsys.readouterr().out
    assert "Active Gemini mode set to: ⚡ AUTO" in captured


def test_30_offline_atsits_remains_functional_without_gemini():
    cfg = GeminiConfig(api_key=None)
    runtime = GeminiMCPRuntime(config=cfg)
    assert runtime.is_configured is False
    with pytest.raises(Exception):
        runtime.send_message("hello")


def test_31_legitimate_sequential_teaching_actions_allowed():
    """Verify that multiple state-changing actions with distinct arguments in teaching workflows are allowed."""
    from google.genai import types

    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    mcp.call_tool.side_effect = [
        {"material_id": "mat-001"},
        {"material_id": "mat-002"},
        {"draft_id": "dft-001"},
    ]

    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    # Turn 1: create_teaching_material for Doc 1
    fc1 = types.FunctionCall(name="create_teaching_material", args={"title": "Doc 1", "content": "Text 1"})
    cand1 = types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=fc1)]))
    resp1 = types.GenerateContentResponse(candidates=[cand1])

    # Turn 2: create_teaching_material for Doc 2
    fc2 = types.FunctionCall(name="create_teaching_material", args={"title": "Doc 2", "content": "Text 2"})
    cand2 = types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=fc2)]))
    resp2 = types.GenerateContentResponse(candidates=[cand2])

    # Turn 3: extract_strategy_draft
    fc3 = types.FunctionCall(name="extract_strategy_draft", args={"material_id": "mat-001"})
    cand3 = types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=fc3)]))
    resp3 = types.GenerateContentResponse(candidates=[cand3])

    # Turn 4: Final text response
    cand4 = types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Teaching extraction completed.")]))
    resp4 = types.GenerateContentResponse(candidates=[cand4])

    mock_client.generate_content.side_effect = [resp1, resp2, resp3, resp4]

    res = runtime.send_message("Analyze teaching materials 1 and 2")
    assert "Teaching extraction completed" in res
    assert mcp.call_tool.call_count == 3


def test_32_critical_task_thinking_rejection_no_silent_downgrade():
    """Verify that when a model rejects thinking_config on a CRITICAL task, it does not silently downgrade without reasoning."""
    from google.genai import types

    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    # 3.8 rejects thinking with API error
    thinking_err = GeminiAPIError("Model gemini-3.8-flash does not support thinking_config")
    # 3.7 succeeds with thinking
    cand = types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Strategy verification complete with rigorous reasoning.")]))
    resp_37 = types.GenerateContentResponse(candidates=[cand])

    mock_client.generate_content.side_effect = [thinking_err, resp_37]

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    res = runtime.send_message("Verify strategy consistency before promotion", context={"is_critical": True})
    assert "Strategy verification complete" in res
    # Verified fallback to gemini-3.7-flash
    assert runtime.last_routing_metadata.selected_model == "gemini-3.7-flash"
    assert runtime.last_routing_metadata.fallback_attempt == 1


def test_33_runtime_test_connection_auto_mode_healthy_candidate():
    """Verify runtime.test_connection returns ONLINE in AUTO mode when first candidate is healthy even if default is 429."""
    cfg = GeminiConfig(api_key="mock_key", model_name="gemini-2.5-flash-lite", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    # Client test_connection returns True for gemini-3.1-flash-lite
    def mock_test_conn(model=None):
        if model == "gemini-3.1-flash-lite":
            return (True, "Successfully authenticated with Gemini API (model: Gemini 3.1 Flash Lite)")
        if model == "gemini-2.5-flash-lite":
            return (False, "Gemini 2.5 Flash Lite quota exhausted.")
        return (False, "Unknown model")

    mock_client.test_connection.side_effect = mock_test_conn

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    success, msg, meta = runtime.test_connection()
    assert success is True
    assert meta["status"] == "ONLINE"
    assert meta["model"] == "gemini-3.1-flash-lite"
    assert "Auto Router" in meta["display_name"]


def test_34_runtime_test_connection_all_candidates_exhausted():
    """Verify runtime.test_connection returns QUOTA_EXHAUSTED when all candidate models return 429."""
    cfg = GeminiConfig(api_key="mock_key", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True
    mock_client.test_connection.return_value = (False, "Gemini quota exhausted. Switch model or try later.")

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    success, msg, meta = runtime.test_connection()
    assert success is False
    assert meta["status"] == "QUOTA_EXHAUSTED"


def test_35_runtime_test_connection_manual_mode():
    """Verify runtime.test_connection tests specifically the selected model in MANUAL mode."""
    cfg = GeminiConfig(api_key="mock_key", model_name="gemini-3.8-flash", selection_mode="MANUAL")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True
    mock_client.test_connection.return_value = (True, "Successfully authenticated with Gemini API (model: Gemini 3.8 Flash)")

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    success, msg, meta = runtime.test_connection()
    assert success is True
    assert meta["status"] == "ONLINE"
    assert meta["model"] == "gemini-3.8-flash"
    assert meta["mode"] == "MANUAL"
    mock_client.test_connection.assert_called_with(model="gemini-3.8-flash")


def test_36_api_status_reflects_runtime_router_health():
    """Verify /api/status accurately emits gemini_online, gemini_status, and display name."""
    cfg = GeminiConfig(api_key="mock_key", model_name="gemini-2.5-flash-lite", selection_mode="AUTO")
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.is_configured = True

    def mock_test_conn(model=None):
        if model == "gemini-3.1-flash-lite":
            return (True, "Online")
        return (False, "Quota exhausted")

    mock_client.test_connection.side_effect = mock_test_conn

    mcp = MagicMock(spec=MCPClient)
    mcp.list_tools.return_value = []
    runtime = GeminiMCPRuntime(config=cfg, client=mock_client, mcp_client=mcp)

    app = create_app(gemini_config=cfg, gemini_runtime=runtime, mcp_client=mcp)
    client = TestClient(app)

    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["gemini_online"] is True
    assert data["gemini_status"] == "ONLINE"
    assert data["gemini_model"] == "gemini-3.1-flash-lite"
    assert "Auto Router" in data["gemini_model_display"]


