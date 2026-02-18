# 🧀 CheeseDog V3 (Step 16) 升級指南

本指南將協助您將 VPS 上的 V2.0 版本升級到 V3.2，主要包含 **實盤交易引擎整合** 與 **Unified Trading Interface**。

---

## 🚀 快速升級指令 (Copy-Paste)

請依序在您的 VPS 終端機執行以下指令：

### 1. 更新程式碼
```bash
# 進入您的專案目錄
cd /path/to/cheesedog 

# 拉取最新程式碼 (如果是 git repo)
git pull origin main

# 如果沒有 git，請手動上傳新檔案覆蓋舊檔案
```

### 2. 安裝新依賴
V3 新增了 `py-clob-client` 用於 Polymarket 實盤交易。
```bash
pip install -r backend/requirements.txt
```

### 3. 資料庫遷移 (重要！)
V3 在 `trades` 表新增了 `trade_type` (區分實盤/模擬) 等欄位，必須執行遷移腳本以保留舊數據。
```bash
python backend/scripts/db_migrate_v2_to_v3.py
```
> 如果看到 `✅ 資料庫遷移完成！` 代表成功。

### 4. 更新設定檔 (.env)
如果您打算啟用實盤交易，請編輯 `.env` 檔案加入以下內容：
```bash
nano .env
```
新增/修改以下設定：
```ini
# ── 實盤交易設定 (V3 新增) ──────────────
# ⚠️ 警告：請妥善保管私鑰，切勿外洩！
WALLET_PRIVATE_KEY=<您的 Polygon 私鑰>
PM_LIVE_ENABLED=false  # 若要開啟實盤請改為 true
PM_LIVE_MAX_SINGLE_TRADE=10.0   # 單筆最大金額 (USDC)
PM_LIVE_MAX_TOTAL_TRADED=100.0  # 累計最大金額 (USDC)
```
> **建議**：初次升級先保持 `PM_LIVE_ENABLED=false` 進行觀察。

### 5. 重啟服務
根據您的部署方式重啟服務：

**使用 PM2:**
```bash
pm2 restart cheesedog
```

**使用 Systemd:**
```bash
sudo systemctl restart cheesedog
```

**使用 nohup:**
```bash
pkill -f "python -m app.main"
nohup python -m app.main > logs/cheesedog.log 2>&1 &
```

---

## ⚠️ 常見問題

### Q: 我需要提供什麼給 AI Agent 嗎？
A: 
- **對於程式碼 (Antigravity)**：不需要，程式碼已含所有邏輯。
- **對於機器人本身 (CheeseDog Bot)**：
  - 如果只跑 **模擬模式**：不需要提供任何新東西。
  - 如果要跑 **實盤模式**：必須提供 **Polygon 錢包私鑰 (Private Key)** 並確保錢包內有 **USDC** 和少許 **MATIC** (雖 Polymarket 免 Gas，但建議備用)。

### Q: 如何確認升級成功？
查看日誌：
```bash
tail -f logs/cheesedog.log
```
如果看到 `🟢 模擬交易引擎已啟動` (或 `🟢 實盤交易引擎已啟動`) 且沒有報錯 `Database Error`，即代表成功。

### Q: 我的舊歷史數據會不見嗎？
執行 `db_migrate_v2_to_v3.py` 後，舊數據會被保留，並自動標記為 `simulation` (模擬交易)，不會遺失。

---

祝交易順利！🧀
