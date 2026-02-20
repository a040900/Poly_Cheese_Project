---
description: 設定與管理 CheeseDog (乳酪のBTC預測室) 的 Telegram Bot，用於遠端操控與 HITL 提案審核
---

# 🧀 CheeseDog Telegram Bot 設定指南

本 Skill 指引 AI Agent 如何為 CheeseDog 系統建立並配置 Telegram Bot，
實現 Human-in-the-Loop (HITL) 遠端審核功能。

---

## 📋 前置條件

- CheeseDog 後端已在 VPS 上運行
- 後端 API 可達（預設: `http://localhost:8000`）
- 使用者已擁有 Telegram 帳號

## 🔧 設定流程

### Step 1: 建立 Telegram Bot

1. 在 Telegram 中搜尋 **@BotFather** 並啟動對話
2. 發送指令: `/newbot`
3. 依照 BotFather 提示：
   - 輸入 Bot 名稱（例如：`乳酪BTC預測室`）
   - 輸入 Bot 使用者名稱（必須以 `bot` 結尾，例如：`cheesedog_btc_bot`）
4. BotFather 會回覆一組 **Bot Token**，格式如：`123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
5. **保存此 Token**

### Step 2: 取得 Chat ID

使用者需要知道自己的 Telegram Chat ID，有兩種方式：

**方式 A: 透過 Bot 自動取得**
1. 在 Telegram 搜尋剛建立的 Bot
2. 點擊「Start」啟動對話
3. Bot 會自動回覆你的 Chat ID（CheeseDog Bot 支援 `/start` 自動記錄）

**方式 B: 透過 @userinfobot**
1. 在 Telegram 搜尋 `@userinfobot`
2. 點擊「Start」，它會回覆你的 User ID
3. 這個 User ID 就是你的 Chat ID

### Step 3: 透過 API 設定 CheeseDog

使用 CheeseDog 的 REST API 來動態配置：

```bash
# Step 3.1: 設定 Bot Token 和 Chat ID，並啟用
curl -X POST http://<CHEESEDOG_HOST>:8000/api/telegram/configure \
  -H "Content-Type: application/json" \
  -d '{
    "bot_token": "<你的 BOT TOKEN>",
    "chat_id": "<你的 CHAT ID>",
    "enabled": true
  }'
```

**API 端點**: `POST /api/telegram/configure`  
**Body 參數**:

| 參數       | 類型   | 說明                                       |
|-----------|--------|-------------------------------------------|
| bot_token | string | Telegram Bot Token (從 BotFather 取得)      |
| chat_id   | string | 你的 Telegram Chat ID                      |
| enabled   | bool   | 是否啟用 Bot (設為 true 後自動啟動)           |

**回傳範例**:
```json
{
  "success": true,
  "changes": ["bot_token 已更新", "chat_id 已設定為 987654321", "enabled 已設定為 True", "Bot 已自動啟動"],
  "status": {
    "available": true,
    "enabled": true,
    "running": true,
    "token_set": true,
    "chat_id": "987654321",
    "stats": {...}
  }
}
```

### Step 4: 驗證配置

```bash
# 發送測試訊息
curl -X POST http://<CHEESEDOG_HOST>:8000/api/telegram/test

# 預期回覆
# {"success": true}
```

如果使用者的 Telegram 收到了一條測試訊息，表示配置完成！

### Step 5: 安裝 Python 依賴（如未安裝）

```bash
pip install python-telegram-bot
```

---

## 🤖 可用的 Telegram 指令

| 指令 | 說明 |
|------|------|
| `/start` | 初始化 Bot，自動記錄 Chat ID |
| `/help` | 查看所有可用指令 |
| `/status` | 查看系統狀態（Navigator, AuthMode, 佇列統計） |
| `/proposals` | 列出待審核提案（含 Inline 核准/拒絕按鈕） |
| `/report` | 查看完整績效報告 |
| `/mode` | 查看當前交易模式 |
| `/setnavigator <值>` | 設定 AI Navigator (`openclaw` / `internal` / `none`) |
| `/setauth <值>` | 設定授權模式 (`auto` / `hitl` / `monitor`) |

---

## 📡 API 端點一覽

### Telegram API

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET  | `/api/telegram/status`    | 取得 Bot 狀態 |
| POST | `/api/telegram/configure` | 動態設定 Token/ChatID/Enabled |
| POST | `/api/telegram/test`      | 發送測試訊息 |

### Supervisor API（相關）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET  | `/api/supervisor/status`                         | 系統授權狀態 |
| GET  | `/api/supervisor/proposals`                      | 待審核提案列表 |
| GET  | `/api/supervisor/proposals/{id}`                 | 提案詳情 |
| POST | `/api/supervisor/proposals/{id}/approve`         | 核准提案 (也可透過 Telegram 操作) |
| POST | `/api/supervisor/proposals/{id}/reject`          | 拒絕提案 (也可透過 Telegram 操作) |
| GET  | `/api/supervisor/history`                        | 提案歷史 |
| POST | `/api/supervisor/settings`                       | 更新 Navigator/AuthMode |

---

## ⚙️ 環境變數

以下環境變數可在 `.env` 中設定（也可透過 API 動態設定）：

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
TELEGRAM_ENABLED=true

# Phase 4: Supervisor
AI_NAVIGATOR=internal        # openclaw | internal | none
AUTHORIZATION_MODE=hitl      # auto | hitl | monitor
```

---

## 🔔 自動推播行為

Bot 在啟動後會自動訂閱以下事件：

| 事件 | 觸發時機 | 推播內容 |
|------|---------|---------|
| `supervisor.proposal_created` | AI 建議進入 HITL 佇列 | 提案摘要 + Approve/Reject 按鈕 |
| `supervisor.proposal_resolved` (auto_approved) | 緊急安全閥觸發 | 🚨 強提醒告警 |
| `supervisor.auto_executed` | AUTO 模式自動執行 | ⚡ 執行通知 |

---

## 🛠️ 常見問題

### Q: Bot 無法啟動？
1. 確認 `python-telegram-bot` 已安裝 (`pip install python-telegram-bot`)
2. 確認 Token 格式正確
3. 確認 VPS 可以連到 `api.telegram.org`（部分地區可能需要代理）

### Q: 收不到推播？
1. 確認 Chat ID 正確 (`GET /api/telegram/status` 查看)
2. 確認已對 Bot 發送 `/start` 指令
3. 確認 `TELEGRAM_ENABLED=true`

### Q: 如何更換 Token？
呼叫 `POST /api/telegram/configure` 傳入新的 `bot_token` 即可，Bot 會重啟。

---

## 📐 架構概覽

```
使用者 (Telegram App)
    ↕️ Inline Buttons / 指令
Telegram Bot API (python-telegram-bot)
    ↕️ MessageBus 事件訂閱
CheeseDog Supervisor Module
    ├── AuthorizationManager (路由決策)
    ├── ProposalQueue (提案生命週期)
    └── LLMAdvisor (AI 建議處理)
```
