# Dynamic Leverage System — Design Document

> Date: 2026-03-09
> Status: Approved
> Author: Claude + User

## Overview

Add dynamic leverage (contract trading) support to the backtesting platform. An AI-powered LeverageAssessor module evaluates market conditions before each trade to determine the optimal leverage multiplier (1x–max), while strategies can optionally override the suggested leverage.

## Requirements

| Requirement | Decision |
|-------------|----------|
| Leverage determination | AI dynamic assessment (LeverageAssessor) |
| Max leverage | Configurable, default 10x |
| Liquidation | Simulate Binance rules (maintenance margin) |
| Funding rate | Fixed rate simulation (default 0.01% per 8h) |
| Architecture | Independent LeverageAssessor module |
| Strategy override | Allowed via optional `TradeSignal.leverage` field |
| Backward compatibility | Full — leverage=1.0 equals current behavior |

## 1. Data Model Changes

### BacktestConfig — new fields

```python
# Leverage settings
max_leverage: float = 10.0              # Hard cap (1.0~20.0)
leverage_mode: str = "dynamic"          # "dynamic"=AI assess, "fixed"=constant
fixed_leverage: float = 1.0             # Used when leverage_mode="fixed"

# Contract costs
funding_rate: float = 0.0001            # Per 8h (0.01%), ~10.95% annualized
maintenance_margin_rate: float = 0.005  # 0.5% (Binance default for BTC)
```

### Trade — new fields

```python
leverage: float = 1.0            # Actual leverage used
margin_used: float = 0.0         # Margin amount locked
liquidation_price: float = 0.0   # Forced liquidation price
funding_paid: float = 0.0        # Cumulative funding paid
```

### TradeSignal — new optional field

```python
leverage: Optional[float] = None  # Strategy-suggested leverage (None = use Assessor)
```

All new fields have defaults. Existing code is unaffected.

## 2. LeverageAssessor Module

New file: `backend/services/leverage_service.py`

### Interface

```python
class LeverageAssessor:
    def assess(self, ohlcv: OHLCVData, index: int, side: str,
               max_leverage: float = 10.0) -> float:
        """Return suggested leverage (1.0 ~ max_leverage)."""
```

### Three-Factor Scoring Model

| Factor | Calculation | Logic | Weight |
|--------|------------|-------|--------|
| Volatility score | ATR(14) / close | Low vol → safe for high leverage | 40% |
| Trend strength | ADX(14) | ADX > 25 → strong trend → higher leverage | 35% |
| EMA alignment | EMA(20) vs EMA(50) vs EMA(200) | Triple alignment → high; tangled → low; counter-direction → minimum | 25% |

### Scoring Formula

```python
composite_score = vol_score * 0.4 + adx_score * 0.35 + ema_score * 0.25
# Range: 0.0 ~ 1.0

suggested_leverage = 1.0 + (max_leverage - 1.0) * composite_score
# Example: max=10x, score=0.7 → 1 + 9*0.7 = 7.3x → round to 7x
```

### Override Priority

1. If `TradeSignal.leverage` is set → use it (capped at max_leverage)
2. If `leverage_mode="fixed"` → use `fixed_leverage`
3. Otherwise → use LeverageAssessor.assess() result

### New Indicator Required: ADX

Add `adx(highs, lows, closes, period=14)` to `indicator_service.py`.
ADX (Average Directional Index) measures trend strength on a 0–100 scale.

## 3. Engine Changes

### Main Loop Order (updated)

```
Per candle:
  1. Check Liquidation          ← NEW (highest priority)
  2. Apply Funding Rate         ← NEW
  3. Check fixed SL/TP          ← existing
  4. Check ATR Trailing Stop    ← existing
  5. Generate signal            ← existing
  6. Process signal (open/close)← MODIFIED (leverage-aware)
  7. Calculate equity curve     ← MODIFIED (margin model)
```

### Open Position with Leverage

```python
def _open_long(self, candle, capital, signal, leverage):
    fill_price = candle.close * (1 + slippage)
    commission = capital * commission_rate
    margin = capital - commission              # Available margin
    position_value = margin * leverage         # Leveraged notional value
    quantity = position_value / fill_price

    # Binance isolated margin liquidation price (simplified)
    # LONG: liq = entry * (1 - 1/leverage + mmr)
    liquidation_price = fill_price * (1 - 1/leverage + maintenance_margin_rate)

    return Trade(..., leverage=leverage, margin_used=margin,
                 liquidation_price=liquidation_price)

def _open_short(self, candle, capital, signal, leverage):
    fill_price = candle.close * (1 - slippage)
    commission = capital * commission_rate
    margin = capital - commission
    position_value = margin * leverage
    quantity = position_value / fill_price

    # SHORT: liq = entry * (1 + 1/leverage - mmr)
    liquidation_price = fill_price * (1 + 1/leverage - maintenance_margin_rate)

    return Trade(..., leverage=leverage, margin_used=margin,
                 liquidation_price=liquidation_price)
```

### Liquidation Check

```python
def _check_liquidation(self, position, candle):
    if position.side == "LONG":
        if candle.low <= position.liquidation_price:
            return position.liquidation_price
    else:  # SHORT
        if candle.high >= position.liquidation_price:
            return position.liquidation_price
    return None
```

On liquidation: `capital = 0`, `exit_type = "LIQUIDATION"`. Margin is fully lost.

### Funding Rate

```python
def _apply_funding(self, position, candle, capital, funding_rate, interval):
    # Determine funding interval based on candle interval
    # 1h → every 8 candles, 4h → every 2 candles, 1d → every 1/3 (skip)
    funding_cost = position.quantity * candle.close * funding_rate
    position.funding_paid += funding_cost
    # Deduct from margin/capital
```

Funding is applied at fixed intervals. For timeframes longer than 8h (e.g., 1d),
funding is prorated (3x per day).

### Equity Curve (leveraged)

```python
# LONG with leverage:
unrealized_pnl = (candle.close - entry_price) * quantity
equity = margin + unrealized_pnl - funding_paid

# SHORT with leverage:
unrealized_pnl = (entry_price - candle.close) * quantity
equity = margin + unrealized_pnl - funding_paid
```

### Close Position PnL

```python
# LONG:
proceeds = quantity * exit_price
pnl = proceeds - (quantity * entry_price) - exit_commission - funding_paid
capital = margin + pnl  # Can be > margin (profit) or < margin (loss)

# SHORT:
pnl = (entry_price - exit_price) * quantity - exit_commission - funding_paid
capital = margin + pnl
```

## 4. API Changes

### POST /api/backtest/run — new optional fields

```json
{
  "max_leverage": 10.0,
  "leverage_mode": "dynamic",
  "fixed_leverage": 1.0,
  "funding_rate": 0.0001,
  "maintenance_margin_rate": 0.005
}
```

### POST /api/backtest/compare — same new fields per config

All fields optional with backward-compatible defaults.

## 5. New Metrics

| Metric | Description |
|--------|-------------|
| `avg_leverage` | Mean leverage across all trades |
| `max_leverage_used` | Highest leverage actually used |
| `total_funding_paid` | Cumulative funding rate cost |
| `liquidation_count` | Number of liquidation events |
| `leverage_adjusted_return` | Net return after funding costs |

## 6. File Changes

### New files

| File | Purpose |
|------|---------|
| `services/leverage_service.py` | LeverageAssessor module |
| `tests/test_leverage_assessor.py` | Assessor unit tests (~10) |
| `tests/test_liquidation.py` | Liquidation mechanism tests (~8) |
| `tests/test_funding_rate.py` | Funding rate tests (~5) |
| `tests/test_leverage_engine.py` | Integration tests (~5) |

### Modified files

| File | Changes |
|------|---------|
| `models/__init__.py` | Add leverage fields to BacktestConfig, Trade, TradeSignal |
| `services/indicator_service.py` | Add ADX indicator |
| `services/strategy_engine.py` | Leverage-aware open/close, liquidation check, funding |
| `services/backtest_service.py` | Pass-through new config params |
| `services/report_service.py` | New leverage-related metrics |
| `app.py` | Parse new API parameters |

### Estimated test count: ~40 new tests

## 7. Backward Compatibility

- `max_leverage=10.0` with `leverage_mode="dynamic"` is the new default
- When all leverage params are at defaults and the assessor returns 1.0 (flat market), behavior equals current 1x mode
- `leverage_mode="fixed"` + `fixed_leverage=1.0` exactly replicates current behavior
- Existing strategies don't need any changes (TradeSignal.leverage defaults to None)
- All 162 existing tests must continue to pass

## 8. Risk Management Notes

- Liquidation check runs BEFORE SL/TP — if price gaps through SL into liquidation territory, liquidation takes priority (more realistic)
- Funding rate is always charged to the position holder (simplified; in reality it depends on the rate being positive or negative)
- The LeverageAssessor never suggests leverage below 1.0
- The assessor's suggestions are deterministic (same inputs → same output), making backtests reproducible
