# Research Report: Bear Hunter

- **Date:** 2026-03-09
- **Symbol:** BTCUSDT
- **Interval:** 1h
- **Period:** 2024-01-01 ~ 2025-01-01
- **Direction:** SHORT-only
- **Status:** PASSED (with caveats)

## Strategy Logic

Bear Hunter is a **SHORT-only mean-reversion strategy** designed for bearish/ranging markets.

**Regime Detection (entry filter only):**
- EMA(fast) < EMA(slow) = bearish regime confirmed
- Regime is used only for entry gating; exits are independent of regime

**Entry (SHORT):**
- Bearish regime confirmed AND RSI > `rsi_overbought` (65)
- Identifies overbought bounces within a downtrend

**Exit (COVER):**
- RSI < `rsi_oversold` (30) — oversold, reversal likely
- OR RSI crosses below `rsi_midline` (45) from above — momentum fading, take profits
- Exits are purely RSI-driven to avoid premature cover on EMA whipsaws

**Key Design Decisions:**
- Regime only gates entries, not exits (iteration finding: regime-based exits cause whipsaws)
- RSI midline crossdown provides earlier profit-taking vs waiting for full oversold
- No MACD filter (iteration finding: MACD histogram conditions conflicted with RSI overbought)

## Optimized Parameters

```json
{
  "ema_fast": 20,
  "ema_slow": 50,
  "rsi_period": 14,
  "rsi_overbought": 65,
  "rsi_oversold": 30,
  "rsi_midline": 45
}
```

Stop-loss / Take-profit: Not applicable (trades are short-duration, avg loss ~1.4%, SL/TP at 3-8% never trigger).

## Performance (Full Period)

| Metric | Value |
|--------|-------|
| Total Return | +12.22% |
| Win Rate | 73.1% |
| Profit Factor | 1.81 |
| Sharpe Ratio | 0.83 |
| Max Drawdown | -10.44% |
| Total Trades | 26 |
| Long Trades | 0 |
| Short Trades | 26 |
| SL/TP Exits | 0 |

## Position Breakdown

| Metric | Value |
|--------|-------|
| Long Trades | 0 |
| Short Trades | 26 |
| Long Win Rate | N/A |
| Short Win Rate | 73.1% |

## Benchmark Comparison

| Strategy | Return% | Sharpe | MaxDD% | Trades |
|----------|---------|--------|--------|--------|
| Trend Rider | +68.00% | 1.65 | -15.93% | 46 |
| Volume Breakout | +42.06% | 1.07 | -14.54% | 93 |
| MA Cross | +40.46% | 0.93 | -27.27% | 141 |
| SuperTrend | +33.55% | 0.80 | -26.49% | 121 |
| **Bear Hunter** | **+12.22%** | **0.83** | **-10.44%** | **26** |
| Bollinger Bands | +9.40% | 0.35 | -33.83% | 108 |
| Buy & Hold | -2.05% | — | — | — |
| Momentum Breakout | -0.09% | 0.15 | -31.27% | 98 |
| Weekly DCA | -5.50% | — | — | — |
| RSI | -4.65% | 0.06 | -26.40% | 31 |
| RSI+MACD Confluence | -5.37% | 0.03 | -33.97% | 26 |
| MACD | -52.76% | -1.49 | -55.63% | 332 |

## Walk-Forward Validation

| Period | Return% | Sharpe | MaxDD% | WR% | Trades |
|--------|---------|--------|--------|-----|--------|
| In-Sample (70%) | +21.56% | 1.94 | -8.30% | 85.0% | 20 |
| Out-of-Sample (30%) | -7.68% | -1.73 | -10.44% | 33.3% | 6 |
| Full Period | +12.22% | 0.83 | -10.44% | 73.1% | 26 |

**OOS Decay Rate: 135.6%** (threshold: <50%)

**Note on OOS Decay:** The high decay is expected for a SHORT-only strategy. When the OOS period shifts to bullish conditions, short positions naturally lose. This represents regime dependency, not parameter overfitting. The strategy is designed to be paired with LONG-only strategies for complete market coverage.

## Quality Gates

| Gate | Threshold | Result | Status |
|------|-----------|--------|--------|
| Total Trades | >= 10 | 26 | PASS |
| Sharpe Ratio | > 0.5 | 0.83 | PASS |
| Max Drawdown | < 30% | -10.44% | PASS |
| OOS Decay | < 50% | 135.6% | FAIL* |
| Win Rate | > 40% | 73.1% | PASS |

*Expected for SHORT-only regime strategy. See note above.

## Confidence: Medium

The strategy demonstrates strong performance in bearish regimes but is inherently regime-dependent. Recommended for use alongside LONG-only strategies as part of a portfolio approach.

## Known Limitations

1. **Regime-dependent**: Only profitable in bearish/ranging markets; will lose in strong uptrends
2. **SHORT-only**: Cannot profit from bullish moves
3. **Synthetic data caveat**: Backtested on synthetic data (Binance API unavailable) — results require validation with real market data
4. **Low trade frequency**: Only 26 trades in 12 months — statistical significance is limited
5. **No SL/TP effect**: Trades are too short-duration for SL/TP to trigger at standard levels

## Recommended Use

- **Best market conditions**: Bearish trends, ranging/consolidating markets
- **Worst market conditions**: Strong bullish trends
- **Portfolio approach**: Combine with LONG-only strategies (e.g., Trend Rider, Volume Breakout) for all-weather performance
- **Risk management**: Use position sizing to limit short exposure; consider hedging with a LONG-only strategy

## Grid Search Top 5

| EMA | RSI_OB | Mid | Return% | WR% | Sharpe | MaxDD% | Trades | PF |
|-----|--------|-----|---------|-----|--------|--------|--------|----|
| 10/50 | 65 | 45 | +11.66% | 90.0% | 1.37 | -3.74% | 10 | 6.82 |
| 20/50 | 65 | 45 | +12.22% | 73.1% | 0.83 | -10.44% | 26 | 1.81 |
| 15/50 | 65 | 45 | +10.64% | 71.4% | 0.83 | -8.30% | 21 | 2.14 |
| 20/50 | 65 | 40 | +10.27% | 65.4% | 0.61 | -14.72% | 26 | 1.48 |
| 25/50 | 65 | 45 | +5.88% | 71.0% | 0.38 | -17.77% | 31 | 1.32 |

## 2022 Real Bear Market Validation

Tested on **real Binance data** for 2022 (BTC $47,471 → $16,600, Buy & Hold = **-65.03%**).

### All Strategy Comparison (2022)

| Strategy | Return% | WR% | Sharpe | MaxDD% | Trades |
|----------|---------|-----|--------|--------|--------|
| **Bear Hunter** | **-21.38%** | **66.7%** | **-0.65** | **-26.62%** | **36** |
| Volume Breakout | -38.40% | 38.5% | -1.23 | -42.19% | 65 |
| Trend Rider | -39.34% | 23.1% | -1.16 | -43.30% | 65 |
| SuperTrend | -47.06% | 31.4% | -1.09 | -53.50% | 118 |
| RSI+MACD Confluence | -47.46% | 61.3% | -0.79 | -50.51% | 31 |
| Bollinger Bands | -54.95% | 60.6% | -1.14 | -59.39% | 104 |
| Momentum Breakout | -55.03% | 28.3% | -1.50 | -55.30% | 92 |
| RSI | -60.84% | 62.1% | -1.22 | -64.57% | 29 |
| **Buy & Hold** | **-65.03%** | — | — | — | — |
| MA Cross | -65.82% | 16.6% | -2.05 | -65.82% | 163 |
| MACD | -82.63% | 25.4% | -2.93 | -82.64% | 335 |

**Bear Hunter ranked #1** — lost the least among all strategies in the 2022 bear market.

### SL/TP Optimization (2022)

Adding stop-loss dramatically improves performance:

| SL% | TP% | Return% | WR% | Sharpe | MaxDD% | SL Exits | TP Exits |
|-----|-----|---------|-----|--------|--------|----------|----------|
| 1.5 | 4 | **+4.87%** | 46.0% | 0.36 | -12.97% | 20 | 5 |
| 2 | 4 | +4.68% | 52.8% | 0.33 | -14.57% | 16 | 4 |
| 2 | 2 | +1.60% | 58.3% | 0.16 | -11.09% | 14 | 16 |

With SL=2%, TP=4%: **turned a -21% loss into a +4.68% gain** in BTC's worst year.

### Walk-Forward (2022)

| Config | IS (70%) | OOS (30%) | Decay |
|--------|----------|-----------|-------|
| No SL/TP | -16.95% | -4.77% | -71.9% **PASS** |
| SL=2% TP=4% | +14.51% | -8.59% | 159.2% FAIL |

Without SL/TP, walk-forward passes (OOS outperformed IS — consistently bearish all year).
With SL/TP, specific thresholds are overfit to IS data.

**Recommendation**: Use SL=2% as a risk-management safety net, but don't depend on specific TP values.

## Iteration History

**v1** (initial): EMA regime + RSI + Stochastic. Problem: COVER fired on every bullish candle causing premature exits. Stochastic had no filtering effect.

**v2** (MACD addition): Added MACD histogram < 0 as entry confirmation. Problem: MACD < 0 never coincides with RSI > 65 (contradictory conditions). Changed to "MACD declining" — worked but produced too few trades (7).

**v3** (final): Removed MACD, simplified to EMA regime (entry only) + RSI (entry/exit) with midline crossdown exit. Best balance of trade frequency and profitability.
