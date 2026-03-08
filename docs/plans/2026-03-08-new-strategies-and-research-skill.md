# New Strategies + /research Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 3 new trading strategies (Confluence, SuperTrend, Volume Breakout) and create a `/research` slash command that automates the full strategy research cycle.

**Architecture:** Each strategy is a standalone file inheriting `BaseStrategy`, registered via `@StrategyRegistry.register`. SuperTrend requires a new indicator in `indicator_service.py`. The `/research` command is a `.claude/commands/research.md` file that orchestrates research → implement → validate → iterate.

**Tech Stack:** Python 3.10+, numpy, existing indicator_service.py functions, HTTP API at localhost:8000

---

## Task 1: Add SuperTrend indicator to indicator_service.py

**Files:**
- Modify: `backend/services/indicator_service.py` (append new function at end of file)

**Step 1: Add `supertrend()` function**

Append this function at the end of `backend/services/indicator_service.py`:

```python
def supertrend(highs: List[float], lows: List[float], closes: List[float],
               atr_period: int = 10, multiplier: float = 3.0) -> Tuple[List[Optional[float]], List[int]]:
    """
    SuperTrend indicator.
    Returns: (supertrend_values, direction)
      - supertrend_values: the SuperTrend line price
      - direction: 1 = bullish (uptrend), -1 = bearish (downtrend)
    """
    n = len(closes)
    atr_values = atr(highs, lows, closes, atr_period)

    st_values = [None] * n
    direction = [0] * n
    upper_band = [0.0] * n
    lower_band = [0.0] * n

    for i in range(atr_period, n):
        if atr_values[i] is None:
            continue

        hl2 = (highs[i] + lows[i]) / 2.0
        upper_band[i] = hl2 + multiplier * atr_values[i]
        lower_band[i] = hl2 - multiplier * atr_values[i]

        if i == atr_period:
            direction[i] = 1 if closes[i] > upper_band[i] else -1
            st_values[i] = lower_band[i] if direction[i] == 1 else upper_band[i]
            continue

        # Ratchet bands: only tighten, never widen against the trend
        if lower_band[i] < lower_band[i - 1] and closes[i - 1] > lower_band[i - 1]:
            lower_band[i] = lower_band[i - 1]
        if upper_band[i] > upper_band[i - 1] and closes[i - 1] < upper_band[i - 1]:
            upper_band[i] = upper_band[i - 1]

        # Determine direction
        if direction[i - 1] == 1:
            if closes[i] < lower_band[i]:
                direction[i] = -1
                st_values[i] = upper_band[i]
            else:
                direction[i] = 1
                st_values[i] = lower_band[i]
        else:
            if closes[i] > upper_band[i]:
                direction[i] = 1
                st_values[i] = lower_band[i]
            else:
                direction[i] = -1
                st_values[i] = upper_band[i]

    return st_values, direction
```

**Step 2: Verify indicator_service.py loads without errors**

Run: `cd backend && python -c "from services import indicator_service as ind; print('OK:', [x for x in dir(ind) if not x.startswith('_')])"`

Expected: OK with `supertrend` in the function list.

**Step 3: Commit**

```bash
git add backend/services/indicator_service.py
git commit -m "feat: add SuperTrend indicator to indicator_service"
```

---

## Task 2: Create Confluence strategy (RSI + MACD)

**Files:**
- Create: `backend/strategies/confluence_strategy.py`

**Step 1: Write the strategy file**

Create `backend/strategies/confluence_strategy.py`:

```python
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class ConfluenceStrategy(BaseStrategy):
    """RSI + MACD multi-indicator confluence strategy.

    Requires both RSI zone confirmation AND MACD momentum shift
    to trigger signals, dramatically reducing false signals.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "RSI+MACD Confluence",
            "description": "Buy when RSI is oversold AND MACD histogram turns bullish. Sell when RSI is overbought AND MACD turns bearish.",
            "category": "composite",
            "parameters": {
                "rsi_period": {
                    "type": "int", "default": 14, "min": 5, "max": 50,
                    "description": "RSI calculation period"
                },
                "overbought": {
                    "type": "float", "default": 65.0, "min": 55, "max": 85,
                    "description": "RSI overbought threshold"
                },
                "oversold": {
                    "type": "float", "default": 35.0, "min": 15, "max": 45,
                    "description": "RSI oversold threshold"
                },
                "macd_fast": {
                    "type": "int", "default": 12, "min": 5, "max": 30,
                    "description": "MACD fast EMA period"
                },
                "macd_slow": {
                    "type": "int", "default": 26, "min": 15, "max": 50,
                    "description": "MACD slow EMA period"
                },
                "macd_signal": {
                    "type": "int", "default": 9, "min": 3, "max": 20,
                    "description": "MACD signal line period"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        macd_slow = self.params["macd_slow"]
        rsi_period = self.params["rsi_period"]
        min_period = max(macd_slow + self.params["macd_signal"], rsi_period) + 2

        if index < min_period:
            return None

        # Cache indicators
        rsi_values = self.cache_indicator(
            f"rsi_{rsi_period}",
            lambda: ind.rsi(ohlcv.closes(), rsi_period)
        )
        macd_key = f"macd_{self.params['macd_fast']}_{macd_slow}_{self.params['macd_signal']}"
        macd_result = self.cache_indicator(
            macd_key,
            lambda: ind.macd(ohlcv.closes(), self.params["macd_fast"],
                           macd_slow, self.params["macd_signal"])
        )
        _, _, histogram = macd_result

        rsi_val = rsi_values[index]
        hist_curr = histogram[index]
        hist_prev = histogram[index - 1]

        if rsi_val is None or hist_curr is None or hist_prev is None:
            return None

        candle = ohlcv.candles[index]

        # BUY: RSI in oversold zone + MACD histogram turning bullish
        if rsi_val <= self.params["oversold"] and hist_curr > hist_prev and hist_prev < 0:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"Confluence BUY: RSI={rsi_val:.1f} <= {self.params['oversold']}, MACD hist turning up"
            )

        # SELL: RSI in overbought zone + MACD histogram turning bearish
        if rsi_val >= self.params["overbought"] and hist_curr < hist_prev and hist_prev > 0:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"Confluence SELL: RSI={rsi_val:.1f} >= {self.params['overbought']}, MACD hist turning down"
            )

        return None
```

**Step 2: Register in app.py**

In `backend/app.py` line 23, change:

```python
from strategies import rsi_strategy, macd_strategy, bollinger_strategy, ma_cross_strategy, momentum_strategy
```

to:

```python
from strategies import rsi_strategy, macd_strategy, bollinger_strategy, ma_cross_strategy, momentum_strategy, confluence_strategy
```

**Step 3: Verify strategy loads**

Run: `cd backend && python -c "from strategies import confluence_strategy; from strategies.registry import StrategyRegistry; print([s['name'] for s in StrategyRegistry.list_all()])"`

Expected: list includes `"RSI+MACD Confluence"`

**Step 4: Commit**

```bash
git add backend/strategies/confluence_strategy.py backend/app.py
git commit -m "feat: add RSI+MACD Confluence strategy"
```

---

## Task 3: Create SuperTrend strategy

**Files:**
- Create: `backend/strategies/supertrend_strategy.py`

**Step 1: Write the strategy file**

Create `backend/strategies/supertrend_strategy.py`:

```python
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry
from services import indicator_service as ind


@StrategyRegistry.register
class SuperTrendStrategy(BaseStrategy):
    """ATR-based SuperTrend trend-following strategy.

    Uses ATR to dynamically calculate trend bands.
    Enters when trend flips bullish, exits when trend flips bearish.
    Excels in trending markets, underperforms in choppy/ranging markets.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "SuperTrend",
            "description": "Buy when SuperTrend flips bullish (price breaks above upper band), sell when it flips bearish.",
            "category": "momentum",
            "parameters": {
                "atr_period": {
                    "type": "int", "default": 10, "min": 5, "max": 50,
                    "description": "ATR calculation period"
                },
                "multiplier": {
                    "type": "float", "default": 2.5, "min": 1.0, "max": 5.0,
                    "description": "ATR multiplier for band width"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        atr_period = self.params["atr_period"]
        if index < atr_period + 2:
            return None

        # Cache SuperTrend computation
        st_key = f"supertrend_{atr_period}_{self.params['multiplier']}"
        st_result = self.cache_indicator(
            st_key,
            lambda: ind.supertrend(
                ohlcv.highs(), ohlcv.lows(), ohlcv.closes(),
                atr_period, self.params["multiplier"]
            )
        )
        _, direction = st_result

        curr_dir = direction[index]
        prev_dir = direction[index - 1]

        if curr_dir == 0 or prev_dir == 0:
            return None

        candle = ohlcv.candles[index]

        # BUY: trend flips from bearish to bullish
        if curr_dir == 1 and prev_dir == -1:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"SuperTrend flipped BULLISH (ATR={atr_period}, mult={self.params['multiplier']})"
            )

        # SELL: trend flips from bullish to bearish
        if curr_dir == -1 and prev_dir == 1:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"SuperTrend flipped BEARISH (ATR={atr_period}, mult={self.params['multiplier']})"
            )

        return None
```

**Step 2: Register in app.py**

In `backend/app.py` line 23, change the import to also include `supertrend_strategy`:

```python
from strategies import rsi_strategy, macd_strategy, bollinger_strategy, ma_cross_strategy, momentum_strategy, confluence_strategy, supertrend_strategy
```

**Step 3: Verify strategy loads**

Run: `cd backend && python -c "from strategies import supertrend_strategy; from strategies.registry import StrategyRegistry; print([s['name'] for s in StrategyRegistry.list_all()])"`

Expected: list includes `"SuperTrend"`

**Step 4: Commit**

```bash
git add backend/strategies/supertrend_strategy.py backend/app.py
git commit -m "feat: add SuperTrend trend-following strategy"
```

---

## Task 4: Create Volume Breakout strategy

**Files:**
- Create: `backend/strategies/volume_breakout_strategy.py`

**Step 1: Write the strategy file**

Create `backend/strategies/volume_breakout_strategy.py`:

```python
from typing import Optional, Dict, Any
from models import OHLCVData, TradeSignal
from strategies.base_strategy import BaseStrategy
from strategies.registry import StrategyRegistry


@StrategyRegistry.register
class VolumeBreakoutStrategy(BaseStrategy):
    """Volume-confirmed breakout strategy.

    Only enters on breakouts accompanied by above-average volume,
    filtering out false breakouts that lack participation.
    This is the only strategy that uses volume data.
    """

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return {
            "name": "Volume Breakout",
            "description": "Buy when price breaks above N-period high with volume surge. Sell when price breaks below N-period low.",
            "category": "momentum",
            "parameters": {
                "lookback": {
                    "type": "int", "default": 10, "min": 5, "max": 50,
                    "description": "Lookback period for high/low and average volume"
                },
                "vol_multiplier": {
                    "type": "float", "default": 2.5, "min": 1.0, "max": 5.0,
                    "description": "Volume must exceed avg volume by this multiplier to confirm breakout"
                },
            }
        }

    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        lookback = self.params["lookback"]
        if index < lookback + 1:
            return None

        candle = ohlcv.candles[index]
        prev_candles = ohlcv.candles[index - lookback:index]

        highest = max(c.high for c in prev_candles)
        lowest = min(c.low for c in prev_candles)
        avg_volume = sum(c.volume for c in prev_candles) / lookback

        vol_threshold = avg_volume * self.params["vol_multiplier"]

        # BUY: price breaks above N-period high + volume confirmation
        if candle.close > highest and candle.volume > vol_threshold:
            return TradeSignal(
                candle.timestamp, "BUY", candle.close,
                f"Volume Breakout: price {candle.close:.2f} > {lookback}p high {highest:.2f}, "
                f"vol {candle.volume:.1f} > {vol_threshold:.1f}"
            )

        # SELL: price breaks below N-period low (no volume requirement for exits)
        if candle.close < lowest:
            return TradeSignal(
                candle.timestamp, "SELL", candle.close,
                f"Breakdown: price {candle.close:.2f} < {lookback}p low {lowest:.2f}"
            )

        return None
```

**Step 2: Register in app.py**

In `backend/app.py` line 23, change the import to the final version:

```python
from strategies import rsi_strategy, macd_strategy, bollinger_strategy, ma_cross_strategy, momentum_strategy, confluence_strategy, supertrend_strategy, volume_breakout_strategy
```

**Step 3: Verify strategy loads**

Run: `cd backend && python -c "from strategies import volume_breakout_strategy; from strategies.registry import StrategyRegistry; print([s['name'] for s in StrategyRegistry.list_all()])"`

Expected: list includes `"Volume Breakout"`

**Step 4: Commit**

```bash
git add backend/strategies/volume_breakout_strategy.py backend/app.py
git commit -m "feat: add Volume Breakout strategy"
```

---

## Task 5: Integration test — restart server and run all 8 strategies

**Step 1: Kill existing server and restart**

```bash
# Kill existing server
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
# Start fresh
cd backend && nohup python app.py &
sleep 3
```

**Step 2: Verify all 8 strategies are loaded**

Run: `curl -s http://localhost:8000/api/strategies | python -c "import sys,json; data=json.load(sys.stdin); [print(f'  {s[\"name\"]:25s} ({s[\"category\"]})') for s in data['strategies']]; print(f'\nTotal: {len(data[\"strategies\"])} strategies')"`

Expected output should list 8 strategies:
- RSI
- MACD
- Bollinger Bands
- MA Cross
- Momentum Breakout
- RSI+MACD Confluence
- SuperTrend
- Volume Breakout

**Step 3: Run full comparison backtest**

```bash
curl -s -X POST http://localhost:8000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{"configs":[
    {"symbol":"BTCUSDT","strategy_name":"RSI"},
    {"symbol":"BTCUSDT","strategy_name":"MACD"},
    {"symbol":"BTCUSDT","strategy_name":"Bollinger Bands"},
    {"symbol":"BTCUSDT","strategy_name":"MA Cross"},
    {"symbol":"BTCUSDT","strategy_name":"Momentum Breakout"},
    {"symbol":"BTCUSDT","strategy_name":"RSI+MACD Confluence"},
    {"symbol":"BTCUSDT","strategy_name":"SuperTrend"},
    {"symbol":"BTCUSDT","strategy_name":"Volume Breakout"}
  ]}'
```

Expected: all 8 return valid metrics with no errors.

**Step 4: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test: verify all 8 strategies pass integration test"
```

---

## Task 6: Create `/research` slash command

**Files:**
- Create: `.claude/commands/research.md`

**Step 1: Write the research command**

Create `.claude/commands/research.md`:

```markdown
# /research — AI 自動策略研究工作流

針對指定幣種/週期，自動完成「研究 → 實作 → 驗證 → 迭代」的完整循環。

## 使用方式

```
/research BTCUSDT 1h
/research ETHUSDT 4h 2023-01-01 2024-01-01
```

## 參數

- `$ARGUMENTS` 格式：`SYMBOL INTERVAL [START_DATE] [END_DATE]`
- 預設：BTCUSDT 1h 2024-01-01 2025-01-01

## 執行流程

### Phase 1: 環境確認
1. 確認 server 正在運行（port 8000），如果沒有就啟動：
   ```bash
   cd backend && nohup python app.py &
   ```
2. 拉取目前所有策略：
   ```bash
   curl -s http://localhost:8000/api/strategies
   ```

### Phase 2: Baseline 建立
1. 對所有現有策略跑回測（用 `/api/backtest/compare`）
2. 記錄 baseline 指標表格（報酬、夏普、回撤、勝率、交易數）
3. 計算 Buy & Hold 基準：用 `/api/data/{SYMBOL}` 取得首尾價格算漲跌幅

### Phase 3: 策略研究
1. 根據 baseline 結果分析不足之處（例如：回撤太大、勝率太低、信號太少）
2. 搜尋適合該幣種/週期的策略思路（考慮該幣種的波動特性）
3. 決定新策略的方向：
   - 如果現有策略回撤太大 → 偏向保守/組合指標策略
   - 如果現有策略信號太少 → 偏向靈敏度更高的策略
   - 如果現有策略趨勢捕捉差 → 偏向趨勢跟蹤策略
4. 設計策略邏輯（進場、出場條件）

### Phase 4: 策略實作
1. 在 `backend/strategies/` 建立新策略檔案，遵循 BaseStrategy 模板
2. 加上 `@StrategyRegistry.register` 裝飾器
3. 在 `backend/app.py` 的 import 行加入新策略
4. 重啟 server 並確認策略出現在 `/api/strategies`

### Phase 5: 回測驗證
1. 用預設參數跑一次回測
2. 用 grid search 做參數優化（每次最多 20 組）：
   - 按 Sharpe Ratio 排序
   - 剔除 Max Drawdown > 30% 的組合
   - 剔除交易次數 < 10 的組合
3. 用最佳參數再跑一次回測
4. 跟所有策略做完整比較

### Phase 6: Walk-Forward 驗證
1. 用前 70% 數據做 in-sample 優化（找最佳參數）
2. 用後 30% 數據做 out-of-sample 驗證
3. 計算 OOS 衰退率 = (IS_return - OOS_return) / IS_return
4. 如果 OOS 衰退 > 50%，警告過度擬合

### Phase 7: 迭代優化（最多 2 輪）
如果策略不符合門檻，進行調整：
- 修改策略邏輯（例如增加過濾條件）
- 調整參數範圍
- 嘗試不同的指標組合
- 回到 Phase 5 重新驗證

#### 通過門檻
| 指標 | 門檻 |
|------|------|
| 交易數 | >= 10 |
| 夏普比率 | > 0.5 |
| 最大回撤 | < 30% |
| OOS 衰退 | < 50% |
| 勝率 | > 40% |

### Phase 8: 最終報告
輸出包含：
1. 策略名稱和邏輯描述
2. 最佳參數組合
3. 完整績效指標（含 IS 和 OOS）
4. 與所有現有策略的比較表
5. Buy & Hold 基準比較
6. 信心評級（高/中/低）和使用建議
7. 已知限制和適用行情類型

## 注意事項
- 每次 compare API 最多放 20 個 config
- 參數組合超過 100 個時用 random search
- 合成數據時要特別註明，結果僅供參考
- 新策略用 `self.cache_indicator()` 快取指標
- 指標計算用 `services/indicator_service.py` 裡的函式
```

**Step 2: Verify the file is created correctly**

Run: `ls -la .claude/commands/research.md`

Expected: file exists.

**Step 3: Commit**

```bash
git add .claude/commands/research.md
git commit -m "feat: add /research AI strategy research workflow command"
```

---

## Task 7: Final verification — run /research manually to validate workflow

**Step 1: Run a quick smoke test of the research flow**

Execute the research workflow manually to verify it works end-to-end:

```bash
# 1. List all strategies
curl -s http://localhost:8000/api/strategies | python -c "
import sys, json
data = json.load(sys.stdin)
print(f'{len(data[\"strategies\"])} strategies loaded')
for s in data['strategies']:
    print(f'  - {s[\"name\"]} ({s[\"category\"]})')
"

# 2. Full comparison
curl -s -X POST http://localhost:8000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{"configs":[
    {"symbol":"BTCUSDT","strategy_name":"RSI"},
    {"symbol":"BTCUSDT","strategy_name":"MACD"},
    {"symbol":"BTCUSDT","strategy_name":"Bollinger Bands"},
    {"symbol":"BTCUSDT","strategy_name":"MA Cross"},
    {"symbol":"BTCUSDT","strategy_name":"Momentum Breakout"},
    {"symbol":"BTCUSDT","strategy_name":"RSI+MACD Confluence"},
    {"symbol":"BTCUSDT","strategy_name":"SuperTrend"},
    {"symbol":"BTCUSDT","strategy_name":"Volume Breakout"}
  ]}' | python -c "
import sys, json
data = json.load(sys.stdin)
results = data['results']
print(f'\n{\"Strategy\":<28} {\"Return%\":>9} {\"WinRate\":>8} {\"Trades\":>7} {\"Sharpe\":>8} {\"MDD%\":>8}')
print('-' * 70)
for r in results:
    m = r['metrics']
    print(f'{r[\"strategy\"]:<28} {m[\"total_return_pct\"]:>+9.2f} {m[\"win_rate\"]*100:>8.1f} {m[\"total_trades\"]:>7} {m[\"sharpe_ratio\"]:>8.2f} {m[\"max_drawdown_pct\"]:>8.1f}')
"
```

Expected: all 8 strategies return results with no errors.

**Step 2: Commit everything**

```bash
git add -A
git commit -m "feat: complete new strategies + /research workflow

Add 3 new strategies:
- RSI+MACD Confluence (composite, multi-indicator confirmation)
- SuperTrend (ATR-based trend following)
- Volume Breakout (volume-confirmed price breakout)

Add SuperTrend indicator to indicator_service.py.
Add /research slash command for AI-driven strategy research workflow."
```

---

## Summary of Files Changed/Created

| Action | File | Purpose |
|--------|------|---------|
| Modify | `backend/services/indicator_service.py` | Add `supertrend()` function |
| Create | `backend/strategies/confluence_strategy.py` | RSI+MACD Confluence strategy |
| Create | `backend/strategies/supertrend_strategy.py` | SuperTrend strategy |
| Create | `backend/strategies/volume_breakout_strategy.py` | Volume Breakout strategy |
| Modify | `backend/app.py` | Add imports for 3 new strategies |
| Create | `.claude/commands/research.md` | /research slash command |
