"""
策略參數校正優化器 (Calibration Optimizer)
讀取 data/cheesedog-1.db，測試不同權重組合的效果。
"""

import sys
import os
import sqlite3
import logging
from pathlib import Path
import copy

# 加入專案路徑
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.performance.backtester import Backtester, BacktestConfig
from app import config

# 設定日誌
logging.basicConfig(level=logging.ERROR, format="%(message)s") # Only show errors from backend
logger = logging.getLogger("cheesedog.optimizer")

# Force UTF-8 for stdout
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


TARGET_DB_PATH = Path(__file__).parent.parent.parent / "data" / "cheesedog-1.db"

def load_snapshots(limit=50000):
    if not TARGET_DB_PATH.exists():
        print(f"❌ 找不到資料庫: {TARGET_DB_PATH}")
        return []
    conn = sqlite3.connect(str(TARGET_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp ASC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def run_test(name, weights, snapshots):
    print(f"\n[Test] {name}")
    sys.stdout.flush()
    
    # 暫時覆蓋全域權重
    original_weights = copy.deepcopy(config.BIAS_WEIGHTS)
    config.BIAS_WEIGHTS = weights
    
    bt_config = BacktestConfig(
        initial_balance=10000.0,
        trading_mode="balanced",
        use_fees=True,            # 啟用手續費來看真實獲利能力
        use_profit_filter=False,  # 關閉過濾器以測試信號品質
        use_saved_signals=False,  # 強制重算
        disable_cooldown=True
    )
    
    try:
        backtester = Backtester(bt_config)
        report = backtester.run(snapshots=snapshots)
        s = report['summary']
        
        print(f"   Trades: {s['total_trades']:<4} | WinRate: {s['win_rate']:>5.1f}% | PnL: ${s['total_pnl']:>8.2f} | Sharpe: {s['sharpe_ratio']:>4.2f}")
    except Exception as e:
        print(f"   [Error] {e}")
    finally:
        # 還原
        config.BIAS_WEIGHTS = original_weights
        sys.stdout.flush()

def main():
    snapshots = load_snapshots(limit=30000)
    if not snapshots:
        return
    
    print(f"[Info] Loaded {len(snapshots)} snapshots")
    print("[Info] Starting calibration...\n")
    sys.stdout.flush()
    
    # 1. 基準 (Baseline)
    baseline = config.BIAS_WEIGHTS.copy()
    run_test("Baseline", baseline, snapshots)
    
    # 2. 趨勢加強 (Trend Follower)
    trend = baseline.copy()
    trend['ema'] = 15     # Was 10
    trend['macd'] = 10    # Was 8
    trend['ha'] = 20      # Was 15
    trend['rsi'] = 2
    trend['bb'] = 2
    run_test("Trend Focused", trend, snapshots)

    # 3. 反轉加強 (Mean Reversion)
    reversion = baseline.copy()
    reversion['ema'] = 2
    reversion['macd'] = 2
    reversion['rsi'] = 15   # Was 10
    reversion['bb'] = 15    # Was 12
    reversion['obi'] = 10   # Was 8
    run_test("Reversion Focused", reversion, snapshots)
    
    # 4. 籌碼加強 (Orderbook/Flow)
    flow = baseline.copy()
    flow['obi'] = 15      # Was 10
    flow['walls'] = 10    # Was 5
    flow['cvd'] = 15      # Was 10
    flow['poc'] = 8       # Was 5
    run_test("Flow Focused", flow, snapshots)

if __name__ == "__main__":
    main()
