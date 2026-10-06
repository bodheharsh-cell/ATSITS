# PHASE 8.7 — GEMINI MODEL SELECTION & RUNTIME CONFIGURATION REPORT

**Date**: 2026-09-23  
**Status**: COMPLETE & VERIFIED  
**Test Suite**: 226 passed, 0 failed  
**Historical Regression**: 201 trades, -$306.09 Net PnL, 33.33% Win Rate (Exact Bit-for-Bit Preservation)

---

## 1. Executive Summary

Phase 8.7 adds dynamic Gemini model selection and runtime configuration to ATSITS across the Web GUI, REST API, Interactive CLI, and Python runtime.

### Key Capabilities Delivered
1. **Curated Model Whitelist**: Built-in support for 5 Google Gemini text & function-calling models with human-readable display names.
2. **Dynamic Runtime Switching**: Seamless in-memory model switching via `GeminiMCPRuntime.set_model()` without restart or conversation drops.
3. **Safe Persistence**: Optional model selection persistence to `.env` (`persist_gemini_model`) without exposing, modifying, or corrupting `GEMINI_API_KEY`.
4. **Web GUI Model Selector**: Interactive dropdown in header status bar that populates available models, tracks active model, switches active model on change, and informs the operator.
5. **Quota Error Handling (HTTP 429 / RESOURCE_EXHAUSTED)**: Immediate detection and translation of quota limits into clear, actionable notifications recommending model switching without retry loops or API key leakage.
6. **CLI & REPL Integration**: Multi-command support via `--model` / `-m` flags on `chat`, `teach`, and `status`, plus `model [model_id]` command in interactive REPL.

---

## 2. Supported Model Whitelist

The system strictly supports the following text/reasoning & tool-calling models (Gemini Live models are strictly excluded per architectural constraints):

| Model ID | Human-Readable Display Name | Role / Description | Whitelist Default |
|---|---|---|:---:|
| `gemini-2.5-flash-lite` | Gemini 2.5 Flash Lite | High-speed, lightweight model for fast reasoning & MCP tools | **Yes (Default)** |
| `gemini-3.1-flash-lite` | Gemini 3.1 Flash Lite | Next-generation efficient flash model with function calling | No |
| `gemini-3.6-flash` | Gemini 3.6 Flash | Balanced speed and reasoning for multi-turn tool interaction | No |
| `gemini-3.7-flash` | Gemini 3.7 Flash | Advanced reasoning model with deep analysis capabilities | No |
| `gemini-3.8-flash` | Gemini 3.8 Flash | Latest high-capacity flagship flash model for quantitative research | No |

---

## 3. Architecture & API Layer

### REST API Endpoints
- `GET /api/models`
  - Returns array of supported model info objects and active model ID:
  ```json
  {
    "models": [
      {
        "model_id": "gemini-2.5-flash-lite",
        "display_name": "Gemini 2.5 Flash Lite",
        "description": "High-speed, lightweight model for fast reasoning & MCP tools",
        "is_default": true
      },
      ...
    ],
    "active_model_id": "gemini-2.5-flash-lite",
    "active_display_name": "Gemini 2.5 Flash Lite"
  }
  ```
- `POST /api/model`
  - Validates requested `model_id` against whitelist and updates runtime:
  ```json
  { "model_id": "gemini-3.7-flash", "persist": true }
  ```
  - Response:
  ```json
  {
    "success": true,
    "status": "ok",
    "model_id": "gemini-3.7-flash",
    "display_name": "Gemini 3.7 Flash",
    "message": "Active Gemini model switched to Gemini 3.7 Flash."
  }
  ```
- `GET /api/status`
  - Returns `gemini_model` and `gemini_model_display` metadata alongside engine and MCP status. Never exposes API keys.

---

## 4. Quota Exhaustion (429) & Error Boundary

When Gemini encounters API rate limits or quota exhaustion:
1. `GeminiClient` intercepts HTTP 429 / `RESOURCE_EXHAUSTED` responses and raises `GeminiQuotaExceededError`.
2. The error message cleanly formats: `"<Model Display Name> quota exhausted. Switch to another available model or try again later."`
3. In Web GUI, `/api/chat` returns structured error `QUOTA_EXHAUSTED` with advice to select another model from the header dropdown.
4. No automated blind retry loops are executed (preserving quota and preventing hangs).
5. All secrets and keys are redacted and never returned to the UI or client.

---

## 5. CLI & REPL Usage

### CLI Commands
```bash
# Check status and see supported models
python -m atsits status

# Probe Gemini connection with a specific model
python -m atsits status --model gemini-3.7-flash

# Launch Chat with a specific model
python -m atsits chat --model gemini-3.8-flash "Analyze 1H BTC volatility"

# Launch Strategy Teaching Pipeline with a specific model
python -m atsits teach -m gemini-3.6-flash --text "Enter long on 20 EMA pullback"

# Launch Web GUI
python -m atsits web --port 8000
```

### Interactive REPL Commands
```
atsits> model
Current Gemini Model: Gemini 2.5 Flash Lite (gemini-2.5-flash-lite)
Supported Models:
  [*] gemini-2.5-flash-lite        - Gemini 2.5 Flash Lite
  [ ] gemini-3.1-flash-lite        - Gemini 3.1 Flash Lite
  [ ] gemini-3.6-flash             - Gemini 3.6 Flash
  [ ] gemini-3.7-flash             - Gemini 3.7 Flash
  [ ] gemini-3.8-flash             - Gemini 3.8 Flash

atsits> model gemini-3.7-flash
Active Gemini model set to: Gemini 3.7 Flash (gemini-3.7-flash)
Configuration saved to .env
```

---

## 6. Verification & Regression Audit

1. **Automated Test Suite**:
   - Total tests: **226 passed**
   - New dedicated test module: `tests/test_model_selection.py` (16 tests verifying registry, validation, persistence, API routes, quota error handling, and CLI flags).
2. **Historical Backtest Validation**:
   - Total Trades: **201**
   - Winning Trades: **67** (33.33%)
   - Net PnL: **$-306.09**
   - Profit Factor: **0.98**
   - Max Drawdown: **$1,448.11 (13.80%)**
   - **Bit-for-bit identical with locked baseline**.
3. **Safety & Authority Invariant**:
   - Human authority remains supreme.
   - Deterministic execution engine unmodified.
   - API keys remain strictly local and masked.
