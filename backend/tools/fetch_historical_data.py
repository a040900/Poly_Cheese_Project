"""
🧀 乳酪のBTC預測室 — 真實歷史數據獲取工具
=====================================================

從 Binance API 獲取真實的 BTCUSDT 歷史 K 線數據 (1 分鐘)，
並生成 market_snapshots 供回測使用。

功能:
    1. 下載最近 N 小時的真實 K 線 (OHLCV)
    2. 使用真實數據計算技術指標 (EMA, RSI, MACD, BB...)
    3. 模擬 Polymarket 合約價格 (基於真實 BTC 波動)
    4. 寫入 market_snapshots 到資料庫

使用方式:
    cd backend
    python tools/fetch_historical_data.py --hours 24
"""

import sys
import os
import time
import json
import logging
import random
import requests
from datetime import datetime, timedelta

# ── 加入專案路徑 ────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db
from app.indicators import technical

# ── 日誌設定 ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetcher")

BINANCE_API_URL = "https://api.binance.com/api/v3/klines"

def fetch_binance_klines(symbol="BTCUSDT", interval="1m", limit=1000):
    """從 Binance 獲取 K 線數據"""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(BINANCE_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Binance kline format:
        # [Open time, Open, High, Low, Close, Volume, Close time, ...]
        klines = []
        for k in data:
            klines.append({
                "t": k[0] / 1000,
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
            })
        return klines
    except Exception as e:
        logger.error(f"❌ 無法獲取 Binance 數據: {e}")
        return []

def generate_snapshots_from_real_data(hours: int = 24):
    """
    使用真實 K 線數據生成 market_snapshots
    """
    logger.info(f"📥 從 Binance 下載最近 {hours} 小時 BTC 數據...")
    
    # 計算需要多少根 K 線 (每分鐘一根)
    limit = min(hours * 60, 1000)  # Binance 單次最多 1000 根
    # 如果需要更多，這裡簡化處理只抓最近 1000 分鐘 (約 16 小時)
    # 若要完整 24h+，需分頁處理，但 1000 根足夠校準 demo
    klines = fetch_binance_klines(limit=limit)

    if not klines:
        logger.error("❌ 無法獲取 K 線數據，終止。")
        return

    logger.info(f"✅ 成功獲取 {len(klines)} 根 K 線")
    
    # 準備寫入資料庫
    snapshots_added = 0
    
    # 用於計算指標的窗口
    window = []

    for i, k in enumerate(klines):
        window.append(k)
        # 保持窗口大小
        if len(window) > 100:
            window.pop(0)
            
        # 至少需要 30 根 K 線才開始計算指標
        if len(window) < 30:
            continue

        price = k["c"]
        ts = k["t"]

        # 1. 計算真實技術指標
        indicators = {
            "ema": {}, "rsi": {}, "macd": {}, "bb": {}, "ha": {}
        }
        
        # EMA
        ema_s, ema_l = technical.ema_cross(window)
        if ema_s and ema_l:
            indicators["ema"] = {"short": ema_s, "long": ema_l}

        # RSI
        rsi_val = technical.rsi(window)
        if rsi_val:
            indicators["rsi"] = {"value": rsi_val}

        # MACD
        m, s, h = technical.macd(window)
        if h is not None:
            indicators["macd"] = {"histogram": h}

        # BB
        bb = technical.bollinger_bands(window)
        if bb:
            indicators["bb"] = bb

        # HA
        streak = technical.ha_streak(window)
        indicators["ha"] = {"streak": streak}

        # 2. 模擬 Polymarket 價格 (基於真實波動)
        # 這裡只能模擬，因為沒有 PM 歷史數據
        # 假設: 趨勢強時 PM 價格會偏離 0.5
        bias = 0.5
        if ema_s and ema_l:
             diff_pct = (ema_s - ema_l) / ema_l * 100
             bias += diff_pct * 2.0  # 放大趨勢影響
        
        bias = max(0.05, min(0.95, bias))
        pm_up = bias
        pm_down = 1.0 - bias
        
        # 加入隨機雜訊模擬 Spread
        pm_up += random.gauss(0, 0.01)
        pm_down += random.gauss(0, 0.01)

        # 3. 建構 Snapshot
        snapshot = {
            "timestamp": ts,
            "btc_price": price,
            "pm_up_price": round(pm_up, 4),
            "pm_down_price": round(pm_down, 4),
            "chainlink_price": price, # 簡化
            "bias_score": 0, # 讓回測引擎自己算
            "signal": "NEUTRAL", # 讓回測引擎自己算
            "trading_mode": "balanced",
            "indicators": indicators,
        }

        db.save_market_snapshot(snapshot)
        snapshots_added += 1

    logger.info(f"✅ 已將 {snapshots_added} 筆真實市場快照寫入資料庫")
    logger.info(f"   時間範圍: {datetime.fromtimestamp(klines[0]['t'])} -> {datetime.fromtimestamp(klines[-1]['t'])}")
    logger.info(f"   價格範圍: ${min(k['l'] for k in klines):,.2f} - ${max(k['h'] for k in klines):,.2f}")

def clear_snapshots():
    """清空 market_snapshots 表"""
    logger.warning("🗑️ 正在清空 market_snapshots 表...")
    with db._connect() as conn:
        conn.execute("DELETE FROM market_snapshots")
        conn.commit()
    logger.info("✅ 已清空所有舊快照")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="真實歷史數據獲取工具")
    parser.add_argument("--hours", type=int, default=16, help="獲取最近 N 小時數據 (Max ~16h via public API)")
    parser.add_argument("--clear", action="store_true", help="執行前先清空舊數據")
    args = parser.parse_args()

    if args.clear:
        clear_snapshots()

    generate_snapshots_from_real_data(hours=args.hours)
