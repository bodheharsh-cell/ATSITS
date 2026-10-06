# ATSITS PHASE 8.6 — BASIC LOCAL WEB GUI IMPLEMENTATION REPORT

**Date:** 2026-09-23  
**Status:** COMPLETE & VERIFIED  
**Framework:** FastAPI + Uvicorn (Bound strictly to `127.0.0.1:8000`)  
**Historical Baseline Status:** 100% Bit-for-bit Deterministic Match (201 trades, -$306.09, 33.33% Win Rate)  
**Test Suite Status:** 210 / 210 tests passing  

---

## 1. Executive Summary

Phase 8.6 introduces a clean, lightweight, local-only web browser interface for ATSITS. It allows the human operator to interact with all ATSITS features (Chat, Strategy Teaching & Human Review, Strategy Inspection, Deterministic Backtesting, Trade Journal, and Research Experiments) directly via a local web browser at `http://127.0.0.1:8000`.

---

## 2. Framework Chosen & Architecture

### Framework
- **Backend:** FastAPI (Python lightweight ASGI framework with strict Pydantic v2 schemas).
- **Server:** Uvicorn ASGI server configured to bind strictly to `127.0.0.1`.
- **Frontend:** Vanilla HTML5, CSS3, and JavaScript (single-page application, zero external JS frameworks, zero cloud dependencies).

### Architecture Flow
```
+-----------------------------------------------------------------------------------+
|                           BROWSER (Localhost Only)                                |
|   http://127.0.0.1:8000 (Single-Page UI with 6 Navigation Tabs)                   |
+-----------------------------------------------------------------------------------+
                                         │
                                (Local HTTP/JSON)
                                         ▼
+-----------------------------------------------------------------------------------+
|                        ATSITS WEB BACKEND (FastAPI)                               |
|   - Strictly bound to 127.0.0.1                                                   |
|   - API Key never transmitted or returned                                        |
|   - In-memory conversation state (no disk storage/telemetry)                      |
|   - Strict request validation & backtest boundary                                 |
+-----------------------------------------------------------------------------------+
       │                                     │
(Deterministic Engine Calls)         (Gemini MCP Runtime)
       ▼                                     ▼
+------------------------------+     +-------------------------------+
|  DETERMINISTIC ATSITS CORE   |     |      GEMINI RUNTIME           |
|  - BacktestEngine            |     |  - GeminiMCPRuntime           |
|  - TradingJournal            |     |  - MCP Tool Calling Loop      |
|  - StrategyExtractor         |     +-------------------------------+
|  - HumanReviewEngine         |                     │
|  - ExperimentRegistry        |                     ▼
+------------------------------+     +-------------------------------+
                                     |       ATSITS MCP SERVER       |
                                     |  - 19 Controlled Tools        |
                                     |  - Permission: RESEARCH       |
                                     +-------------------------------+
```

---

## 3. UI Structure & Features

The interface consists of a single responsive dark-themed page divided into:

### 1. Top Header & Status Bar
- Live status indicators:
  - `Gemini ● Connected (<model>)` or `Gemini ● Offline`
  - `MCP Ready (19 tools)`
  - `ATSITS Engine Ready`

### 2. Tab: 💬 Chat
- Conversational chat interface interacting with `GeminiMCPRuntime`.
- Real-time MCP visibility: Expandable `🔍 MCP Tool Invocations (N)` dropdown under each assistant response displaying exact tool names, arguments, and outcomes (`get_strategy`, `get_performance_metrics`, etc.).
- Reset Button: Clears in-memory conversation history.

### 3. Tab: 🎓 Teach (Human Review Gate Enforced)
- Paste unstructured strategy notes or text.
- Step 1: Ingests into `TeachingRegistry` and extracts structured `DraftStrategy`.
- Step 2: Displays extracted rules, indicators, certainty levels, missing parameters, and conflicts.
- Step 3: **Mandatory Human Operator Review Gate**:
  - `[Approve All Rules]`: Human operator accepts extracted rules into review lineage.
  - `[Save Clarifications]`: Allows providing values for missing items (e.g. instrument, timeframes).
  - `[Reject Draft]`: Marks draft as rejected.
  - `[Verify Strategy Gate]`: Invokes `HumanReviewEngine.verify_draft()` to evaluate executability and seal verified specification.

### 4. Tab: 📈 Strategy
- Displays Production Strategy (`EMA_Pullback_v1.0` [PRODUCTION LOCKED]) with parameters (`fast_period: 20`, `slow_period: 50`, `stop_loss: Swing Low`, `take_profit: 2.0R`).
- Displays list of verified strategies and pending draft revisions.

### 5. Tab: 📊 Backtest
- Simple form with Strategy selector (locked to registered deterministic strategies), Symbol (`BTCUSDT`), and Initial Equity ($).
- Executes deterministic `BacktestEngine` with zero costs baseline and displays complete results card matching historical baseline (201 trades, -$306.09, 33.33% Win Rate).

### 6. Tab: 📖 Journal
- Interactive table displaying all recorded trade logs: Trade ID, Entry Time, Exit Time, Direction, Entry Price, Exit Price, Net P&L ($), and Exit Reason.

### 7. Tab: 🔬 Experiments
- Overview of research hypotheses and experiment records from `ExperimentRegistry` with in-sample/out-of-sample validation status.

---

## 4. Security & Safety Commitments

1. **Localhost Isolation:** Server binds strictly to `127.0.0.1` and explicitly rejects external LAN/0.0.0.0 bindings.
2. **Zero API Key Leakage:** `GEMINI_API_KEY` remains server-side only. It is **NEVER** returned in any API JSON response, HTML attribute, error payload, or log. An automated test (`test_api_key_leak_prevention_audit`) scans all endpoints to enforce this invariant.
3. **In-Memory Chat Only:** Chat history is maintained strictly in memory during the active session. No conversations are written to disk, database, or telemetry. Resetting chat clears memory immediately.
4. **Strict Backtest Boundary:** `/api/backtest` accepts only supported strategy names (`EMA_Pullback_v1.0`). Arbitrary module/function/code execution is rejected with HTTP 400.
5. **Preserved Human Authority:** The GUI does not auto-approve or auto-promote strategies. Only explicit human review actions (`APPROVE`, `CLARIFY`, `REJECT`, `VERIFY`) via `HumanReviewEngine` are permitted.

---

## 5. Verification & Test Results

### 1. Automated Test Suite
```bash
python -m pytest -v
```
**Results:** **210 / 210 passed** (198 existing tests + 12 new web API/security tests).

### 2. Historical Baseline Regression
```bash
python scripts/run_validation_report.py
```
**Results:** **100% Bit-for-bit exact match**
- Total Trades: 201 (100 Long / 101 Short)
- Win Rate: 33.33% (67 Wins / 134 Losses)
- Total Net P&L: -$306.09 (-3.06%)
- Profit Factor: 0.98 | Max Drawdown: 13.80%

### 3. Live Server Smoke Test
- Verified live on `http://127.0.0.1:8000`:
  - `GET /` -> 200 OK (HTML UI loaded)
  - `GET /api/status` -> 200 OK (Clean status, no API key present)
  - `POST /api/chat` -> 200 OK (Real-time MCP tool execution captured)
  - `POST /api/chat/reset` -> 200 OK (Memory reset)
  - `POST /api/backtest` -> 200 OK (Exact 201 trades, -$306.09)
  - `POST /api/teach/extract` -> 200 OK (Draft extracted)
  - `POST /api/teach/review` -> 200 OK (Human review gate executed)

---

## 6. Files Changed & Created

| File | Status | Description |
|---|---|---|
| `src/atsits/web/__init__.py` | NEW | Web package exports. |
| `src/atsits/web/app.py` | NEW | FastAPI application with REST endpoints. |
| `src/atsits/web/server.py` | NEW | Uvicorn server runner enforcing `127.0.0.1` binding. |
| `src/atsits/web/templates/index.html` | NEW | Single-page UI template (Chat, Teach, Strategy, Backtest, Journal, Experiments). |
| `src/atsits/cli.py` | MODIFIED | Added `web` subcommand (`atsits web --port 8000`). |
| `pyproject.toml` | MODIFIED | Added `fastapi>=0.100.0` and `uvicorn>=0.20.0` dependencies. |
| `tests/test_web.py` | NEW | Automated test suite for all web routes, boundary checks, and API key leak audit. |
| `ATSITS_GUI_IMPLEMENTATION_REPORT.md` | NEW | Complete implementation documentation. |

---

## 7. Known Limitations

- **Single-User Local Desktop Use:** Designed for a single operator interacting locally on the machine. Not designed for multi-tenant deployments.
- **In-Memory Chat:** Refreshing the browser or restarting the server resets the active chat session.

---

## 8. Command to Launch the GUI

To start the ATSITS Local Web GUI, run:

```bash
python -m atsits web
```

Then open your web browser and navigate to:

```
http://127.0.0.1:8000
```
