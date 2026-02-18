# 🤖 CheeseDog AI Supervisor 介面文件

此文件專為 **上層 AI Agent (Supervisor)** 設計。
若您使用 AutoGen, LangChain, 或自建 Agent 來管理此交易系統，請將以下 **System Prompt** 與 **API文件** 提供給它。

---

## 🧠 System Prompt (給 Supervisor Agent)

```text
You are the "Risk Supervisor" for the CheeseDog High-Frequency Trading System.
Your goal is to correct the trading strategy provided by the "CheeseDog Trading Bot" and ensure capital preservation.

Your capabilities:
1. MONITOR: You can poll the system status via API to check PnL, Win Rate, and Server Health.
2. CONTROL: You can switch trading modes (Aggressive/Balanced/Conservative) based on market conditions.
3. EMERGENCY: You must STOP the system immediately if critical thresholds are breached.

Rules of Engagement:
- POLL FREQUENCY: Check system status every 15 minutes.
- WIN RATE ALERT: If "recent win rate" (last 50 trades) drops below 45%, switch to "Conservative" mode.
- CRITICAL STOP: If "recent win rate" drops below 35% OR "drawdown" > 10%, call "Emergency Stop" immediately.
- HEALTH CHECK: If the API returns 500 or times out, log a critical alert.

Access Information:
- Base URL: http://localhost:8888 (Adjust if remote)
- Auth: No auth required for read-only. Write actions may require configuration.
```

---

## 🛠️ API 工具箱 (Tool Definitions)

請將以下 API 定義提供給 Agent 的 Tool Use 功能：

### 1. 🔍 監控系統狀態 (Monitor)
**GET** `/api/status`
- **用途**: 獲取全域市場狀態、最新價格、當前信號。
- **回應關鍵欄位**:
  - `btc_price`: BTC 價格
  - `signal`: 當前信號 (BUY_UP / SELL_DOWN / NEUTRAL)
  - `performance`: 簡單績效摘要

### 2. 📊 獲取詳細績效 (Performance)
**GET** `/api/simulation/stats`
- **用途**: 獲取詳細的帳戶餘額、勝率、盈虧。
- **回應關鍵欄位**:
  - `win_rate`: 勝率 (例如 55.2)
  - `total_pnl`:總盈虧 (USDC)
  - `balance`: 當前餘額
  - `open_trades`: 持倉數量
  - `engine_type`: "simulation" 或 "live"

### 3. Change Trading Mode (Control)
**POST** `/api/mode/{mode}`
- **用途**: 切換交易策略模式。
- **參數**:
  - `mode`: "aggressive" | "balanced" | "conservative"
- **範例**: `POST /api/mode/conservative`

### 4. 🚨 緊急停止 (Emergency)
**POST** `/api/trading/emergency_stop` (需確認此端點是否已實作，若無則需透過 SSH/Process Kill)
- **目前建議**: 若發生緊急狀況，建議 Agent 透過 SSH 執行 `pm2 stop cheesedog` 或發送警報給人類管理員。

### 5. 📜 讀取近期交易
**GET** `/api/trades?limit=10`
- **用途**: 分析最近 10 筆交易的結果。
- **回應**: 交易列表，包含 `pnl`, `status`, `direction`。

---

## 💡 Agent 決策範例 (Reasoning Trace)

**Scenario 1: 市場波動劇烈，連續虧損**
1. Agent 呼叫 `GET /api/simulation/stats` 發現 `win_rate` 從 55% 掉到 42%。
2. Agent 判斷觸發 "WIN RATE ALERT"。
3. Agent 呼叫 `POST /api/mode/conservative` 將模式切換為保守。
4. Agent 記錄日誌: "Win rate drop detected. Switched to Conservative mode."

**Scenario 2: 系統異常**
1. Agent 呼叫 `GET /api/status` 失敗 (Connection Refused)。
2. Agent 再次重試 (Retry) 失敗。
3. Agent 發送 "CRITICAL ALERT: CheeseDog System DOWN" 給管理員 (透過 Email/Discord Webhook)。
