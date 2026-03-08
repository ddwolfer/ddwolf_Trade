# /optimize — AI 策略參數優化

自動搜尋指定策略的最佳參數組合，包含止損/止盈優化和 walk-forward 驗證。

## 使用方式

```
/optimize RSI BTCUSDT 1h 2024-01-01 2025-01-01
/optimize "MA Cross" ETHUSDT 4h
/optimize SuperTrend BTCUSDT 1h --with-sl-tp
```

## 參數解析

從 `$ARGUMENTS` 解析：
- 第 1 個：策略名稱（必填）
- 第 2 個：交易對（預設 BTCUSDT）
- 第 3 個：時間間隔（預設 1h）
- 第 4 個：起始日期（預設 2024-01-01）
- 第 5 個：結束日期（預設 2025-01-01）
- `--with-sl-tp`：同時優化止損/止盈百分比

## 執行步驟

### 1. 環境確認
確認 server 正在運行：
```bash
curl -s http://localhost:8000/api/strategies > /dev/null || (cd backend && nohup python app.py > /dev/null 2>&1 &)
```

### 2. 取得策略參數 Schema
```bash
curl -s http://localhost:8000/api/strategies
```
找到目標策略的 `parameters` 定義，確認每個參數的 `min`、`max`、`default`。

### 3. 生成參數組合

根據參數範圍生成 grid search 組合。每個參數取 3-5 個代表值：

**參數取值原則：**
- `int` 型：取 min、25%、50%（default）、75%、max
- `float` 型：取 min、default*0.5、default、default*1.5、max
- 總組合數 > 100 時 → 改用 random search（隨機取 60-80 組）

**如果帶 `--with-sl-tp`，額外加入：**
- `stop_loss_pct`: [0, 3, 5, 8, 10]
- `take_profit_pct`: [0, 5, 10, 15, 20]

### 4. 批次回測

用 `/api/backtest/compare` 執行（每次最多 20 個 config）：
```bash
curl -X POST http://localhost:8000/api/backtest/compare \
  -H "Content-Type: application/json" \
  -d '{"configs": [
    {"symbol":"BTCUSDT","interval":"1h","start_date":"2024-01-01","end_date":"2025-01-01",
     "strategy_name":"RSI","strategy_params":{"period":10,"overbought":70,"oversold":30},
     "stop_loss_pct":0,"take_profit_pct":0},
    ...
  ]}'
```

如果有多批，依序執行並合併結果。

### 5. 篩選與排序

**剔除條件（任一命中即排除）：**
- Max Drawdown > -30%
- 交易次數 < 10（樣本不足）
- Win Rate < 20%（太低，可能邏輯有問題）

**排序權重：**
1. Sharpe Ratio（主要指標，風險調整報酬）
2. Profit Factor > 1.5 加分
3. Max Drawdown 絕對值越小越好

### 6. 呈現 Top 5 結果

以表格呈現 Top 5 參數組合：

| Rank | Parameters | Return% | WinRate% | Sharpe | MaxDD% | PF | Trades | SL/TP Exits |
|------|-----------|---------|----------|--------|--------|-----|--------|-------------|
| 1 | period=X, ob=Y | +X% | X% | X | -X% | X | X | SL:X TP:X |

### 7. Walk-Forward 驗證

用 Top 1 參數做 out-of-sample 驗證：
- In-sample: 前 70% 時間區間（例如 2024-01-01 ~ 2024-09-01）
- Out-of-sample: 後 30%（例如 2024-09-01 ~ 2025-01-01）

```
OOS 衰退率 = (IS_return - OOS_return) / abs(IS_return) * 100%
```

- 衰退率 < 30% → 參數穩健，可以使用
- 衰退率 30%~50% → 輕微過擬合，建議保守使用
- 衰退率 > 50% → 嚴重過擬合，建議用 Top 2 或 Top 3 重新驗證

### 8. 最終建議

輸出：
1. 推薦的最佳參數組合（含止損/止盈如適用）
2. 該組合的完整績效指標
3. Walk-Forward 驗證結論
4. 是否建議實際使用（基於 OOS 衰退率）

## 注意事項

- 每次 compare API 最多放 20 個 config（server 限制）
- 參數組合超過 100 個時用 random search，超過 200 個時取 100 個隨機樣本
- 止損/止盈優化會大幅增加組合數（×25），謹慎使用
- 合成數據（Binance API 不可用時的 fallback）的優化結果僅供參考
- 過擬合是最大風險 — 永遠要做 walk-forward 驗證
