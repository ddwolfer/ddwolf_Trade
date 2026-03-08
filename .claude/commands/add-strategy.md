# /add-strategy — 新增自訂交易策略

根據用戶描述，建立一個新的交易策略並整合到系統中。

## 執行步驟

1. 詢問用戶策略邏輯（進場條件、出場條件）

2. 在 `backend/strategies/` 建立新檔案，遵循以下模板：

```python
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class NewStrategy(BaseStrategy):
    """策略描述"""

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Strategy Name",
            "description": "What this strategy does",
            "category": "technical|momentum|mean_reversion|composite",
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
        # 用 self.cache_indicator() 快取指標計算
        # 回傳 TradeSignal(timestamp, "BUY"/"SELL", price, reason) 或 None
        pass
```

3. 在 `backend/app.py` 的 import 區塊加入：
   ```python
   from strategies import new_strategy_file
   ```

4. 重啟 server 並用 API 測試：
   ```bash
   curl -s -X POST http://localhost:8000/api/backtest/run \
     -H "Content-Type: application/json" \
     -d '{"symbol":"BTCUSDT","strategy_name":"New Strategy Name"}'
   ```

5. 確認策略出現在策略列表中：
   ```bash
   curl -s http://localhost:8000/api/strategies | python -m json.tool
   ```

## 注意事項

- `generate_signal()` 的 `index` 從 0 開始，要確保 index 夠大再計算指標
- 用 `self.cache_indicator(key, lambda: ...)` 避免重複計算
- 指標計算用 `services/indicator_service.py` 裡的函式
- `metadata()` 裡的 parameters 定義了 UI 上可調的參數
