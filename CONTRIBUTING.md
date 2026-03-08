# Contributing — 新增策略指南

本文件說明如何在 Crypto Backtest Platform 中新增自訂策略。

## 快速開始

只需 3 步：建立檔案、繼承基底類別、註冊策略。

### 1. 建立策略檔案

在 `backend/strategies/` 目錄下建立新的 Python 檔案：

```bash
touch backend/strategies/my_strategy.py
```

### 2. 實作策略類別

```python
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from models import TradeSignal, OHLCVData
from services.indicator_service import sma, rsi  # 按需匯入指標
from typing import Optional


@StrategyRegistry.register
class MyStrategy(BaseStrategy):

    @classmethod
    def metadata(cls) -> dict:
        return {
            "name": "My Strategy",
            "description": "策略簡短描述",
            "version": "1.0",
            "params": {
                "period": {
                    "type": "int",
                    "default": 14,
                    "min": 5,
                    "max": 50,
                    "description": "計算週期"
                },
                "threshold": {
                    "type": "float",
                    "default": 0.02,
                    "min": 0.001,
                    "max": 0.1,
                    "step": 0.005,
                    "description": "觸發閾值"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        """
        每根 K 棒呼叫一次。回傳 TradeSignal 或 None。

        Args:
            ohlcv: 完整的 OHLCV 資料（可用 ohlcv.closes(), ohlcv.highs() 等）
            index: 目前處理到第幾根 K 棒（0-based）

        Returns:
            TradeSignal(action="BUY"|"SELL", price=..., timestamp=...)
            或 None（不產生信號）
        """
        period = self.params.get("period", 14)
        closes = ohlcv.closes()

        # 確保有足夠的數據
        if index < period:
            return None

        # --- 你的策略邏輯 ---
        # 使用 self.cache_indicator() 快取運算結果，避免重複計算
        values = self.cache_indicator(
            f"sma_{period}",
            lambda: sma(closes, period)
        )

        current_price = closes[index]
        indicator_value = values[index]

        if indicator_value is None:
            return None

        # 買入信號
        if current_price < indicator_value * (1 - self.params["threshold"]):
            return TradeSignal(
                action="BUY",
                price=current_price,
                timestamp=ohlcv.candles[index].timestamp
            )

        # 賣出信號
        if current_price > indicator_value * (1 + self.params["threshold"]):
            return TradeSignal(
                action="SELL",
                price=current_price,
                timestamp=ohlcv.candles[index].timestamp
            )

        return None
```

### 3. 註冊策略

在 `backend/app.py` 中加入 import：

```python
from strategies import rsi_strategy, macd_strategy, ..., my_strategy
```

重啟 server 即可。策略會自動出現在 Web UI 和 API 中。

## 可用的技術指標

所有指標都在 `backend/services/indicator_service.py`，純 numpy 實作：

| 函式 | 說明 | 回傳 |
|------|------|------|
| `sma(data, period)` | 簡單移動平均 | `List[Optional[float]]` |
| `ema(data, period)` | 指數移動平均 | `List[Optional[float]]` |
| `rsi(closes, period)` | 相對強弱指標 | `List[Optional[float]]` |
| `macd(closes, fast, slow, signal)` | MACD 線、信號線、柱狀圖 | `Tuple[3 × List]` |
| `bollinger_bands(closes, period, std_dev)` | 上軌、中軌、下軌 | `Tuple[3 × List]` |
| `atr(highs, lows, closes, period)` | 平均真實波幅 | `List[Optional[float]]` |
| `stochastic(highs, lows, closes, k, d)` | 隨機指標 %K, %D | `Tuple[2 × List]` |

需要新指標？直接在 `indicator_service.py` 新增函式即可。

## 參數 Schema 格式

`metadata()` 中的 `params` 會自動生成 Web UI 的參數編輯器：

```python
"params": {
    "param_name": {
        "type": "int" | "float",   # 必填：資料型態
        "default": 14,              # 必填：預設值
        "min": 1,                   # 選填：最小值
        "max": 100,                 # 選填：最大值
        "step": 1,                  # 選填：步進值（float 用）
        "description": "說明文字"   # 必填：顯示在 UI 上
    }
}
```

## 策略設計準則

1. **generate_signal 必須是純函數** — 不要修改 ohlcv 資料或維護外部狀態
2. **用 cache_indicator 快取指標** — 避免每根 K 棒重複計算整條指標
3. **檢查 index 邊界** — 前 N 根 K 棒通常資料不足，直接回傳 None
4. **處理 None 值** — 指標在前幾根 K 棒可能回傳 None
5. **只回傳 BUY 或 SELL** — 引擎會自動處理倉位管理（單一倉位模式）

## 測試策略

```bash
# 啟動 server
cd backend && python app.py

# 用 API 快速測試
curl -X POST http://localhost:8000/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "interval": "1h",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
    "strategy_name": "My Strategy",
    "strategy_params": {"period": 14, "threshold": 0.02}
  }'
```

或使用 Claude Code 的 `/backtest` 指令快速測試。

## 程式碼規範

- 檔案命名：`snake_case.py`（如 `my_awesome_strategy.py`）
- 類別命名：`PascalCase`（如 `MyAwesomeStrategy`）
- metadata 的 `name` 用空格分隔的可讀名稱（如 `"My Awesome Strategy"`）
- 所有策略放在 `backend/strategies/` 目錄下
- 不要引入 pandas/numpy 以外的外部套件
