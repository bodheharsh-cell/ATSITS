# EXPERIMENTAL STRATEGY HISTORICAL VALIDATION REPORT
**Pre-Phase 9 Controlled Experimentation**

**Date**: 2026-09-24  
**Dataset**: BTCUSDT 1H (8,760 candles, 2025-09-21T07:00:00Z to 2026-09-21T06:00:00Z)  
**Status**: HISTORICALLY VALIDATED (EXPERIMENTAL ONLY - NOT PROMOTED TO PRODUCTION)  
**Test Suite Status**: 232 passed, 0 failed  

---

## 1. Executive Summary & Objective

Prior to commencing Phase 9, a controlled parameter adjustment was made strictly to the **separate experimental strategy**:
- **Fast EMA**: 20
- **Slow EMA**: 30
- **Take Profit (TP)**: 3.0R
- **Risk per trade**: 1%

All other strategy rules, execution mechanics, risk models, slippage/fee assumptions, and determinism invariants remain identical to the core system.

The **production strategy (`EMA_Pullback_v1.0`) remains locked and unchanged**.

---

## 2. Strategy Specifications & Parameters

### Locked Production Strategy (`EMA_Pullback_v1.0`)
- **Identifier / Version**: `1.0.0` (`EMA_Pullback_v1.0`)
- **Fast EMA**: 20
- **Slow EMA**: 50
- **Take Profit**: 2.0R
- **Stop Loss**: Pullback candle extreme (Low for Long, High for Short)
- **Risk Model**: 1.0% initial equity risk per trade
- **Status**: **PRODUCTION LOCKED**

### Experimental Strategy (`EMA_Pullback_EMA20_30_3R`)
- **Identifier / Version**: `EMA_Pullback_EMA20_30_3R` (`EMAExperimentalStrategy`)
- **Fast EMA**: 20
- **Slow EMA**: 30
- **Take Profit**: 3.0R
- **Stop Loss**: Pullback candle extreme (Low for Long, High for Short)
- **Risk Model**: 1.0% initial equity risk per trade
- **Status**: **EXPERIMENTAL (RESEARCH ONLY)**

---

## 3. Backtest Assumptions & Dataset

- **Symbol**: BTCUSDT
- **Timeframe**: 1h
- **Candle Count**: 8,760 completed hourly candles
- **Period**: 2025-09-21T07:00:00Z through 2026-09-21T06:00:00Z
- **Initial Equity**: \$10,000.00
- **Execution Rules**:
  - Completed candle decisions only
  - Entry on next bar OPEN
  - Single open position per symbol
  - No pyramiding or immediate reversal
  - Ambiguity resolution: SL takes precedence if both SL and TP are touched in the same bar
  - Cost Model: Slippage = 0.0 pts / 0.0%, Commission = 0.0% (standard unassisted baseline mode)

---

## 4. Complete Historical Results & Comparison

| Performance Metric | Locked Baseline (`EMA20/50 + 2R`) | Experimental Strategy (`EMA20/30 + 3R`) | Delta / Observation |
|---|---|---|---|
| **Strategy Version** | `1.0.0` (`EMA_Pullback_v1.0`) | `EMA_Pullback_EMA20_30_3R` | Experimental branch |
| **Indicator Configuration** | EMA 20 / EMA 50 | EMA 20 / EMA 30 | Faster trend filter |
| **Target Multiple** | 2.0R | 3.0R | Higher reward target |
| **Total Trades** | **201** | **200** | -1 trade |
| **Long Trades** | 100 | 103 | +3 trades |
| **Short Trades** | 101 | 97 | -4 trades |
| **Winning Trades** | 67 | 55 | -12 winners |
| **Losing Trades** | 134 | 145 | +11 losers |
| **Win Rate** | **33.33%** | **27.50%** | -5.83% |
| **Gross Profit** | \$12,952.23 | \$17,122.37 | +\$4,170.14 |
| **Gross Loss** | \$13,258.32 | \$15,532.33 | +\$2,274.01 |
| **Total Net P&L** | **-\$306.09 (-3.06%)** | **+\$1,590.04 (+15.90%)** | +\$1,896.13 |
| **Profit Factor** | **0.98** | **1.10** | +0.12 |
| **Maximum Drawdown** | **\$1,448.11 (13.80%)** | **\$2,888.42 (23.99%)** | +\$1,440.31 (+10.19%) |
| **Average Trade P&L** | -\$1.52 | +\$7.95 | +\$9.47 |
| **Take Profit (TP) Exits** | 66 | 54 | -12 exits |
| **Stop Loss (SL) Exits** | 134 | 145 | +11 exits |
| **End of Data (EOD) Exits** | 1 | 1 | 0 |
| **Rejected Setups** | 0 | 0 | 0 |

*(Note: In accordance with governance constraints, neither strategy is ranked or declared a winner. Results are observed strictly as empirical observations of parameter variation).*

---

## 5. Deterministic Verification & Invariants

1. **Indicator Period Validation**:
   - `EMAExperimentalStrategy` initializes and computes with EMA20 fast period and EMA30 slow period.
2. **Take Profit Validation**:
   - Target price calculated exactly as `Entry + (3.0 * (Entry - Stop))` for Longs and `Entry - (3.0 * (Stop - Entry))` for Shorts.
3. **Stop Loss Preservation**:
   - Stop Loss levels remain anchored to the qualifying pullback candle extreme.
4. **Position Sizing**:
   - Strictly computed as `(Equity * 0.01) / abs(Entry - Stop)`.
5. **No Lookahead Bias**:
   - Setup detection occurs on completed confirmation bar; entry executed on next bar open.
6. **Bit-for-Bit Determinism**:
   - Executing the experimental backtest multiple times on the historical dataset produces identical metrics and trade lists.
7. **Locked Production Baseline Preservation**:
   - `EMAPullbackStrategy` reproduces the exact 201 trades, -\$306.09 Net PnL, 33.33% Win Rate.

---

## 6. Safety & Promotion Status

- **Live Trading Connection**: **DISABLED** (No Binance / Broker connection initialized)
- **Live Paper Trading**: **NOT STARTED**
- **Strategy Promotion**: **NONE** (`EMA_Pullback_v1.0` remains the sole production-locked strategy)
- **Test Suite**: **232 tests passing**
- **Readiness for Phase 9**: Fully verified, zero blocking issues.
