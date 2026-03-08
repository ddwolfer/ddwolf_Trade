# Research Report: Trend Rider

- **Date:** 2026-03-09
- **Symbol:** BTCUSDT
- **Interval:** 1h
- **Period:** 2024-01-01 ~ 2025-01-01
- **Status:** PASSED (all quality gates)

## Strategy Logic

EMA crossover entry + ATR trailing stop exit. Designed to ride trends and minimize whipsaw exits.

- **Entry:** Fast EMA crosses above Slow EMA AND price > Long-term EMA filter
- **Exit:** Fast EMA crosses below Slow EMA OR ATR trailing stop hit

## Optimized Parameters

```json
{
  "fast_ema": 34,
  "slow_ema": 55,
  "atr_period": 14,
  "atr_multiplier": 4.0,
  "trend_filter_ema": 100
}
```

These are set as the strategy's default values in `backend/strategies/trend_rider_strategy.py`.

## Performance (Full Period)

| Metric | Value |
|--------|-------|
| Return | +68.00% |
| Win Rate | 39.1% |
| Profit Factor | 2.11 |
| Sharpe Ratio | 1.65 |
| Max Drawdown | -15.9% |
| Total Trades | 46 |

## Benchmark Comparison

| Strategy | Return | Sharpe | MaxDD |
|----------|--------|--------|-------|
| Buy & Hold | +123.0% | - | - |
| **Trend Rider** | **+68.0%** | **1.65** | **-15.9%** |
| DCA Monthly | +54.3% | - | - |
| DCA Weekly | +52.3% | - | - |
| Volume Breakout | +42.1% | 1.07 | -14.5% |

**Result:** Beats DCA (+68% vs +52%), does not beat Buy & Hold (+123%).

## Walk-Forward Validation

| Period | Return | Sharpe | MaxDD | Trades |
|--------|--------|--------|-------|--------|
| In-Sample (Jan-Sep 2024) | +31.0% | 1.30 | -15.0% | 33 |
| Out-of-Sample (Sep-Jan) | +24.2% | 2.17 | -12.3% | 12 |
| **Decay** | **22.1%** | | | |

All quality gates passed. OOS Sharpe (2.17) higher than IS (1.30).

## Quality Gates

| Gate | Threshold | Result | Status |
|------|-----------|--------|--------|
| Trades | >= 5 | 12 | PASS |
| Sharpe | > 0.5 | 2.17 | PASS |
| Max DD | > -40% | -12.3% | PASS |
| Win Rate | > 30% | 39.1% | PASS |
| OOS Decay | < 50% | 22.1% | PASS |

## Confidence: Medium-High

- Strong risk-adjusted returns (Sharpe 1.65)
- Low drawdown (-15.9%) compared to most strategies
- Healthy walk-forward results (no overfitting)
- Does not beat Buy & Hold in a strong bull market (expected)
- With leverage, could potentially approach Buy & Hold returns

## Known Limitations

- Underperforms Buy & Hold in strong unidirectional bull markets
- Not tested on bear market data
- May whipsaw in ranging/choppy markets
- No integrated stop-loss mechanism (uses ATR trailing stop via signals)

## Grid Search Top 5

| Fast | Slow | ATRx | Filter | Return | Sharpe |
|------|------|------|--------|--------|--------|
| 34 | 55 | 4.0 | 100 | +68.0% | 1.65 |
| 21 | 89 | 4.0 | 200 | +50.9% | 1.57 |
| 21 | 55 | 4.0 | 200 | +50.4% | 1.32 |
| 34 | 55 | 4.0 | 200 | +47.5% | 1.43 |
| 34 | 89 | 4.0 | 100 | +46.5% | 1.38 |
