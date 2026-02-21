"""
專用於使用指定的 DB 檔案進行策略校正 (Calibration) 並驗證 V3.3.0
讀取 data/cheesedog_market_data_20260221.db 中的歷史 market_snapshots，進行回測分析。
"""

import sys
import os
import sqlite3
import json
import logging
from pathlib import Path

# 加入專案路徑以引用 app 模組
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.performance.backtester import Backtester, BacktestConfig
from app import config

# 設定日誌
logging.basicConfig(level=logging.ERROR, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("cheesedog.calibrate")

TARGET_DB_PATH = Path(__file__).parent.parent.parent / "data" / "cheesedog_market_data_20260221.db"

def load_snapshots_from_specific_db(db_path: Path, limit: int = 50000) -> list:
    """從指定的 DB 檔案讀取 market_snapshots"""
    if not db_path.exists():
        logger.error(f"❌ 找不到資料庫檔案: {db_path}")
        return []
    
    logger.info(f"📂 正在從 {db_path.name} 載入歷史數據...")
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM market_snapshots ORDER BY timestamp ASC LIMIT ?", 
            (limit,)
        ).fetchall()
        conn.close()
        
        snapshots = [dict(row) for row in rows]
        logger.info(f"✅ 成功載入 {len(snapshots)} 筆歷史快照")
        return snapshots
    except Exception as e:
        logger.error(f"❌ 讀取資料庫失敗: {e}")
        return []

def run_calibration_baseline():
    """執行基準回測 (Baseline)"""
    snapshots = load_snapshots_from_specific_db(TARGET_DB_PATH, limit=50000)
    
    if not snapshots:
        return

    logger.info("🚀 開始執行 V3.3.0 強制驗證回測...")
    
    # 這裡啟用了 Anti-FOMO 會被觸發 (因為我們 use_saved_signals=False 會重新走交易邏輯)
    bt_config = BacktestConfig(
        initial_balance=1000.0,
        trading_mode="balanced",
        use_fees=True,
        use_profit_filter=True, 
        use_saved_signals=False,
        disable_cooldown=False
    )
    
    backtester = Backtester(bt_config)
    report = backtester.run(snapshots=snapshots)
    
    # 輸出摘要
    summary = report.get("summary", {})
    with open("backtest_summary.json", "w") as f:
        json.dump(summary, f, indent=4)
    print("Backtest finished. Summary written to backtest_summary.json")

if __name__ == "__main__":
    run_calibration_baseline()
