"""
專用於使用指定的 DB 檔案進行策略校正 (Calibration)
讀取 data/cheesedog-1.db 中的歷史 market_snapshots，進行回測分析。
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("cheesedog.calibrate")

TARGET_DB_PATH = Path(__file__).parent.parent.parent / "data" / "cheesedog-1.db"

def load_snapshots_from_specific_db(db_path: Path, limit: int = 10000) -> list:
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

    logger.info("🚀 開始執行基準回測 (Baseline Calibration)...")
    
    # 使用當前配置進行回測
    # 注意：我們使用 use_saved_signals=False 來強制重新計算信號
    # 這樣才能驗證當前的參數設置，而不是歷史紀錄中的舊信號
    bt_config = BacktestConfig(
        initial_balance=10000.0,
        trading_mode="balanced",
        use_fees=False,  # 暫時關閉手續費，排除干擾
        use_profit_filter=False,  # 暫時關閉利潤過濾器，查看原始信號量
        use_saved_signals=False,
        disable_cooldown=True     # 禁用冷卻期，盡可能多交易
    )
    
    backtester = Backtester(bt_config)
    report = backtester.run(snapshots=snapshots)
    
    # 輸出摘要
    summary = report.get("summary", {})
    print("\n" + "="*60)
    print(f"📊 校正回測結果 (Baseline: Balanced Mode)")
    print("="*60)
    print(f"交易次數: {summary.get('total_trades', 0)}")
    print(f"勝率    : {summary.get('win_rate', 0):.2f}%")
    print(f"總損益  : ${summary.get('total_pnl', 0):.2f}")
    print(f"收益率  : {summary.get('total_return_pct', 0):.2f}%")
    print(f"最大回撤: {summary.get('max_drawdown_pct', 0):.2f}%")
    print(f"夏普比率: {summary.get('sharpe_ratio', 0):.2f}")
    print(f"獲利因子: {summary.get('profit_factor', 0):.2f}")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_calibration_baseline()
