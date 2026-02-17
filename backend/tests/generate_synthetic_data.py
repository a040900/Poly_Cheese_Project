"""
🧀 CheeseDog - 合成市場數據生成器
生成模擬的 BTC 價格歷史數據（約 24 小時），
寫入 market_snapshots 表，供回測引擎和 Dashboard 使用。

產出：
    - ~1440 筆 market_snapshots（每分鐘一筆，模擬 24 小時）
    - BTC 價格區間: $95,000 - $98,000 (帶趨勢+隨機波動)
    - 含模擬指標分數、信號方向、交易模式
"""

import sys
import os
import math
import time
import json
import random

# 加入專案路徑
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db


def generate_synthetic_data(
    hours: int = 24,
    interval_sec: int = 60,
    base_price: float = 96500.0,
    volatility: float = 0.0003,
):
    """
    生成合成市場數據

    Args:
        hours: 模擬時間長度（小時）
        interval_sec: 每筆數據間隔（秒）
        base_price: BTC 起始價格
        volatility: 每步價格波動率
    """
    total_steps = int(hours * 3600 / interval_sec)
    start_ts = time.time() - (hours * 3600)

    print(f"🧀 CheeseDog 合成數據生成器")
    print(f"   模擬時間: {hours} 小時 ({total_steps} 筆快照)")
    print(f"   起始價格: ${base_price:,.2f}")
    print(f"   波動率: {volatility*100:.2f}%/步")
    print()

    price = base_price
    snapshots_added = 0

    # 週期參數 — 模擬真實市場的多週期波動
    trend_period = total_steps * 0.3       # 大趨勢週期
    swing_period = total_steps * 0.07      # 中期擺盪
    noise_amplitude = base_price * 0.001   # 短期雜訊幅度

    for i in range(total_steps):
        ts = start_ts + (i * interval_sec)

        # 多週期模擬價格運動
        trend = math.sin(2 * math.pi * i / trend_period) * base_price * 0.008
        swing = math.sin(2 * math.pi * i / swing_period) * base_price * 0.003
        noise = random.gauss(0, noise_amplitude)
        momentum = random.gauss(0, volatility * price)

        price = base_price + trend + swing + noise + momentum

        # 確保價格不要太離譜
        price = max(price, base_price * 0.97)
        price = min(price, base_price * 1.03)

        # 生成模擬指標分數
        bias_score = _generate_bias_score(i, total_steps, trend)
        signal = _score_to_signal(bias_score)
        trading_mode = random.choice(["aggressive", "balanced", "balanced", "conservative"])

        # 模擬 Polymarket UP/DOWN 價格
        up_price = _btc_to_pm_price(bias_score, "up")
        down_price = _btc_to_pm_price(bias_score, "down")

        # 模擬 Chainlink 價格（與 BTC 相近但有輕微延遲）
        chainlink_price = price + random.gauss(0, 5)

        # 模擬指標 JSON
        indicators = _generate_indicators(price, bias_score, i, total_steps)

        snapshot = {
            "timestamp": ts,
            "btc_price": round(price, 2),
            "pm_up_price": round(up_price, 4),
            "pm_down_price": round(down_price, 4),
            "chainlink_price": round(chainlink_price, 2),
            "bias_score": round(bias_score, 2),
            "signal": signal,
            "trading_mode": trading_mode,
            "indicators": indicators,
        }

        db.save_market_snapshot(snapshot)
        snapshots_added += 1

        if snapshots_added % 200 == 0:
            pct = snapshots_added / total_steps * 100
            print(f"   進度: {snapshots_added}/{total_steps} ({pct:.0f}%) | BTC: ${price:,.2f} | 分數: {bias_score:+.1f}")

    print(f"\n✅ 完成！已寫入 {snapshots_added} 筆合成市場快照到資料庫")
    print(f"   時間範圍: {hours} 小時前 → 現在")
    print(f"   價格範圍: ${base_price * 0.97:,.0f} - ${base_price * 1.03:,.0f}")
    print(f"\n💡 現在可以使用回測引擎進行策略驗證了！")
    return snapshots_added


def _generate_bias_score(step: int, total: int, trend: float) -> float:
    """生成模擬的偏差分數 (-100 ~ +100)"""
    # 基礎分數跟隨趨勢
    base = (trend / 500) * 40  # 趨勢貢獻
    cycle = math.sin(2 * math.pi * step / (total * 0.05)) * 25  # 短週期
    noise = random.gauss(0, 15)  # 隨機雜訊

    score = base + cycle + noise
    return max(-100, min(100, score))


def _score_to_signal(score: float) -> str:
    """將分數轉換為交易信號"""
    if score > 30:
        return "BUY_UP"
    elif score < -30:
        return "BUY_DOWN"
    return "NEUTRAL"


def _btc_to_pm_price(bias_score: float, direction: str) -> float:
    """將偏差分數轉換為 PM 合約模擬價格"""
    # 中性分數 → UP/DOWN 各 ~0.50
    norm = max(-100, min(100, bias_score)) / 200 + 0.5  # 0 ~ 1
    noise = random.gauss(0, 0.02)

    if direction == "up":
        return max(0.05, min(0.95, norm + noise))
    else:
        return max(0.05, min(0.95, 1.0 - norm + noise))


def _generate_indicators(price: float, score: float, step: int, total: int) -> dict:
    """生成模擬指標 JSON"""
    rsi = 50 + score * 0.2 + random.gauss(0, 5)
    rsi = max(10, min(90, rsi))

    macd_hist = score * 0.02 + random.gauss(0, 0.5)
    obi = score * 0.005 + random.gauss(0, 0.05)
    cvd_5m = score * 10 + random.gauss(0, 50)

    return {
        "ema": {"ema5": round(price + random.gauss(0, 20), 2),
                "ema20": round(price + random.gauss(0, 50), 2),
                "score": round(score * 0.1, 2)},
        "rsi": {"value": round(rsi, 2),
                "score": round((rsi - 50) * 0.1, 2)},
        "macd": {"histogram": round(macd_hist, 4),
                 "score": round(macd_hist * 5, 2)},
        "obi": {"value": round(obi, 4),
                "score": round(obi * 10, 2)},
        "cvd": {"cvd_5m": round(cvd_5m, 2),
                "score": round(cvd_5m * 0.01, 2)},
        "vwap": {"value": round(price + random.gauss(0, 30), 2),
                 "score": round(score * 0.05, 2)},
        "ha": {"direction": "UP" if score > 0 else "DOWN",
               "consecutive": random.randint(1, 4),
               "score": round(score * 0.06, 2)},
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CheeseDog 合成數據生成器")
    parser.add_argument("--hours", type=int, default=24, help="模擬時間（小時）")
    parser.add_argument("--price", type=float, default=96500.0, help="BTC 起始價格")
    parser.add_argument("--volatility", type=float, default=0.0003, help="波動率")
    args = parser.parse_args()

    generate_synthetic_data(
        hours=args.hours,
        base_price=args.price,
        volatility=args.volatility,
    )
