# ATSITS Experiment Report: EXP-2026-001

## 1. Experiment Overview
- **Experiment ID**: `EXP-2026-001`
- **Hypothesis ID**: `HYP-EMA-FAST-22`
- **Hypothesis Description**: Testing whether increasing fast EMA period from 20 to 22 improves out-of-sample trend pullbacks on BTCUSDT 1H.
- **Baseline Strategy**: `1.0.0`
- **Candidate Strategy**: `1.0.1-candidate-ema22`
- **Candidate Parameter Changes**: `{'fast_period': 22, 'slow_period': 50}`
- **Dataset ID**: `btcusdt_1h_8760` (8760 total candles)
- **In-Sample Period**: 2025-09-21T07:00:00+00:00 to 2026-06-03T18:00:00+00:00 (6132 candles)
- **Out-of-Sample Period**: 2026-06-03T19:00:00+00:00 to 2026-09-21T06:00:00+00:00 (2628 candles)
- **Execution Timestamp**: 2026-09-21T21:14:43.542791+00:00

---

## 2. Out-of-Sample Performance Comparison

| Metric | Baseline (1.0.0) | Candidate (1.0.1-candidate-ema22) | Absolute Diff | Relative Diff (%) |
| :--- | :--- | :--- | :--- | :--- |
| `total_trades` | 52.00 | 54.00 | +2.00 | N/A |
| `win_rate` | 0.31 | 0.24 | -0.07 | N/A |
| `net_pnl` | -545.45 | -1527.40 | -981.96 | -180.03% |
| `profit_factor` | 0.84 | 0.58 | -0.26 | -30.84% |
| `expectancy_r` | -0.10 | -0.30 | -0.20 | N/A |
| `max_drawdown` | 1377.80 | 1917.19 | +539.39 | +39.15% |
| `max_drawdown_pct` | 0.13 | 0.19 | +0.06 | N/A |
| `average_trade_pnl` | -10.49 | -28.29 | -17.80 | -169.66% |

---

## 3. Detailed In-Sample Metrics

### In-Sample Baseline
| Metric | Value |
| :--- | :--- |
| **Sample Size (Trades)** | 148 |
| **Long Trades** | 68 |
| **Short Trades** | 80 |
| **Winning Trades** | 50 |
| **Losing Trades** | 98 |
| **Win Rate** | 33.78% |
| **Gross Profit** | $9,767.43 |
| **Gross Loss** | $9,715.31 |
| **Net P&L** | $52.12 |
| **Profit Factor** | 1.01 |
| **Average Trade P&L** | $0.35 |
| **Average Winner** | $195.35 |
| **Average Loser** | $-99.14 |
| **Max Drawdown** | $1,448.11 (13.80%) |
| **SL Exits / TP Exits / EOD** | 98 / 50 / 0 |
| **Total Realized R** | 2.00R |
| **Average R** | 0.014R |
| **Expectancy in R** | 0.014R |

### In-Sample Candidate
| Metric | Value |
| :--- | :--- |
| **Sample Size (Trades)** | 135 |
| **Long Trades** | 59 |
| **Short Trades** | 76 |
| **Winning Trades** | 43 |
| **Losing Trades** | 92 |
| **Win Rate** | 31.85% |
| **Gross Profit** | $8,596.52 |
| **Gross Loss** | $9,301.61 |
| **Net P&L** | $-705.09 |
| **Profit Factor** | 0.92 |
| **Average Trade P&L** | $-5.22 |
| **Average Winner** | $199.92 |
| **Average Loser** | $-101.10 |
| **Max Drawdown** | $2,024.87 (18.48%) |
| **SL Exits / TP Exits / EOD** | 92 / 43 / 0 |
| **Total Realized R** | -6.00R |
| **Average R** | -0.044R |
| **Expectancy in R** | -0.044R |

---

## 4. Detailed Out-of-Sample Metrics

### Out-of-Sample Baseline
| Metric | Value |
| :--- | :--- |
| **Sample Size (Trades)** | 52 |
| **Long Trades** | 32 |
| **Short Trades** | 20 |
| **Winning Trades** | 16 |
| **Losing Trades** | 36 |
| **Win Rate** | 30.77% |
| **Gross Profit** | $2,910.08 |
| **Gross Loss** | $3,455.53 |
| **Net P&L** | $-545.45 |
| **Profit Factor** | 0.84 |
| **Average Trade P&L** | $-10.49 |
| **Average Winner** | $181.88 |
| **Average Loser** | $-95.99 |
| **Max Drawdown** | $1,377.80 (13.25%) |
| **SL Exits / TP Exits / EOD** | 36 / 15 / 1 |
| **Total Realized R** | -5.13R |
| **Average R** | -0.099R |
| **Expectancy in R** | -0.099R |

### Out-of-Sample Candidate
| Metric | Value |
| :--- | :--- |
| **Sample Size (Trades)** | 54 |
| **Long Trades** | 28 |
| **Short Trades** | 26 |
| **Winning Trades** | 13 |
| **Losing Trades** | 41 |
| **Win Rate** | 24.07% |
| **Gross Profit** | $2,130.32 |
| **Gross Loss** | $3,657.72 |
| **Net P&L** | $-1,527.40 |
| **Profit Factor** | 0.58 |
| **Average Trade P&L** | $-28.29 |
| **Average Winner** | $163.87 |
| **Average Loser** | $-89.21 |
| **Max Drawdown** | $1,917.19 (19.17%) |
| **SL Exits / TP Exits / EOD** | 41 / 12 / 1 |
| **Total Realized R** | -16.13R |
| **Average R** | -0.299R |
| **Expectancy in R** | -0.299R |

---

## 5. Validation Summary
- **Validation Status**: NOT PASSED
- **Validation Detail**: IS Net PnL: Candidate=-705.09 vs Baseline=52.12 | OOS Net PnL: Candidate=-1527.40 vs Baseline=-545.45 | OOS Expectancy R: Candidate=-0.299R vs Baseline=-0.099R | OOS Sample Size: 54 trades

---

## 6. Neutral Factual Interpretation
- Candidate strategy `1.0.1-candidate-ema22` produced an Out-of-Sample Net P&L of $-1,527.40 (vs Baseline $-545.45) across 54 trades.
- Out-of-Sample Profit Factor: Candidate 0.58 vs Baseline 0.84.
- Out-of-Sample Expectancy: Candidate -0.299R vs Baseline -0.099R.
- *Notice: Phase 5 does not autonomously promote or deploy strategies. Human review and approval remain mandatory.*
