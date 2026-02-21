"""
🧀 CheeseDog - 全域設定檔
所有系統常數、環境變數、指標參數皆在此集中管理。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── 載入環境變數 ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# ═══════════════════════════════════════════════════════════════
# 系統設定
# ═══════════════════════════════════════════════════════════════
APP_NAME = "乳酪のBTC預測室 — Polymarket Intelligent Trading Assistant"
VERSION = "3.3.0"
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8888"))
# 反向代理子路徑（如 "/polycheese"），末尾不含 /，直接部署時留空
# VPS Tailscale Serve 部署時在 .env 設為 ROOT_PATH=/polycheese
ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "cheesedog.db"

# 確保目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# Binance 設定
# ═══════════════════════════════════════════════════════════════
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_WS = "wss://stream.binance.com/stream"
BINANCE_REST = "https://api.binance.com/api/v3"
BINANCE_SYMBOL = "BTCUSDT"

# 訂單簿設定
OB_LEVELS = 20              # 訂單簿深度層級
OB_POLL_INTERVAL = 5        # 輪詢間隔（秒）— 原為 2 秒，降低 CPU 負載

# 交易數據保留
TRADE_TTL = 600             # 保留最近 10 分鐘交易數據
TRADE_MAX_BUFFER = 2000     # 交易數據最大緩衝（降低以減少 CPU 用量）

# K 線設定
KLINE_INTERVAL = "1m"       # K 線時間間隔
KLINE_MAX = 150             # 記憶體中最大 K 線數量
KLINE_BOOT = 100            # 啟動時載入的歷史 K 線數

# ═══════════════════════════════════════════════════════════════
# Polymarket 設定
# ═══════════════════════════════════════════════════════════════
PM_GAMMA_API = "https://gamma-api.polymarket.com/events"
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PM_SERIES_SLUG = os.getenv("POLYMARKET_SERIES_SLUG", "btc-up-or-down-15m")
PM_AUTO_SELECT = os.getenv("POLYMARKET_AUTO_SELECT_LATEST", "true").lower() == "true"
PM_POLL_INTERVAL = 5        # REST API 輪詢間隔（秒）

# ═══════════════════════════════════════════════════════════════
# Chainlink / Polygon 設定
# ═══════════════════════════════════════════════════════════════
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://lb.drpc.live/polygon/AnwbZ8L9jEnOnCICP7S8z6GiDO16DtwR8blu-uF7NYYO")
CHAINLINK_BTC_USD_AGGREGATOR = os.getenv(
    "CHAINLINK_BTC_USD_AGGREGATOR",
    "0xc907E116054Ad103354f2D350FD2514433D57F6f"
)
CHAINLINK_POLL_INTERVAL = 30  # Chainlink 價格輪詢間隔（秒）

# Chainlink Aggregator V3 ABI（精簡版，僅需 latestRoundData）
CHAINLINK_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ═══════════════════════════════════════════════════════════════
# 訂單簿指標參數
# ═══════════════════════════════════════════════════════════════
OBI_BAND_PCT = 1.0          # OBI 計算時中價兩側帶寬百分比
OBI_THRESH = 0.10           # OBI 信號閾值（±10%）
WALL_MULT = 5               # 掛單牆判定倍數（大於均值 N 倍）
DEPTH_BANDS = [0.1, 0.5, 1.0]  # 流動性深度計算帶寬（%）

# ═══════════════════════════════════════════════════════════════
# 成交量指標參數
# ═══════════════════════════════════════════════════════════════
CVD_WINDOWS = [60, 180, 300]    # CVD 窗口（秒）: 1m/3m/5m
DELTA_WINDOW = 60               # 短線 Delta 窗口（秒）
VP_BINS = 30                    # 成交量分佈桶數
VP_SHOW = 9                     # 成交量分佈顯示行數

# ═══════════════════════════════════════════════════════════════
# 技術分析指標參數
# ═══════════════════════════════════════════════════════════════
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 5
EMA_LONG = 20
HA_COUNT = 8                # Heikin Ashi 顯示蠟燭數

# ═══════════════════════════════════════════════════════════════
# 趨勢偏差評分權重（Phase 3 Step 13: 真實數據校準 2026-02-19）
# ═══════════════════════════════════════════════════════════════
# 每個指標對最終綜合趨勢分數的最大貢獻度
# 校準數據: marketprice_(1).db (3 Days Real Data, 2026-02-16 ~ 19)
# 校準結果: PnL +19.1% | WinRate=48.3% | Trades=89
# 策略風格: 高波動適應型 (High MACD Momentum + High RSI Reversion)
BIAS_WEIGHTS = {
    "ema":    5,   # EMA 交叉（降低權重，減少滯後）
    "obi":    4,   # 訂單簿失衡
    "macd":  10,   # MACD Histogram（大幅提升動能權重）★ 新核心
    "cvd":    5,   # CVD 5 分鐘方向
    "ha":    12,   # Heikin-Ashi 連續方向 ★ 趨勢核心
    "vwap":   7,   # 價格 vs VWAP
    "rsi":    8,   # RSI 超買/超賣（提升靈敏度）
    "bb":     8,   # Bollinger Band %B（波動率維度）
    "poc":    3,   # 價格 vs POC（成交量集中點）
    "walls":  1,   # 買牆 − 賣牆
}
# 權重總和 = 54；偏差分數 = (原始總和 / 54) * 100，夾緊在 ±100

# ═══════════════════════════════════════════════════════════════
# Phase 5: 情緒因子設定 (Sentiment Factor — Hybrid Decision Engine)
# ═══════════════════════════════════════════════════════════════
# 利用 Polymarket 合約價格與 Binance 技術面的「乖離」來量化市場情緒。
# 當 Polymarket 定價遠超技術面合理機率 → 貪婪 (FOMO)
# 當 Polymarket 定價遠低於技術面合理機率 → 恐懼 (Panic)
SENTIMENT_CONFIG = {
    # 極端情緒閾值：超過此值才觸發衰減/放大
    "extreme_threshold": 60,       # |sentiment_score| > 60 才介入

    # 衰減上限：即使極度貪婪，最多只把分數壓到原始的 N%
    "max_decay_pct": 0.10,         # 最多壓到原始的 10%（不會完全歸零）

    # 反向增益上限：極度恐慌時，最多放大原始分數的 N 倍
    "max_boost_multiplier": 1.3,   # 最多 1.3 倍（不會無限放大）

    # 合理機率的 Sigmoid 斜率（越大 → 隱含機率從 0→1 變化越陡）
    "fair_prob_steepness": 8.0,    # 控制 BTC 距離目標的敏感度
}

# ═══════════════════════════════════════════════════════════════
# 交易模式定義（Phase 3 P1: 5 級連續光譜）
# ═══════════════════════════════════════════════════════════════
# 等級排列: defensive < conservative < balanced < aggressive < ultra_aggressive
# Agent 可根據市場狀態（MARKET_REGIME）自動選擇最適合的模式
TRADING_MODES = {
    "ultra_aggressive": {
        "name": "超激進 (Ultra Aggressive)",
        "description": "極短線趨勢追蹤，高頻交易，需要極強趨勢才有利",
        "signal_threshold": 15,      # 極低門檻，幾乎見信號就進
        "max_position_pct": 0.40,    # 單筆最大倉位 40%
        "stop_loss_pct": 0.20,       # 寬止損
        "take_profit_pct": 0.25,     # 高止盈
        "sentiment_sensitivity": 0.0,  # Phase 5: 不受情緒影響（追動能）
        "indicator_weights_multiplier": {
            "ema": 1.5, "obi": 0.8, "macd": 0.6,
            "cvd": 1.5, "ha": 0.4, "vwap": 0.5,
            "rsi": 0.3, "bb": 0.4, "poc": 0.3, "walls": 1.2,
        },
        "regime_affinity": ["strong_trend"],  # 適合的市場狀態
    },
    "aggressive": {
        "name": "積極 (Aggressive)",
        "description": "高風險高回報，快速進場，適合趨勢市",
        "signal_threshold": 25,
        "max_position_pct": 0.30,
        "stop_loss_pct": 0.15,
        "take_profit_pct": 0.20,
        "sentiment_sensitivity": 0.3,  # Phase 5: 輕微情緒過濾
        "indicator_weights_multiplier": {
            "ema": 1.2, "obi": 0.9, "macd": 0.8,
            "cvd": 1.2, "ha": 0.7, "vwap": 0.8,
            "rsi": 0.5, "bb": 0.6, "poc": 0.5, "walls": 1.0,
        },
        "regime_affinity": ["strong_trend", "mild_trend"],
    },
    "balanced": {
        "name": "平衡 (Balanced)",
        "description": "風險與回報平衡，全指標綜合判斷，適合多數行情",
        "signal_threshold": 40,
        "max_position_pct": 0.20,
        "stop_loss_pct": 0.10,
        "take_profit_pct": 0.15,
        "sentiment_sensitivity": 0.6,  # Phase 5: 中度情緒過濾
        "indicator_weights_multiplier": {
            "ema": 1.0, "obi": 1.0, "macd": 1.0,
            "cvd": 1.0, "ha": 1.0, "vwap": 1.0,
            "rsi": 1.0, "bb": 1.0, "poc": 1.0, "walls": 1.0,
        },
        "regime_affinity": ["mild_trend", "ranging"],
    },
    "conservative": {
        "name": "保守 (Conservative)",
        "description": "低風險穩健策略，需更多確認，適合震盪市",
        "signal_threshold": 55,
        "max_position_pct": 0.12,
        "stop_loss_pct": 0.07,
        "take_profit_pct": 0.12,
        "sentiment_sensitivity": 1.0,  # Phase 5: 全力情緒過濾
        "indicator_weights_multiplier": {
            "ema": 0.8, "obi": 1.2, "macd": 1.2,
            "cvd": 0.8, "ha": 1.2, "vwap": 1.2,
            "rsi": 1.4, "bb": 1.3, "poc": 1.0, "walls": 1.2,
        },
        "regime_affinity": ["ranging", "choppy"],
    },
    "defensive": {
        "name": "防禦 (Defensive)",
        "description": "極保守策略，僅在極強信號進場，適合高波動/不確定市場",
        "signal_threshold": 70,
        "max_position_pct": 0.08,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.08,
        "sentiment_sensitivity": 1.0,  # Phase 5: 全力情緒過濾
        "indicator_weights_multiplier": {
            "ema": 0.6, "obi": 1.5, "macd": 1.5,
            "cvd": 0.6, "ha": 1.5, "vwap": 1.5,
            "rsi": 1.8, "bb": 1.6, "poc": 1.2, "walls": 1.5,
        },
        "regime_affinity": ["choppy", "crash"],
    },
}

# ═══════════════════════════════════════════════════════════════
# 市場狀態自動偵測（Market Regime Detection）
# ═══════════════════════════════════════════════════════════════
# Agent 使用這些參數判斷當前市場狀態，自動選擇最適合的交易模式
MARKET_REGIME_CONFIG = {
    # 波動率閾值（基於 ATR 或 BB 寬度的百分比）
    "volatility_low": 0.3,     # < 0.3% → 低波動（盤整）
    "volatility_mid": 0.8,     # 0.3~0.8% → 中波動（正常）
    "volatility_high": 1.5,    # 0.8~1.5% → 高波動（趨勢）
    # > 1.5% → 極高波動（崩盤/暴漲）

    # 趨勢強度閾值（基於 ADX 或 EMA 斜率）
    "trend_weak": 15,          # ADX < 15 → 無趨勢
    "trend_mild": 25,          # 15~25 → 溫和趨勢
    "trend_strong": 40,        # > 25 → 強趨勢

    # 市場狀態 → 推薦模式映射
    "regime_mode_map": {
        "strong_trend": "aggressive",
        "mild_trend":   "balanced",
        "ranging":      "conservative",
        "choppy":       "defensive",
        "crash":        "defensive",
    },

    # 自動切換冷卻期（秒）— 避免頻繁切換模式
    "mode_switch_cooldown": 300,  # 5 分鐘
}

# ═══════════════════════════════════════════════════════════════
# Phase 3 P2: 風險管理設定 (Risk Management)
# ═══════════════════════════════════════════════════════════════
RISK_MANAGEMENT = {
    # ── Kelly Criterion 設定 ──────────────────────────────────
    "kelly_fraction": 0.5,         # Half-Kelly（更保守，降低破產風險）
    # Full-Kelly = 1.0（理論最優但波動極大）
    # Quarter-Kelly = 0.25（極保守）

    # ── 倉位比例限制 ──────────────────────────────────────────
    "min_position_pct": 0.02,      # 最小倉位 2%（避免交易太小沒意義）
    "max_position_pct": 0.35,      # 最大倉位 35%（全局硬上限）

    # ── Circuit Breaker 1: 日虧損上限 ─────────────────────────
    "daily_loss_limit_enabled": True,
    "daily_loss_limit_pct": 10.0,  # 日虧損超過 10% 觸發熔斷

    # ── Circuit Breaker 2: 連敗上限 ───────────────────────────
    "consecutive_loss_limit_enabled": True,
    "consecutive_loss_limit": 5,   # 連續虧損 5 筆觸發熔斷

    # ── Circuit Breaker 3: 最大回撤 ───────────────────────────
    "max_drawdown_limit_enabled": True,
    "max_drawdown_limit_pct": 20.0,  # 回撤超過 20% 觸發熔斷

    # ── Circuit Breaker 4: 日交易次數上限 ─────────────────────
    "daily_trade_limit_enabled": True,
    "daily_trade_limit": 30,       # 每日最多 30 筆交易

    # ── 熔斷冷卻時間 ──────────────────────────────────────────
    "circuit_breaker_cooldown": 1800,  # 熔斷後冷卻 30 分鐘
}

# ═══════════════════════════════════════════════════════════════
# 模擬交易設定
# ═══════════════════════════════════════════════════════════════
SIM_INITIAL_BALANCE = float(os.getenv("SIM_INITIAL_BALANCE", "1000.0"))

SIM_FEE_PCT = 0.001         # 模擬手續費 0.1%（Phase 1 簡化值）

# Phase 3: 信號冷卻期（同方向信號在 N 秒內不重複觸發）
SIGNAL_COOLDOWN_SECONDS = 120  # 2 分鐘冷卻

# Phase 3 Step 16: 實盤交易開關與安全設定
PM_LIVE_ENABLED = os.getenv("PM_LIVE_ENABLED", "false").lower() == "true"
PM_LIVE_MAX_SINGLE_TRADE = float(os.getenv("PM_LIVE_MAX_SINGLE_TRADE", "10.0"))
PM_LIVE_MAX_TOTAL_TRADED = float(os.getenv("PM_LIVE_MAX_TOTAL_TRADED", "100.0"))

# Phase 2: Polymarket 15m 市場浮動手續費（借鏡 NautilusTrader 文件）
# Buy 端手續費: 0.2% - 1.6%（從 Token 扣除）
# Sell 端手續費: 0.8% - 3.7%（從 USDC 扣除）
PM_FEE_BUY_RANGE = (0.002, 0.016)    # Buy 手續費範圍
PM_FEE_SELL_RANGE = (0.008, 0.037)   # Sell 手續費範圍
PM_FEE_BUY_DEFAULT = 0.005           # 預設 Buy 手續費 0.5%
PM_FEE_SELL_DEFAULT = 0.015          # 預設 Sell 手續費 1.5%

# Phase 2.1: 利潤過濾器 (Profit Filter)
# 開倉前先估算「扣掉手續費+價差後還有沒有賺頭」
PROFIT_FILTER_ENABLED = True                # 是否啟用利潤過濾器
PROFIT_FILTER_MAX_SPREAD_PCT = 0.05         # 最大允許 Spread 放寬至 5%（校準後調整）
PROFIT_FILTER_MIN_PROFIT_RATIO = 1.1        # 預期毛利需為來回手續費的 1.1 倍即可（校準後調整）
PROFIT_FILTER_MIN_TRADE_AMOUNT = 1.0        # 最低交易金額 (USDC)，低於此不交易

# ═══════════════════════════════════════════════════════════════
# 安全設定
# ═══════════════════════════════════════════════════════════════
PASSWORD_LENGTH = 6          # 隨機密碼長度
PASSWORD_EXPIRY = 300        # 密碼有效期（秒）

# ═══════════════════════════════════════════════════════════════
# Dashboard 設定
# ═══════════════════════════════════════════════════════════════
REFRESH_INTERVAL = 5         # 前端刷新間隔（秒）
WS_HEARTBEAT = 30           # WebSocket 心跳間隔（秒）

# ═══════════════════════════════════════════════════════════════
# AI 監控設定（自定義 OpenAI API） - Phase 3 P1 (User Request)
# ═══════════════════════════════════════════════════════════════
# 改由後端直接呼叫 OpenAI API 進行系統分析與建議
# 避免外部 Agent 頻繁呼叫導致 Token 浪費
AI_MONITOR_ENABLED = os.getenv("AI_MONITOR_ENABLED", "false").lower() == "true"
AI_MONITOR_INTERVAL = int(os.getenv("AI_MONITOR_INTERVAL", "900"))  # 15 分鐘
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")

# ═══════════════════════════════════════════════════════════════
# Phase 4: Hybrid Intelligence & Collaborative Architecture
# ═══════════════════════════════════════════════════════════════

# ── 導航員選擇 (Navigator Selection) ──────────────────────────
# 決定系統的 AI 戰略顧問來源。
# 注意：此設定影響的是「控制平面」(誰能下指令)，
#       「資料平面」(讀取數據的 API) 不受影響，永遠開放。
#
# 可選值:
#   "openclaw"  — OpenClaw 官方雲端大腦 (外部 AI)
#   "internal"  — 使用者自備 API Key 的內建 AI 引擎
#   "none"      — 純演算法模式，不接受任何 AI 指令
AI_NAVIGATOR = os.getenv("AI_NAVIGATOR", "internal")

# ── 授權模式 (Authorization Mode) ─────────────────────────────
# 定義 AI 導航員對系統的操作權限等級。
#
# 可選值:
#   "auto"      — God Mode: AI 建議直接執行 (高頻/夜間適用)
#   "hitl"      — Supervisor Mode: AI 僅能提案，需人類核准
#   "monitor"   — Monitor Only: AI 僅提供分析報告，不介入操作
AUTHORIZATION_MODE = os.getenv("AUTHORIZATION_MODE", "hitl")

# ── 提案佇列設定 (Proposal Queue) ─────────────────────────────
# HITL 模式下，AI 的操作建議會進入提案佇列等待人類審核。
PROPOSAL_QUEUE_CONFIG = {
    # 提案過期時間（秒）— 超時未審核自動標記 EXPIRED
    "expiry_seconds": 600,          # 10 分鐘

    # 佇列最大容量 — 滿了之後最舊的未處理提案自動過期
    "max_queue_size": 50,

    # 緊急提案自動執行 — HITL 模式下，若 AI 信心度 >= 此值
    # 且 action 為 PAUSE_TRADING 或 risk_level 為 CRITICAL，
    # 則繞過人工審核直接執行（安全閥設計）
    "emergency_auto_approve_confidence": 95,

    # 緊急行動白名單 — 這些 action 在滿足信心度門檻時可自動執行
    "emergency_actions": ["PAUSE_TRADING"],

    # 提案歷史保留數量（已處理的提案保留多少筆供查詢）
    "history_retention": 200,
}

# ── Telegram Bot 設定 ─────────────────────────────────────────
# 透過 Telegram Bot 進行 HITL 遠端審核。
# Token 和 Chat ID 可在運行後透過 API 動態設定。
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_NOTIFY_ON_PROPOSAL = True     # 新提案時推播通知
TELEGRAM_NOTIFY_ON_EMERGENCY = True    # 緊急安全閥觸發時推播
TELEGRAM_NOTIFY_ON_TRADE = True        # 交易執行時推播
TELEGRAM_HOURLY_REPORT = False         # 每小時簡報（預設關閉）
