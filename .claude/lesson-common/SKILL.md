---
name: lesson-common
description: 回顧當前對話，萃取經驗教訓並寫入對應層級的 CLAUDE.md。在完成複雜任務、修復棘手 bug、發現架構模式、或對話中反覆犯錯後應主動使用。使用方式：/lesson-common 或 /lesson-common packages/components-ui
---

# lesson-common

回顧當前對話中的錯誤嘗試、偵錯過程和解決方案，萃取可複用的經驗教訓，寫入對應層級的 CLAUDE.md。

## 參數

- `$ARGUMENTS`: 可選的目標路徑（例如：`packages/components-ui`、`apps/scatter`）
  - 如未指定，自動判斷當前對話涉及的主要目錄

## 執行流程

### Step 1: 回顧對話

掃描當前對話，識別以下模式：

**錯誤嘗試（Missteps）：**
- 嘗試了錯誤的方法後才找到正確解法
- 修改了錯誤的檔案
- 誤解了架構或資料流
- 遺漏了必要的連動修改

**偵錯洞察（Debug Insights）：**
- 問題的根本原因（root cause）
- 有效的偵錯路徑
- 誤導性的錯誤訊息

**架構發現（Architecture Discoveries）：**
- 模組之間的隱含依賴
- 未記錄的約定或慣例
- 常踩到的邊界條件

**工具與流程（Tooling & Workflow）：**
- 建置、測試、部署相關的注意事項
- 套件管理或版本相容性問題
- CI/CD 或開發環境的陷阱

### Step 2: 萃取教訓

將識別出的模式轉化為具體、可執行的規則。

**好的教訓：**
```
- 修改 shared package 的 export 後，必須同步更新所有消費端的 import
- pnpm workspace 中 peer dependency 版本衝突時，需在根目錄 pnpm-overrides 統一版本
```

**不好的教訓（太模糊）：**
```
- 要注意依賴關係
- 小心版本問題
```

### Step 3: 判斷寫入層級

根據教訓的適用範圍，決定寫入哪一層的 CLAUDE.md：

| 範圍 | 寫入位置 | 範例 |
|------|---------|------|
| 整個 repo 通用 | 根目錄 `CLAUDE.md` | commit 規範、monorepo 操作注意事項、共用工具鏈設定 |
| 特定 package | `packages/{name}/CLAUDE.md` | 該 package 的 API 慣例、建置注意事項 |
| 特定 app | `apps/{name}/CLAUDE.md` | 該 app 的路由結構、狀態管理規則 |
| 特定子目錄 | `{path}/CLAUDE.md` | 該目錄下的檔案組織慣例、模組互動規則 |

**判斷原則：**
- 如果教訓只在某個 package/app 內適用 → 寫入該目錄的 CLAUDE.md
- 如果教訓跨多個 package/app 適用 → 寫入根目錄 CLAUDE.md
- 如果教訓屬於某個子目錄的局部知識 → 寫入該子目錄的 CLAUDE.md

### Step 4: 寫入 CLAUDE.md

**寫入規則：**

1. **讀取目標 CLAUDE.md** — 先讀取完整內容
2. **檢查是否重複** — 如果已有類似規則，更新而非重複添加
3. **追加到「常見陷阱」區段** — 如果有此區段，追加到其中；如果沒有，在檔案末尾新增此區段
4. **保持簡潔** — 每條規則 1-2 行，避免過度描述
5. **標注來源** — 用 HTML 註解標記更新時間

**追加格式：**
```markdown
## 常見陷阱

<!-- 以下由 /lesson-common 自動萃取 -->
- **[分類]** 具體規則描述
```

### Step 5: 也寫入自動記憶

如果教訓具有跨 session 價值，同時更新 Claude 的自動記憶目錄：

路徑：當前專案的 memory 目錄（通常位於 `~/.claude/projects/` 下對應專案路徑的 `memory/` 子目錄）

- 如果 `MEMORY.md` 中還沒有相關項目，加入簡要提示
- 如果是詳細的技術模式，建立專門的 topic file（例如 `monorepo-patterns.md`）

### Step 6: 輸出摘要

```
============================================================
/lesson-common 萃取報告
============================================================

本次對話萃取了 {N} 條教訓：

1. [CLAUDE.md] 新增：pnpm workspace 的 peer dependency 處理規則
2. [packages/components-ui/CLAUDE.md] 更新：元件 export 命名慣例
3. [apps/scatter/CLAUDE.md] 新增：SSR hydration 注意事項

已更新檔案：
- CLAUDE.md
- packages/components-ui/CLAUDE.md

記憶更新：
- memory/MEMORY.md — 新增 monorepo 依賴管理提示
============================================================
```

## 注意事項

1. **只記錄已驗證的教訓** — 不記錄猜測或未確認的結論
2. **避免記錄一次性的操作細節** — 只記錄可複用的模式
3. **不刪除現有規則** — 只追加或更新，除非明確發現現有規則有誤
4. **保持 CLAUDE.md 精簡** — 每個檔案的「常見陷阱」區段建議不超過 15 條
5. **語言跟隨專案** — CLAUDE.md 的語言應與該專案既有的 CLAUDE.md 風格一致，若無既有檔案則使用中文
