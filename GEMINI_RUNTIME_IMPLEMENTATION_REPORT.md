# ATSITS PHASE 8.5 — GEMINI RUNTIME + ATSITS CLI IMPLEMENTATION REPORT

**Date:** 2026-09-22  
**Status:** COMPLETE & VERIFIED  
**SDK:** Google GenAI Python SDK (`google-genai>=2.0.0`, currently v2.25.0)  
**Historical Baseline Status:** 100% Bit-for-bit Deterministic Match (201 trades, -$306.09, 33.33% Win Rate)  
**Test Suite Status:** 198 / 198 tests passing  

---

## 1. Executive Summary

Phase 8.5 introduces the complete user-facing interactive runtime for ATSITS, connecting:
$$\text{Human Operator} \longleftrightarrow \text{ATSITS Interactive CLI} \longleftrightarrow \text{Gemini API (Official SDK)} \longleftrightarrow \text{ATSITS MCP Server} \longleftrightarrow \text{Deterministic Engines}$$

### Key Architectural Commitments Enforced:
1. **Human Operator is Supreme:** Only a genuine named human operator in a direct CLI session can verify or approve strategy drafts. Gemini has zero strategy verification or promotion authority.
2. **Current Official Google GenAI SDK:** Uses Google's official `google-genai` SDK (`google_genai>=2.0.0`) exclusively. Deprecated `google-generativeai` is never imported.
3. **API Key Security & Privacy:** API keys are read securely from `GEMINI_API_KEY` environment variable or `.env` file. Keys are masked in memory, logs, outputs, and representations (`AIza...6789`). Error strings are sanitized to redact any accidental key leakage.
4. **Offline Resilience:** All deterministic ATSITS components (`status`, `backtest`, `journal`, `experiments`, `strategy`, `teach`) operate completely offline without requiring a Gemini API key or internet connection.
5. **No Live Trading / Mutation:** Broker integration, live order routing, and autonomous parameter mutation remain strictly forbidden.

---

## 2. Architecture & Component Flow

```
+-----------------------------------------------------------------------------------+
|                                 HUMAN OPERATOR                                    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                             ATSITS INTERACTIVE CLI                                |
|  - CLI Commands: status, backtest, journal, experiments, strategy, teach, chat    |
|  - Slash Commands: /status, /backtest, /journal, /experiments, /strategy, /exit   |
|  - Interactive Strategy Teaching Review UX: [A] Approve [C] Clarify [V] Verify    |
+-----------------------------------------------------------------------------------+
               |                                                   |
      (Offline / Direct)                                   (Gemini Reasoning)
               |                                                   |
               v                                                   v
+-----------------------------+                  +----------------------------------+
|    DETERMINISTIC ENGINES    |                  |          GEMINI RUNTIME          |
|  - BacktestEngine           |                  |  - Config & Secret Masker        |
|  - TradingJournal           |                  |  - GeminiClient (google-genai)   |
|  - StrategyExtractor        |                  |  - GeminiMCPRuntime Loop         |
|  - HumanReviewEngine        |                  |  - ATSITS System Instructions    |
+-----------------------------+                  +----------------------------------+
               ^                                                   |
               |                                                   v
               |                                 +----------------------------------+
               +---------------------------------|         ATSITS MCP SERVER        |
                   (JSON-RPC 2.0 In-Process)     |  - 19 Controlled MCP Tools       |
                                                 |  - PermissionPolicy (RESEARCH)   |
                                                 |  - Audit Lineage Logger          |
                                                 +----------------------------------+
```

---

## 3. Official `google-genai` SDK Integration

ATSITS Phase 8.5 standardizes on Google's official `google-genai` SDK:
- **Package:** `google-genai` (v2.25.0 installed and declared in `pyproject.toml`).
- **Client Instantiation:** `genai.Client(api_key=...)`.
- **Config & Schema:** `types.GenerateContentConfig` with `types.Tool` wrapping `types.FunctionDeclaration(name=..., description=..., parameters_json_schema=...)`.
- **Function Response Protocol:** `types.Part.from_function_response(name=..., response={"result": ...})`.
- **Multi-Turn Interaction Loop:** Multi-turn tool execution loop in `GeminiMCPRuntime.send_message()`.

---

## 4. API Key Security & Secret Masking

1. **Config Loader (`atsits.gemini.config`):**
   - Resolves API key in priority order: CLI argument $\to$ Environment variable $\to$ `.env` file $\to$ `None`.
   - `.env` file is safely loaded without external dependencies and ignored by `.gitignore`.
2. **Secret Masking:**
   - Keys are masked everywhere: `_mask_secret()` formats `AIzaSyD-123456789-abcdef` as `AIza...cdef`.
   - `GeminiConfig.__repr__()` and `GeminiConfig.__str__()` always print masked keys.
3. **Error Message Sanitization:**
   - `_sanitize_error_message()` intercepts any SDK exceptions containing raw keys and replaces them with `[REDACTED_API_KEY]`.

---

## 5. ATSITS Interactive CLI & REPL Commands

### 1. `status`
Displays system health, historical dataset facts, production strategy state (`EMA_Pullback_v1.0` [PRODUCTION LOCKED]), teaching pipeline counts, journal counts, active MCP tools (19 tools), and Gemini connection status.

### 2. `backtest [--strategy STRAT] [--equity AMOUNT]`
Runs deterministic backtest on historical OHLCV data (`data/btcusdt_1h.csv`) and prints complete performance statistics matching baseline.

### 3. `journal [--limit N]`
Displays recent trade records, timestamps, directions, entry/exit prices, and net P&L.

### 4. `experiments`
Lists registered hypothesis and experiment records from `ExperimentRegistry`.

### 5. `strategy {list, show, verify}`
- `strategy list`: Lists production baseline, verified strategies, and pending drafts.
- `strategy show <id>`: Displays comprehensive rule, missing information, and ambiguity breakdown.
- `strategy verify <draft_id>`: Executes the mandatory Human Verification Gate as a named human operator.

### 6. `teach [--file FILE] [--text "STRATEGY TEXT"]`
Interactive 5-step teaching workflow:
1. Ingests source teaching material.
2. Runs deterministic `StrategyExtractor`.
3. Displays extracted rules, indicators, ambiguities, missing information, and conflicts.
4. Consults Gemini reasoning layer for semantic analysis and recommendations (if configured).
5. Enters interactive Human Operator Review Gate:
   - `[A] Approve Rules`: Human operator accepts extracted rules into review lineage.
   - `[C] Clarify / Correct`: Human operator provides values for missing parameters or rule overrides.
   - `[R] Reject Draft`: Discards draft.
   - `[S] Skip`: Preserves draft in registry for later review.
   - `[V] Verify Draft`: Runs formal verification gate for execution readiness.

### 7. `chat [PROMPT]`
Multi-turn conversational chat with Gemini and ATSITS MCP tools. Autonomously queries platform data via MCP tools in real-time.

---

## 6. Verification & Test Suite

### Full Automated Test Suite
```bash
python -m pytest -v
```
**Results:** **198 / 198 passed** (0 failures, 1 deprecation warning from SDK).

### Historical Baseline Regression Audit
```bash
python scripts/run_validation_report.py
```
**Results:**
- **Total Trades:** 201
- **Winning Trades:** 67 | **Losing Trades:** 134
- **Win Rate:** 33.33%
- **Total Net P&L:** -$306.09 (-3.06%)
- **Profit Factor:** 0.98
- **Max Drawdown:** $1,448.11 (13.80%)
- **Bit-for-bit Determinism:** 100% PASSED

---

## 7. File Manifest of Phase 8.5 Changes

| File | Status | Description |
|---|---|---|
| `src/atsits/gemini/__init__.py` | NEW | Public package exports for Gemini runtime. |
| `src/atsits/gemini/config.py` | NEW | Gemini configuration, secret masking, and dotenv loader. |
| `src/atsits/gemini/exceptions.py` | NEW | Domain exceptions for Gemini runtime and auth. |
| `src/atsits/gemini/prompts.py` | NEW | System instruction prompts with authority constraints. |
| `src/atsits/gemini/client.py` | NEW | Safe client wrapper around official `google-genai` SDK. |
| `src/atsits/gemini/runtime.py` | NEW | Multi-turn MCP tool execution and reasoning coordinator. |
| `src/atsits/cli.py` | NEW | Interactive CLI, REPL, subcommands, and human review UX. |
| `src/atsits/__main__.py` | NEW | CLI entrypoint for `python -m atsits`. |
| `pyproject.toml` | UPDATED | Added `google-genai>=2.0.0` dependency and `atsits` script. |
| `tests/test_gemini_runtime.py` | NEW | Automated unit tests for Gemini config, client, and runtime. |
| `tests/test_cli.py` | NEW | Automated functional tests for CLI and review UX. |
| `GEMINI_RUNTIME_IMPLEMENTATION_REPORT.md` | NEW | Comprehensive Phase 8.5 architecture and implementation report. |

---

## 8. Conclusion

ATSITS Phase 8.5 is **COMPLETE, TESTED, AND VERIFIED**. The human operator has full interactive control via the CLI with deterministic offline execution and Gemini reasoning integration.
