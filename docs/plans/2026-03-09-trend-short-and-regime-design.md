# Design: Trailing Stop + Trend Short Strategy + Market Regime Service

**Date:** 2026-03-09
**Status:** Approved

## Goals

1. **引擎加 ATR Trailing Stop** — 讓趨勢策略能鎖住利潤
2. **雙向趨勢策略（Trend Surfer）** — 牛市做多、熊市做空，一個策略自動切換
3. **市場牛熊判斷服務（Regime API）** — 多時間框架判斷，給自動化交易決策用

---

## Feature 1: ATR Trailing Stop

### 修改檔案
- `backend/models/__init__.py` — BacktestConfig 新增欄位
- `backend/services/strategy_engine.py` — 引擎新增 trailing stop 邏輯
- `backend/tests/test_trailing_stop.py` — 新增測試

### 模型變更

```python
# BacktestConfig 新增
trailing_stop_atr_period: int = 0    # 0=disabled, e.g. 14
trailing_stop_atr_mult: float = 3.0  # ATR × mult = trailing distance
```

### 引擎邏輯

在 `StrategyEngine.run()` 主迴圈中：
1. 預算 ATR 指標（如果 trailing_stop_atr_period > 0）
2. 每根 K 棒更新持倉的 max/min price reached
3. 計算 trailing stop 線：
   - LONG: stop = max_price - ATR * mult, 觸發條件 candle.low <= stop
   - SHORT: stop = min_price + ATR * mult, 觸發條件 candle.high >= stop
4. 止損線只往有利方向移動

主迴圈順序：固定 SL/TP → **trailing stop** → signal → process → equity

exit_type 新增值: `"TRAILING_STOP"`

### 需要追蹤的狀態（引擎內部，不改 Trade model）
- `_trailing_max_price: float` — LONG 持倉期間最高價
- `_trailing_min_price: float` — SHORT 持倉期間最低價

---

## Feature 2: Trend Surfer 雙向策略

### 新增檔案
- `backend/strategies/trend_surfer_strategy.py`

### 策略邏輯

基於 SuperTrend 指標（已有），趨勢轉向就翻倉：

```
SuperTrend direction 從 -1 翻成 +1 → BUY（開多）
SuperTrend direction 從 +1 翻成 -1 → SHORT（開空）
持倉中收到反向信號 → 引擎自動先平倉再開新倉（已支援）
```

進場條件：
- BUY: SuperTrend 翻多 AND EMA(fast) > EMA(slow) 確認
- SHORT: SuperTrend 翻空 AND EMA(fast) < EMA(slow) 確認

出場條件：
- 靠 Trailing Stop（引擎層級）或 SuperTrend 反轉

參數：
```python
{
    "atr_period": 10,      # SuperTrend ATR period
    "multiplier": 3.0,     # SuperTrend band multiplier
    "ema_fast": 20,        # EMA confirmation fast
    "ema_slow": 50,        # EMA confirmation slow
}
```

### 與現有策略的關係
- 保留 Bear Hunter（均值回歸做空）
- Trend Surfer 是趨勢跟蹤雙向，互補而非取代

---

## Feature 3: Market Regime Service

### 新增檔案
- `backend/services/regime_service.py` — 核心判斷邏輯
- `backend/app.py` — 新增 API endpoint

### API 設計

```
GET /api/regime/{symbol}?interval=1h
```

回傳：
```json
{
  "symbol": "BTCUSDT",
  "timestamp": 1709942400000,
  "timeframes": {
    "1h": {
      "regime": "bullish",
      "confidence": 65,
      "ema_trend": "bullish",
      "supertrend_dir": 1,
      "macd_regime": "bullish"
    },
    "4h": {
      "regime": "bearish",
      "confidence": 82,
      "ema_trend": "bearish",
      "supertrend_dir": -1,
      "macd_regime": "bearish"
    },
    "1d": {
      "regime": "bearish",
      "confidence": 91,
      "ema_trend": "bearish",
      "supertrend_dir": -1,
      "macd_regime": "bearish"
    }
  },
  "overall": "bearish",
  "overall_confidence": 79,
  "recommendation": "short"
}
```

### 判斷邏輯（每個時間框架）

使用三個指標投票：
1. **EMA Trend**: EMA(20) vs EMA(50) — bullish/bearish
2. **SuperTrend Direction**: direction[last] — 1=bullish, -1=bearish
3. **MACD Regime**: histogram > 0 = bullish, < 0 = bearish

Confidence 計算：
- 3/3 指標同向 = 90-100%
- 2/3 指標同向 = 60-80%
- 1/3 = neutral (30-50%)

Overall = 加權平均（1d 權重最高 > 4h > 1h）

### 所需數據
- 每個時間框架需要最近 200 根 K 棒
- 用現有的 `data_service.fetch_klines()` 拉取

---

## Implementation Tasks (可平行化)

### Task A: ATR Trailing Stop (引擎層)
- 修改 `models/__init__.py`
- 修改 `strategy_engine.py`
- 修改 `backtest_service.py` (pass through)
- 修改 `app.py` (parse new config fields)
- 寫測試 `tests/test_trailing_stop.py`
- **前置依賴：無**

### Task B: Market Regime Service
- 新增 `services/regime_service.py`
- 修改 `app.py` (新 endpoint)
- 寫測試 `tests/test_regime_service.py`
- **前置依賴：無（獨立服務）**

### Task C: Trend Surfer 雙向策略
- 新增 `strategies/trend_surfer_strategy.py`
- 修改 `app.py` (import)
- **前置依賴：Task A（需要 trailing stop 支援才能發揮完整效果）**
- 但策略本身可以先寫，只是回測時先不用 trailing stop

### 平行化方案
```
Task A (Trailing Stop) ─────┐
                            ├──> Task C (Trend Surfer 策略 + 回測驗證)
Task B (Regime Service) ────┘
```
Task A 和 B 可以完全平行。Task C 在 A 完成後開始。
