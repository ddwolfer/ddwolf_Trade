# /backtest — 快速執行回測

執行一次策略回測並顯示結果摘要。

## 使用方式

```
/backtest RSI BTCUSDT 1h 2024-01-01 2025-01-01
/backtest MACD ETHUSDT 4h 2024-06-01 2025-01-01
```

## 執行步驟

1. 確認 server 正在運行（port 8000），如果沒有就啟動它：
   ```bash
   cd backend && nohup python app.py 8000 &
   ```

2. 呼叫 API 執行回測：
   ```bash
   curl -s -X POST http://localhost:8000/api/backtest/run \
     -H "Content-Type: application/json" \
     -d '{
       "symbol": "$SYMBOL",
       "interval": "$INTERVAL",
       "start_date": "$START",
       "end_date": "$END",
       "strategy_name": "$STRATEGY"
     }'
   ```

3. 解析結果並呈現關鍵指標：
   - Total Return %
   - Win Rate %
   - Max Drawdown %
   - Sharpe Ratio
   - Profit Factor
   - Total Trades
   - Avg Win / Avg Loss

4. 如果結果不理想，建議調整參數方向。
