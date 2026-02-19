# 🤖 CheeseDog AI Supervisor 介面文件

此文件專為 **上層 AI Agent (Supervisor)** 設計。
若您使用 AutoGen, LangChain, 或自建 Agent 來管理此交易系統，請將以下 **System Prompt** 與 **API文件** 提供給它。

---

## 🧠 System Prompt (給 Supervisor Agent)

```text
You are the "Risk Supervisor" for the CheeseDog Trading System.
Your goal is to monitor system health and adjust trading strategy based on market conditions.

Your capabilities:
1. MONITOR: Poll system status via /api/cro/compact (low token cost).
2. CONTROL: Switch trading modes (aggressive/balanced/conservative).
3. EMERGENCY: Stop the system if critical thresholds are breached.

Rules of Engagement:
- Use /api/cro/compact for routine checks (every 15-30 min). It returns ~300 tokens.
- Only use /api/cro/stats when you need detailed analysis (every 2-4 hours).
- NEVER use /api/llm/context for routine monitoring (high token cost).

Decision Matrix (based on /api/cro/compact response):
- If adv == "HOLD": Do nothing, log keep-alive.
- If adv == "SWITCH" && advTo == "con": POST /api/mode/conservative
- If adv == "SWITCH" && advTo == "agg": POST /api/mode/aggressive
- If adv == "PAUSE": POST /api/simulation/toggle (stop trading)
- If hp == 0: Log CRITICAL alert, notify human admin.

Access Information:
- Base URL: http://localhost:8888 (adjust for remote)
- Auth: No auth required for read-only.
```

---

## 🛠️ API 工具箱 (Tool Definitions)

### ⭐ 1. 精簡監控 (推薦, 低 Token)
**GET** `/api/cro/compact`
- **用途**: 高頻率監控，每 15-30 分鐘呼叫一次。
- **Token 消耗**: ~100-150 tokens (輸入) + ~50 tokens (輸出)
- **回應範例**:
```json
{
  "btc": 67250.35,
  "sig": "U",
  "sc": 42.5,
  "mode": "bal",
  "wr6h": 55.0,
  "wr24h": 52.3,
  "pnl": 15.82,
  "bal": 1015.82,
  "open": 1,
  "dd": 2.1,
  "closs": 0,
  "vol": "M",
  "liq": "G",
  "sprd": 1.25,
  "hp": 1,
  "adv": "HOLD"
}
```
- **Key 速查表**:

| Key | 含義 | 值域 |
|-----|------|------|
| `btc` | BTC 價格 | 數字 |
| `sig` | 信號方向 | U=看漲, D=看跌, N=中性 |
| `sc` | 信號分數 | -100 ~ +100 |
| `mode` | 交易模式 | ultra/agg/bal/con/def |
| `wr6h` | 近6h勝率% | 0-100 |
| `wr24h` | 近24h勝率% | 0-100 |
| `pnl` | 總盈虧 | USDC |
| `bal` | 帳戶餘額 | USDC |
| `open` | 未平倉數 | 整數 |
| `dd` | 最大回撤% | 0-100 |
| `closs` | 連續虧損 | 整數 |
| `vol` | 波動率 | L=低, M=中, H=高, X=極端 |
| `liq` | 流動性 | G=好, M=中, L=低, C=危機 |
| `sprd` | 平均 Spread% | 數字 |
| `hp` | 系統健康 | 1=OK, 0=異常 |
| `adv` | 建議行動 | HOLD/SWITCH/PAUSE |
| `advTo` | 建議模式 | agg/con (僅 adv=SWITCH 時) |

### 2. 詳細分析 (每 2-4 小時)
**GET** `/api/cro/stats`
- **用途**: 獲取詳細績效、市場狀態、多條建議。
- **Token 消耗**: ~500-800 tokens
- **適用**: 需要深度分析或撰寫日報時使用。

### 3. 模式切換
**POST** `/api/mode/{mode}`
- **參數**: `mode` = `aggressive` | `balanced` | `conservative` | `defensive`
- **範例**: `POST /api/mode/conservative`

### 4. 模擬交易開關
**POST** `/api/simulation/toggle`
- **用途**: 啟動/暫停模擬交易。

### 5. 帳戶統計
**GET** `/api/simulation/stats`
- **用途**: 獲取帳戶餘額、勝率、盈虧明細。

---

## 💡 Token 優化建議

### 監控策略分級

| 級別 | 頻率 | 端點 | Token/次 | Token/24h |
|------|------|------|----------|-----------|
| **常規監控** | 每 30 分鐘 | `/api/cro/compact` | ~200 | ~9,600 |
| **深度分析** | 每 4 小時 | `/api/cro/stats` | ~700 | ~4,200 |
| **總計** | | | | **~13,800** |

### 對比舊方案

| 方案 | Token/次 | 頻率 | Token/24h |
|------|----------|------|-----------|
| ❌ 舊: `/api/llm/context` + prompt | ~3,500 | 每 15 分 | **~336,000** |
| ✅ 新: compact + stats 分級 | ~200-700 | 分級 | **~13,800** |
| | | **節省** | **~96%** |

---

## � Agent 決策範例

**Scenario: 日常監控 (每 30 分鐘)**
```
1. GET /api/cro/compact
2. Response: {"btc":67250,"sig":"N","sc":5.2,"mode":"bal","wr6h":55,"adv":"HOLD","hp":1}
3. adv == "HOLD" && hp == 1 → 無需行動，記錄 log
```

**Scenario: 勝率下滑**
```
1. GET /api/cro/compact
2. Response: {"wr6h":38,"closs":5,"adv":"SWITCH","advTo":"con"}
3. adv == "SWITCH" → POST /api/mode/conservative
4. 記錄: "Win rate drop to 38%, switched to conservative."
```

**Scenario: 極端波動**
```
1. GET /api/cro/compact
2. Response: {"vol":"X","adv":"PAUSE","hp":1}
3. adv == "PAUSE" → POST /api/simulation/toggle (stop)
4. 記錄: "Extreme volatility detected. Trading paused."
5. 30 分鐘後再檢查，若 vol 回到 M/L → 恢復交易
```
