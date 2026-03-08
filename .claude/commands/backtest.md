# /backtest — 快速執行回測

執行一次策略回測並顯示結果摘要。

## 使用方式

```
/backtest RSI BTCUSDT 1h 2024-01-01 2025-01-01
/backtest MACD ETHUSDT 4h 2024-06-01 2025-01-01
/backtest "Trend Rider" BTCUSDT 1h 2024-01-01 2025-01-01 --sl 5 --tp 10
```

## 參數解析

從 `$ARGUMENTS` 解析：
- 第 1 個：策略名稱（如果有空格，用引號包住）
- 第 2 個：交易對（預設 BTCUSDT）
- 第 3 個：時間間隔（預設 1h）
- 第 4 個：起始日期（預設 2024-01-01）
- 第 5 個：結束日期（預設 2025-01-01）
- `--sl N`：止損百分比（預設 0，0 = 關閉）
- `--tp N`：止盈百分比（預設 0，0 = 關閉）
- `--capital N`：初始資金（預設 10000）
- `--params '{}'`：策略參數 JSON（覆蓋預設值）

## 執行步驟

1. 確認 server 正在運行（port 8000），如果沒有就啟動它：
   ```bash
   cd backend && nohup python app.py 8000 > /dev/null 2>&1 &
   ```
   等 2 秒確認啟動成功：
   ```bash
   curl -s http://localhost:8000/api/strategies > /dev/null && echo "Server OK"
   ```

2. 如果用戶指定了策略參數或想知道可用參數，先查策略 schema：
   ```bash
   curl -s http://localhost:8000/api/strategies | python -m json.tool
   ```

3. 呼叫 API 執行回測：
   ```bash
   curl -s -X POST http://localhost:8000/api/backtest/run \
     -H "Content-Type: application/json" \
     -d '{
       "symbol": "$SYMBOL",
       "interval": "$INTERVAL",
       "start_date": "$START",
       "end_date": "$END",
       "strategy_name": "$STRATEGY",
       "strategy_params": {},
       "initial_capital": 10000,
       "stop_loss_pct": 0,
       "take_profit_pct": 0
     }'
   ```

4. 解析結果並呈現關鍵指標表格：

   **核心指標：**
   | 指標 | 值 |
   |------|-----|
   | Total Return | X% ($X) |
   | Win Rate | X% |
   | Profit Factor | X |
   | Max Drawdown | X% |
   | Sharpe Ratio | X |
   | Sortino Ratio | X |
   | Total Trades | X |
   | Avg Win / Avg Loss | $X / $X |
   | Avg Holding Hours | X |
   | Max Consecutive Losses | X |

   **如果有止損/止盈：**
   - Signal Exits: X
   - Stop Loss Exits: X
   - Take Profit Exits: X

   **如果有空倉交易：**
   - Long Trades: X (win rate X%)
   - Short Trades: X (win rate X%)

5. 根據結果提供簡短建議：
   - 勝率 < 40% → 建議調整進出場條件
   - Max Drawdown > 30% → 建議加入止損或降低倉位
   - 交易數 < 10 → 樣本不足，建議延長回測區間
   - Sharpe < 0.5 → 風險調整後報酬偏低
   - Profit Factor < 1 → 策略虧損，需根本性調整

## 可用策略（9 個）

RSI, MACD, Bollinger Bands, MA Cross, Momentum Breakout, RSI+MACD Confluence, SuperTrend, Volume Breakout, Trend Rider

所有策略目前只發 BUY/SELL 信號（做多），引擎已支援 SHORT/COVER 但尚無策略使用。
