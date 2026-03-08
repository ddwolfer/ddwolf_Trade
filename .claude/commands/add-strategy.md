# /add-strategy — 新增自訂交易策略

根據用戶描述，建立一個新的交易策略並整合到系統中。

## 執行步驟

### 1. 了解策略需求

詢問用戶（如果尚未提供）：
- 進場條件（什麼情況下開倉）
- 出場條件（什麼情況下平倉）
- 方向：只做多（BUY/SELL）還是也做空（SHORT/COVER）？
- 需要哪些技術指標？
- 有沒有參數想讓用戶在 UI 上調整？

### 2. 建立策略檔案

在 `backend/strategies/` 建立新檔案，遵循以下模板：

```python
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class NewStrategy(BaseStrategy):
    """策略描述（簡要說明邏輯）"""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Strategy Name",
            "description": "What this strategy does",
            "category": "technical|momentum|mean_reversion|trend_following|composite",
            "parameters": {
                "param_name": {
                    "type": "int|float",
                    "default": 14,
                    "min": 1,
                    "max": 100,
                    "description": "What this controls"
                }
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        if index < 50:  # 確保有足夠歷史數據
            return None

        candle = ohlcv.candles[index]
        closes = [c.close for c in ohlcv.candles[:index + 1]]

        # 用 self.cache_indicator() 快取指標計算
        rsi = self.cache_indicator("rsi", lambda: ind.rsi(closes, self.params.get("period", 14)))

        current_rsi = rsi[index]

        # 做多信號
        if current_rsi < 30:
            return TradeSignal(
                timestamp=candle.timestamp,
                signal_type="BUY",
                price=candle.close,
                reason=f"RSI oversold: {current_rsi:.1f}"
            )

        # 做空信號（如果策略支援）
        # if current_rsi > 70:
        #     return TradeSignal(
        #         timestamp=candle.timestamp,
        #         signal_type="SHORT",
        #         price=candle.close,
        #         reason=f"RSI overbought: {current_rsi:.1f}"
        #     )

        return None
```

### 3. 註冊策略

在 `backend/app.py` 的 import 區塊加入一行：
```python
from strategies import new_strategy_file
```

### 4. 測試策略

重啟 server 並驗證：

```bash
# 確認策略出現在列表中
curl -s http://localhost:8000/api/strategies | python -m json.tool

# 用預設參數跑一次回測
curl -s -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","strategy_name":"New Strategy Name"}'

# 帶止損/止盈測試
curl -s -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","strategy_name":"New Strategy Name","stop_loss_pct":5,"take_profit_pct":10}'
```

### 5. 驗證結果合理性

- 交易次數 > 0（策略有產生信號）
- Win Rate 不是 0% 或 100%（太極端說明邏輯有問題）
- 如果是做空策略，確認有 SHORT 交易出現

## 可用技術指標

`services/indicator_service.py` 提供以下函式（不要自己實作，直接使用）：

| 函式 | 用途 | 預設參數 |
|------|------|---------|
| `sma(closes, period)` | 簡單移動平均 | period=20 |
| `ema(closes, period)` | 指數移動平均 | period=20 |
| `rsi(closes, period)` | 相對強弱指標 | period=14 |
| `macd(closes, fast, slow, signal)` | MACD 三線 | 12, 26, 9 |
| `bollinger_bands(closes, period, std_dev)` | 布林通道 | 20, 2.0 |
| `atr(highs, lows, closes, period)` | 平均真實波幅 | period=14 |
| `stochastic(highs, lows, closes, k, d)` | KD 指標 | 14, 3 |
| `supertrend(highs, lows, closes, atr_period, multiplier)` | SuperTrend | 10, 3.0 |

## 信號類型

引擎支援 4 種信號：

| 信號 | 用途 | 引擎行為 |
|------|------|---------|
| `BUY` | 開多 / 平空 | 無持倉→開多；持空倉→平空再開多 |
| `SELL` | 平多 | 持多倉→平多；無持倉→忽略 |
| `SHORT` | 開空 / 平多 | 無持倉→開空；持多倉→平多再開空 |
| `COVER` | 平空 | 持空倉→平空；無持倉→忽略 |

現有 9 個策略都只用 BUY/SELL。如果用戶想做空，加入 SHORT/COVER 信號即可。

## 注意事項

- `generate_signal()` 的 `index` 從 0 開始，要確保 index 夠大再計算指標（避免陣列越界）
- 用 `self.cache_indicator(key, lambda: ...)` 快取指標，避免每根 K 棒重複計算整個序列
- `metadata()` 裡的 `parameters` 定義了 UI 上可調的參數，`default` 值要設好
- 策略只負責發信號，止損/止盈由引擎處理（用戶在 UI 設定 `stop_loss_pct` / `take_profit_pct`）
- 每個策略必須用 `@StrategyRegistry.register` 裝飾器，否則不會被引擎發現
