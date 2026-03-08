# /optimize — AI 策略參數優化

自動搜尋指定策略的最佳參數組合。

## 使用方式

```
/optimize RSI BTCUSDT 1h 2024-01-01 2025-01-01
```

## 執行步驟

1. 確認 server 正在運行

2. 取得策略的參數 schema：
   ```bash
   curl -s http://localhost:8000/api/strategies
   ```

3. 根據參數範圍，生成參數組合（grid search）。
   例如 RSI 策略：
   - period: [10, 14, 20, 25]
   - overbought: [65, 70, 75, 80]
   - oversold: [20, 25, 30, 35]

4. 用 `/api/backtest/compare` 批次執行：
   ```bash
   curl -X POST http://localhost:8000/api/backtest/compare \
     -H "Content-Type: application/json" \
     -d '{"configs": [
       {"symbol":"BTCUSDT","strategy_name":"RSI","strategy_params":{"period":10,"overbought":70,"oversold":30}},
       {"symbol":"BTCUSDT","strategy_name":"RSI","strategy_params":{"period":14,"overbought":70,"oversold":30}},
       ...
     ]}'
   ```

5. 按以下優先順序排序結果：
   - Sharpe Ratio（風險調整後報酬）
   - 剔除 Max Drawdown > -30% 的組合
   - 剔除交易次數 < 10 的組合（樣本不足）

6. 呈現 Top 5 參數組合的完整指標

7. 建議最佳參數並提供 walk-forward 驗證建議：
   - 用 2024-01-01 ~ 2024-09-01 做 in-sample 優化
   - 用 2024-09-01 ~ 2025-01-01 做 out-of-sample 驗證
   - 如果 out-of-sample 表現顯著下降，警告過度擬合

## 注意事項

- 參數組合太多時（>100），改用 random search
- 每次 compare 最多放 20 個 config，避免 server 過載
- 結果要考慮過度擬合風險，一定要做 out-of-sample 驗證
