# Research Report: Scalp Sniper

- **Date:** 2026-03-10
- **Symbol:** BTCUSDT
- **Interval:** 1m
- **Period:** 2025-01-01 ~ 2025-03-01
- **Direction:** LONG+SHORT (BUY/SELL + SHORT/COVER)
- **Status:** FAILED (absolute profitability gates not met)

## Strategy Logic

The Scalp Sniper is designed for the 1m timeframe using a "micro-swing" approach:
enter on extreme conditions with 1m precision, but hold like a swing trade (4-8 hours).

### Entry Conditions (all must be true):
1. **ATR Volatility Gate**: Current ATR(60) > Average ATR(240) * 1.2 — only trades during high-volatility periods where moves can overcome transaction costs
2. **EMA Trend Filter**: EMA(50) vs EMA(200) determines direction
3. **RSI Extreme**: RSI(14) must have been below 20 (long) or above 80 (short) within last 20 candles
4. **RSI Confirmation**: RSI must bounce above 35 (long) or drop below 65 (short) — confirms reversal
5. **Cooldown**: Minimum 60 candles (1 hour) between entries

### Exit Conditions (first triggered):
1. **RSI Profit-Take**: RSI reaches 70 (long exit) or 30 (short exit) — take profits at opposite extreme
2. **Trend Reversal**: EMA fast crosses back against position direction
3. **Time Stop**: Max 360 candles (6 hours) — forces exit if neither profit-take nor reversal fires
4. **Min Hold**: Exits only allowed after 30 candles (prevents premature exit)

### Signal Types:
- LONG: BUY (entry) / SELL (exit)
- SHORT: SHORT (entry) / COVER (exit)

## Core Insight

On 1m timeframe, the average candle range (0.07%) is only 25% of round-trip transaction costs (0.30% = 0.1% commission * 2 + 0.05% slippage * 2). This means **no traditional strategy can profitably scalp on 1m**. The Scalp Sniper's approach is to:
1. Use extreme filtering to only take 3-8 trades per month (vs 145-1658 for other strategies)
2. Gate entries on high ATR periods where moves are larger
3. Hold for hours, not minutes — capturing swing-scale moves with 1m entry precision

## Optimized Parameters

```json
{
    "ema_fast": 50,
    "ema_slow": 200,
    "rsi_period": 14,
    "rsi_entry_long": 20.0,
    "rsi_entry_short": 80.0,
    "rsi_confirm_long": 35.0,
    "rsi_confirm_short": 65.0,
    "rsi_exit_long": 70.0,
    "rsi_exit_short": 30.0,
    "lookback": 20,
    "atr_period": 60,
    "atr_avg_period": 240,
    "atr_mult": 1.2,
    "cooldown": 60,
    "max_hold": 360,
    "min_hold": 30
}
```

No SL/TP recommended — SL/TP does not improve results on 1m. Smart exits (RSI profit-take + trend reversal + time stop) handle all exit logic.

## Performance (Full Period: Jan-Feb 2025)

| Metric | Value |
|--------|-------|
| Total Return | -2.00% |
| Sharpe Ratio | -0.33 |
| Win Rate | 37.5% |
| Max Drawdown | -3.14% |
| Total Trades | 8 |
| Profit Factor | 0.29 |

### By Month:
| Period | Return | WR | Trades | PF | DD |
|--------|--------|----|--------|----|----|
| Jan 2025 | +0.20% | 100% | 3 | inf | -0.60% |
| Feb 2025 | -2.19% | 0% | 5 | 0.00 | -3.14% |

## ATR Filter Impact

| ATR Mult | Return | Trades | WR | DD | PF |
|----------|--------|--------|----|----|-----|
| None (0) | -7.83% | 28 | 21.4% | -8.25% | 0.17 |
| 0.8 | -5.44% | 20 | 20.0% | -5.86% | 0.13 |
| 1.0 | -2.91% | 12 | 25.0% | -3.22% | 0.23 |
| 1.2 | -2.00% | 8 | 37.5% | -3.14% | 0.29 |

Clear conclusion: higher ATR filter = fewer trades but significantly better quality.

## SL/TP Testing (v5, no smart exits)

| Config | Return | WR | DD |
|--------|--------|----|-----|
| No SL/TP | -7.49% | 25.0% | -9.65% |
| SL0.5% TP1% | -6.56% | 18.8% | -6.57% |
| SL1% | -8.54% | 18.8% | -10.64% |
| SL2% | -7.82% | 25.0% | -9.97% |
| SL3% | -7.49% | 25.0% | -9.65% |

SL/TP does not help — tight SL gets stopped out prematurely, wide SL doesn't trigger.

## Benchmark Comparison (Feb 2025)

| Strategy | Return | Trades | DD |
|----------|--------|--------|----|
| **Scalp Sniper** | **-2.19%** | **5** | **-3.14%** |
| Buy & Hold | -20.41% | 1 | -20.41% |
| DCA Weekly | -13.48% | 9 | — |
| DCA Monthly | -16.25% | 2 | — |
| RSI (1m) | -43.38% | 145 | -44.40% |
| MACD (1m) | -99.41% | 1,658 | -99.42% |
| Bollinger Bands (1m) | -75.10% | 431 | -75.77% |
| MA Cross (1m) | -89.53% | 727 | -89.89% |
| SuperTrend (1m) | -96.87% | 1,112 | -96.98% |
| Trend Rider (1m) | -60.79% | 296 | -60.87% |

**Scalp Sniper outperforms Buy & Hold by +18.22%** and is the only strategy that doesn't catastrophically fail on 1m.

## Benchmark Comparison (Jan-Feb 2025)

| Benchmark | Return |
|-----------|--------|
| Buy & Hold | -11.93% |
| DCA Weekly | -13.48% |
| DCA Monthly | -16.25% |
| **Scalp Sniper** | **-2.00%** |

Alpha vs Buy & Hold: **+9.93%**

## Walk-Forward Validation

| Period | Return | Trades | WR |
|--------|--------|--------|----|
| IS (Jan 2025) | +0.20% | 3 | 100% |
| OOS (Feb 2025) | -2.19% | 5 | 0% |

OOS Decay: Not meaningful — too few trades for statistical significance.

The Walk-Forward results are inconclusive due to insufficient trade count. The ATR filter, while improving per-trade quality, reduces trades below the minimum required for validation.

## Quality Gates

| Gate | Threshold | Result | Pass? |
|------|-----------|--------|-------|
| Total Trades | >= 10 | 8 | **FAIL** |
| Sharpe Ratio | > 0.5 | -0.33 | **FAIL** |
| Max Drawdown | < 30% | -3.14% | **PASS** |
| OOS Decay | < 50% | N/A | **N/A** |
| Win Rate | > 40% | 37.5% | **FAIL** |

**Overall: FAILED** — The strategy cannot achieve absolute profitability on 1m due to the fundamental cost-to-move ratio.

## Confidence: Low

The strategy is not recommended for standalone 1m trading. However, it demonstrates that extreme entry filtering is the only viable approach on 1m — all other strategies lose 40-99% due to excessive trading against transaction costs.

## Design Iterations

The strategy went through 6 major iterations:

1. **v1 (Multi-confluence)**: EMA + RSI + ATR spike + body ratio + candle direction. RSI exits. Result: 0% WR, 9 trades. Exit logic too aggressive.
2. **v2 (EMA crossover exits)**: Changed to EMA crossover exits. Result: 7.7% WR. EMAs cross too quickly on 1m.
3. **v3 (SL/TP only)**: Removed all exits, relied on SL/TP + RSI profit-take. Result: 38-50% WR, PF=0.15-0.55.
4. **v4 (Range Breakout)**: Completely different approach — consolidation breakout. Result: 15-21% WR. Worse than v3.
5. **v5 (Micro-Swing + Time Stop)**: Added cooldown, max_hold, state tracking. Result: -3% to -7% per month. **CRITICAL DISCOVERY**: Dynamic leverage (10x) was silently amplifying all losses.
6. **v6 (ATR Volatility Gate + Smart Exits)**: Added ATR filter, RSI profit-take, trend reversal exit. Result: -2.00% over 2 months with ATR1.2. Best version.

### Key Discovery: Dynamic Leverage Trap
Default `leverage_mode="dynamic"` with `max_leverage=10.0` was silently applying up to 10x leverage, turning a -7% strategy into -42% to -96% losses. **Always use `leverage_mode='fixed', fixed_leverage=1.0` when testing 1m strategies.**

## Known Limitations

1. **Fundamental math problem**: 1m avg candle range (0.07%) is only 25% of round-trip tx cost (0.30%). No strategy can profitably scalp this.
2. **Too few trades**: ATR filter reduces to 3-8 trades/month — below statistical significance
3. **Bearish bias in test period**: Feb 2025 was a -20% crash, which hurts all long strategies
4. **Smart exit whipsaw**: EMA trend reversal exit fires too often on 1m due to noise
5. **No out-of-sample stability**: Strategy flips from +0.20% (Jan) to -2.19% (Feb)

## Recommendations

1. **Not recommended for 1m standalone trading** — fails absolute profitability gates
2. **Consider as capital preservation tool** — loses only 2% when market loses 20%
3. **Better suited for 5m or 15m** — where avg candle range (0.20-0.50%) exceeds tx costs
4. **If used on 1m, reduce commission** — with 0.02% taker fee (VIP maker), strategy may become viable
5. **The ATR volatility gate concept is sound** — should be applied to other strategies too

## Grid Search Top 5 (v5, Jan-Feb 2025)

| Config | Return | Sharpe | WR | DD | Trades | PF |
|--------|--------|--------|----|----|--------|----|
| Default EMA50/200 RSI20/80 | -10.39% | -0.58 | 35.7% | -13.35% | 28 | 0.39 |
| EMA30/150 | -8.84% | -0.76 | 20.0% | -8.98% | 15 | 0.09 |
| Hold120 | -14.26% | -1.03 | 21.4% | -15.60% | 28 | 0.16 |
| RSI30/70 | -54.38% | -1.21 | 31.6% | -55.68% | 253 | 0.50 |
| CD30 RSI30/70 | -54.69% | -1.21 | 30.1% | -55.98% | 256 | 0.49 |
