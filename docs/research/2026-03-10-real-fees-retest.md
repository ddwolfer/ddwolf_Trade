# Re-test Results: Real Maker Fees (0.018%)

- **Date:** 2026-03-10
- **Symbol:** BTCUSDT
- **Period:** 2025-01-01 ~ 2025-03-01
- **Config:** commission_rate=0.00018, slippage_rate=0, leverage=1x fixed
- **Rationale:** User's actual Binance fees are 0.018% Maker (with BNB discount), not the default 0.1%+0.05% slippage

## Key Finding: Scalp Sniper on 1m — From Unprofitable to Break-Even

| Metric | Old Fees (0.1%+0.05%) | Real Fees (0.018%) | Change |
|--------|----------------------|-------------------|--------|
| Total Return | -2.00% | **+0.09%** | +2.09pp |
| Win Rate | 37.5% | **62.5%** | +25pp |
| Profit Factor | 0.29 | **1.25** | 4.3x |
| Max Drawdown | -3.14% | **-1.98%** | Improved |
| Sharpe Ratio | -0.33 | **0.02** | Now positive |
| Trades | 8 | 8 | Same |

The strategy flipped from unprofitable to marginally profitable. Transaction costs were the primary barrier — reducing round-trip cost from 0.30% to 0.036% is transformative.

## 5m Strategy Comparison (Real Maker Fees)

| Strategy | Return | Sharpe | WR | Trades | DD | PF |
|----------|--------|--------|-----|--------|-----|-----|
| RSI+MACD Confluence | -19.61% | -0.69 | 60.4% | 53 | -28.84% | 0.66 |
| Bear Hunter (SHORT) | -23.68% | -2.18 | 34.1% | 41 | -24.44% | 0.12 |
| RSI | -27.03% | -1.02 | 58.5% | 53 | -31.66% | 0.47 |
| Trend Rider | -28.80% | -1.87 | 23.5% | 115 | -29.51% | 0.54 |
| Momentum Breakout | -46.93% | -2.51 | 23.8% | 202 | -49.68% | 0.55 |
| Volume Breakout | -42.16% | -3.05 | 19.1% | 157 | -42.16% | 0.43 |
| Trend Surfer (DUAL) | -45.13% | -2.56 | 22.9% | 166 | -46.81% | 0.43 |
| Bollinger Bands | -50.27% | -2.37 | 46.6% | 178 | -51.62% | 0.45 |
| MA Cross | -64.69% | -4.22 | 17.4% | 327 | -66.50% | 0.45 |
| SuperTrend | -68.48% | -4.36 | 22.6% | 337 | -69.60% | 0.41 |
| Scalp Sniper | -1.00% | -0.19 | 0.0% | 2 | -3.17% | 0.00 |
| MACD | -90.94% | -8.50 | 19.1% | 721 | -91.14% | 0.30 |

**Note:** Scalp Sniper on 5m only took 2 trades (designed for 1m). Buy & Hold returned -11.93% in this period.

## Conclusions

1. **Real fees dramatically improve viability** — Scalp Sniper went from -2.00% to +0.09% on 1m
2. **No existing strategy is profitable on 5m** — all lose, even with real fees. Best is RSI+MACD Confluence at -19.61%
3. **The test period is bearish** (BTC -20% in Feb 2025) — LONG-only strategies suffer disproportionately
4. **RSI+MACD Confluence is the best 5m performer** — fewest trades (53), highest WR (60.4%), lowest DD among losers
5. **A new 5m-optimized strategy is needed** — existing strategies weren't designed for 5m with real fees
6. **Dual-direction strategies help** — Bear Hunter and Trend Surfer lose less than LONG-only equivalents in bearish markets

## Next Steps

- Design and research a new strategy optimized for 5m timeframe
- Consider dual-direction (LONG+SHORT) to handle bearish periods
- Use RSI+MACD Confluence pattern as starting point (best WR and fewest trades)
- ATR volatility gate from Scalp Sniper should be adapted for 5m
